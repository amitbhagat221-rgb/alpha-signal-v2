# Session C12 — Tier Infrastructure + Within-Segment Ranking
# Claude Code Implementation Instructions
# Date: 2026-04-03
# Context: Read CLAUDE.md (v3) first. This is the most important architectural change in the project.

## OBJECTIVE

Add market-cap tier awareness to the entire Alpha Signal pipeline. After this session, every percentile rank in every signal script will be computed WITHIN segment (large/mid/small), not across the full 2,500-stock universe. This is the single highest-impact structural change — research shows signals that "failed" universe-wide (Piotroski t=0.33, promoter t=-0.15, momentum t=0.74) are expected to show significance within their natural segment.

## CRITICAL RULES (from CLAUDE.md)

1. Always activate venv first: `source ~/alpha-signal/venv/bin/activate`
2. Never run two harvester scripts simultaneously
3. Smoke test with 3 stocks before any full run
4. 2-second delay between API calls minimum
5. pip installs: always use `--break-system-packages` flag
6. Tickertape SIDs ≠ NSE tickers — always use universe.csv SIDs
7. Never call build_universe() — always use --resume

## STEP 1: Understand Current State

Read these files first to understand the current codebase:
```bash
source ~/alpha-signal/venv/bin/activate
cd ~/alpha-signal

# Read CLAUDE.md for full project context
cat CLAUDE.md

# Understand universe structure
head -5 data/harvester/universe.csv
wc -l data/harvester/universe.csv

# Understand current screener — find all rank() calls
grep -n "rank(" scripts/03_screener.py

# Understand current integration
grep -n "rank\|pctile\|percentile\|signal" scripts/08_integrate_sentiment.py | head -40

# Understand signal scripts
grep -n "rank(" scripts/28_accruals.py
grep -n "rank(" scripts/29_consensus_signal.py
grep -n "rank(" scripts/30_promoter_signal.py
grep -n "rank(" scripts/16_smart_money.py
```

## STEP 2: Build Tier Assignment Script

Create a NEW script `scripts/32_tier_assignment.py` that:

### 2a. Fetches market cap for all 2,500 stocks

- Read `data/harvester/universe.csv` (has columns: sid, name, ticker, sector, in_nifty500)
- For each stock, fetch market cap using yfinance: `yf.Ticker(f"{ticker}.NS").info.get('marketCap')`
- IMPORTANT: yfinance .info calls are slow and can fail. Use batch approach:
  - Process in chunks of 50
  - 2-second delay between chunks
  - Checkpoint every 200 stocks to a temp CSV
  - Resume capability via `--resume` flag reading checkpoint
  - Log failures to errors, skip and continue
  - Some tickers won't match yfinance (different naming). Handle gracefully.
- Alternative faster approach if .info is too slow: use yfinance `download()` to get latest close price, then multiply by shares outstanding from balance sheet data you already have in `annual_balancesheet.csv`. Check if a "Total Shares Outstanding" or similar column exists.
- Another alternative: check if Tickertape keyRatios in `__NEXT_DATA__` has market cap. Check `slug_map.csv` + tickertape_utils.py for existing infrastructure.

### 2b. Assigns cap_tier

```python
# Sort by market_cap descending
# Rank 1-100 = LARGE
# Rank 101-250 = MID  
# Rank 251+ = SMALL
# Stocks with no market cap data = SMALL (conservative assumption)
```

Use SEBI's methodology: rank by FULL market capitalization (not free-float).

### 2c. Computes 6-month ADTV

- ADTV = Average Daily Turnover Value = avg(close × volume) over last ~125 trading days
- Use yfinance `download(ticker, period="6mo")` to get OHLCV
- Compute: `adtv_6m = (df['Close'] * df['Volume']).mean()`
- Convert to crores: `adtv_6m_cr = adtv_6m / 1e7`
- This can be batched more efficiently than .info calls
- Checkpoint every 200 stocks

### 2d. Updates universe.csv

- Add columns: `market_cap`, `market_cap_rank`, `cap_tier`, `adtv_6m_cr`
- Write updated universe.csv IN PLACE (backup first!)
- Print summary: count per tier, median market cap per tier, median ADTV per tier

### CLI interface:
```bash
python scripts/32_tier_assignment.py --resume    # resume from checkpoint
python scripts/32_tier_assignment.py --refresh   # force re-fetch all
python scripts/32_tier_assignment.py --smoke     # test with 10 stocks only
```

### Smoke test:
```bash
python scripts/32_tier_assignment.py --smoke
# Verify: RELIANCE should be LARGE, some known mid-cap should be MID, etc.
# Print: tier value_counts()
```

### Expected output:
```
LARGE    100
MID      150
SMALL    ~2250
```

## STEP 3: Modify 03_screener.py — Within-Segment Ranking

This is the BIGGEST change. The screener computes value, quality, momentum, and growth sub-scores using percentile ranks. ALL of these must become within-segment.

### 3a. Load cap_tier at the start

Near the top of the script where universe data is loaded, join `cap_tier` from `universe.csv`:

```python
universe = pd.read_csv('data/harvester/universe.csv')
# Ensure cap_tier exists
assert 'cap_tier' in universe.columns, "Run 32_tier_assignment.py first!"
```

Merge cap_tier into the working dataframe early (before any ranking).

### 3b. Replace ALL rank(pct=True) calls

Search for every instance of `.rank(pct=True)` in the file. Each one needs to become:

```python
# BEFORE (v2):
df['earnings_yield_score'] = df['earnings_yield'].rank(pct=True) * 100

# AFTER (v3):
df['earnings_yield_score'] = df.groupby('cap_tier')['earnings_yield'].rank(pct=True) * 100
```

Do this for EVERY rank() call. Common ones to look for:
- earnings_yield (value)
- pb_ratio or book_to_price (value)
- roe_score (quality)
- profit_margin_score (quality)
- debt_to_equity_score (quality) — NOTE: already neutralised for financials (Fix 2)
- ret_1m, ret_3m, ret_6m, ret_1y, mom_6m_adj, mom_12m_adj (momentum)
- RSI score
- DMA score
- revenue_growth, eps_growth (growth)

### 3c. Keep sector z-scores as-is

The sector z-scores (Fix 1 from pre-Phase-C) are ORTHOGONAL to segment ranking. A stock should be scored relative to BOTH its sector AND its cap tier. The sector z-score computation (MAD-based) should NOT change. The segment ranking is applied AFTER sector z-scoring where both exist, or independently where only one applies.

If the code currently does:
```python
z = (value - sector_median) / (1.4826 * MAD)
score = norm.cdf(clip(z, -4, 4)) * 100
```
This stays. But if that score is THEN ranked across the universe, THAT rank becomes within-segment.

### 3d. Momentum: DROP for small caps

After computing momentum scores, set them to neutral (50) for SMALL cap tier:
```python
# Momentum reverses in illiquid small caps — neutralize
momentum_cols = ['ret_1m_score', 'ret_3m_score', 'ret_6m_score', 'ret_1y_score', 
                 'mom_6m_adj_score', 'mom_12m_adj_score']
for col in momentum_cols:
    if col in df.columns:
        df.loc[df['cap_tier'] == 'SMALL', col] = 50.0
```

This is backed by research: illiquid stocks exhibit reversals, not momentum (Pacific-Basin Finance Journal).

### 3e. Smoke test

```bash
python scripts/03_screener.py  # or however it's normally invoked
```

Verify with 5 known stocks across tiers:
- A large-cap (RELIANCE): value score should reflect ranking vs other large caps
- A mid-cap: should be ranked vs mid-cap peers
- A small-cap: momentum scores should be 50 (neutralised)

Print before/after comparison for these 5 stocks to verify scores shifted.

## STEP 4: Modify Signal Scripts — Within-Segment Ranking

Each of these scripts computes percentile ranks. ALL must become within-segment.

### 4a. scripts/28_accruals.py

- Joins `cap_tier` from universe.csv (join on `sid`)
- Changes: `cf_accruals_ratio`, `bs_accruals_ratio`, `eps_cv`, `earnings_beat_rate` — all four component percentile ranks → `groupby('cap_tier').rank(pct=True)`
- The final weighted average (`accruals_signal`) is computed from the within-segment percentile ranks
- Output file `data/signals/accruals.csv` should now include `cap_tier` column

### 4b. scripts/29_consensus_signal.py

- Joins `cap_tier` from universe.csv (join on `sid`)
- Changes: `pt_upside`, `pt_revision`, `eps_growth_pct`, `revenue_growth_pct` — all percentile ranks → `groupby('cap_tier').rank(pct=True)`
- NOTE: Many small caps will have NaN for pt_upside (no analyst coverage). The existing NaN-tolerant weighting handles this. Within-segment ranking makes the available small-cap data more meaningful among peers.
- Output file `data/signals/consensus.csv` should now include `cap_tier` column

### 4c. scripts/30_promoter_signal.py

- Joins `cap_tier` from universe.csv (join on `sid`)
- Changes: `promoter_qoq`, `promoter_trend_4q` — percentile ranks → `groupby('cap_tier').rank(pct=True)`
- `pledge_quality` stays as-is (it's absolute 0-1, not ranked)
- Output file `data/signals/promoter.csv` should now include `cap_tier` column

### 4d. scripts/16_smart_money.py

- Joins `cap_tier` from universe.csv. This script uses NSE ticker (symbol), not sid. Join path: smart_money → universe via `ticker` column.
- Changes: `bulk_score` and `delivery_score` ranking/z-scoring → within-segment
- A high delivery% in small caps means something different than in large caps (small caps naturally have higher delivery%). Within-segment ranking fixes this.
- Output file `data/smart_money/smart_money_score.csv` should now include `cap_tier` column

### Pattern for all scripts:

```python
# At the top, after loading data:
universe = pd.read_csv('data/harvester/universe.csv', usecols=['sid', 'cap_tier'])
df = df.merge(universe, on='sid', how='left')
df['cap_tier'] = df['cap_tier'].fillna('SMALL')  # conservative default

# Replace every:
df['xxx_pctile'] = df['xxx'].rank(pct=True)
# With:
df['xxx_pctile'] = df.groupby('cap_tier')['xxx'].rank(pct=True)
```

## STEP 5: Modify 08_integrate_sentiment.py — Tier-Aware Confidence Multipliers

This is where all B-phase signals (Piotroski, Accruals, Smart Money, Consensus, Promoter) are combined into adjustments on the final score.

### 5a. Load cap_tier

Join `cap_tier` into the enriched dataframe at the start of integration.

### 5b. Add confidence multiplier dict

```python
TIER_CONFIDENCE = {
    'consensus':    {'LARGE': 1.0, 'MID': 0.6, 'SMALL': 0.2},
    'value':        {'LARGE': 0.5, 'MID': 0.8, 'SMALL': 1.0},
    'piotroski':    {'LARGE': 0.3, 'MID': 0.6, 'SMALL': 0.8},  # soft signal, not gate yet
    'accruals':     {'LARGE': 0.5, 'MID': 0.8, 'SMALL': 0.5},  # inverted — use as negative screen
    'smart_money':  {'LARGE': 1.0, 'MID': 0.8, 'SMALL': 0.3},
    'promoter':     {'LARGE': 0.4, 'MID': 0.8, 'SMALL': 1.0},
    'momentum':     {'LARGE': 1.0, 'MID': 0.8, 'SMALL': 0.0},  # DROP for small caps
}
```

### 5c. Apply multipliers to each signal adjustment

Current pattern (v2):
```python
consensus_adj = (consensus_signal - 0.5) * 8  # capped ±4
```

New pattern (v3):
```python
tier = row['cap_tier']  # or vectorized via map
raw_adj = (consensus_signal - 0.5) * 8
consensus_adj = raw_adj * TIER_CONFIDENCE['consensus'].get(tier, 0.5)
# Then cap at ±4 as before
```

Apply this pattern to ALL five signal adjustments. The ±12 total cap (Fix 7) stays.

### 5d. Add cap_tier and adtv_6m_cr to output CSV

The enriched output CSV should now include:
- `cap_tier` column (LARGE/MID/SMALL)
- `adtv_6m_cr` column (for downstream liquidity filtering)
- Individual signal adjustments should be logged with their tier multiplier applied

### 5e. Add tier to email tags

The email already shows tags like `F=7/9`, `Acc=0.72`. Add `Tier=LARGE` or `Tier=S` tag.

## STEP 6: Full Pipeline Smoke Test

After ALL changes are made:

```bash
source ~/alpha-signal/venv/bin/activate
cd ~/alpha-signal

# Step 1: Run tier assignment (smoke first)
python scripts/32_tier_assignment.py --smoke
# Verify output, then full run:
python scripts/32_tier_assignment.py --resume

# Step 2: Verify universe.csv has new columns
head -3 data/harvester/universe.csv
python -c "import pandas as pd; df=pd.read_csv('data/harvester/universe.csv'); print(df['cap_tier'].value_counts()); print(df['adtv_6m_cr'].describe())"

# Step 3: Run signal scripts (they should pick up cap_tier now)
python scripts/27_piotroski.py --resume        # Piotroski doesn't rank — no change needed, but verify it still runs
python scripts/28_accruals.py --resume         # Should now rank within segment
python scripts/29_consensus_signal.py --resume # Should now rank within segment
python scripts/30_promoter_signal.py --resume  # Should now rank within segment
python scripts/16_smart_money.py               # Should now rank within segment

# Step 4: Run screener
python scripts/03_screener.py                  # or however it's invoked

# Step 5: Run integration
python scripts/08_integrate_sentiment.py       # Should apply tier confidence multipliers

# Step 6: Spot-check 5 stocks across tiers
python -c "
import pandas as pd
df = pd.read_csv('data/signals/accruals.csv')
for tier in ['LARGE', 'MID', 'SMALL']:
    sub = df[df['cap_tier']==tier]
    print(f'{tier}: n={len(sub)}, mean_signal={sub[\"accruals_signal\"].mean():.3f}, std={sub[\"accruals_signal\"].std():.3f}')
"
```

## STEP 7: Git Commit

```bash
cd ~/alpha-signal
git add -A
git commit -m "C12: Tier infrastructure + within-segment ranking

- NEW: 32_tier_assignment.py — assigns LARGE/MID/SMALL cap_tier + adtv_6m
- MODIFIED: 03_screener.py — all rank(pct=True) → groupby('cap_tier').rank(pct=True)
- MODIFIED: 03_screener.py — momentum neutralised (=50) for SMALL tier
- MODIFIED: 28_accruals.py — within-segment percentile ranking
- MODIFIED: 29_consensus_signal.py — within-segment percentile ranking
- MODIFIED: 30_promoter_signal.py — within-segment percentile ranking
- MODIFIED: 16_smart_money.py — within-segment percentile ranking
- MODIFIED: 08_integrate_sentiment.py — tier-aware confidence multipliers
- MODIFIED: universe.csv — added market_cap, cap_tier, adtv_6m_cr columns
- Architecture: v3 hierarchical multi-segment model foundation
"
```

## IMPORTANT NOTES FOR CLAUDE CODE

1. **Read the actual code first** before making changes. The patterns above are pseudocode — actual variable names, column names, and code structure may differ. `grep -n "rank(" scripts/03_screener.py` to find exact locations.

2. **Backup before modifying:** `cp scripts/03_screener.py scripts/03_screener.py.v2.bak` for each file.

3. **Do NOT change Piotroski (27) or Forensic Guard (17)** — these compute absolute scores (0-9, and threshold-based), not percentile ranks. No groupby needed.

4. **Do NOT change Macro Pulse (14) or Earnings Calendar (18)** — these are market-wide, not stock-ranked.

5. **If yfinance market cap fetch is too slow** (>2 hours for 2,500 stocks), consider:
   - Using Tickertape's `__NEXT_DATA__` keyRatios which may have market cap
   - Using the latest screener output's CMP × shares from balance sheet as proxy
   - Processing only the ~500 Nifty 500 stocks first and assigning the rest as SMALL

6. **The `in_nifty500` column** already exists in universe.csv. As a FAST APPROXIMATION for tier assignment:
   - If in_nifty500 == True: could be LARGE or MID (need market cap to differentiate)
   - If in_nifty500 == False: almost certainly SMALL
   - This can bootstrap the process if full market cap fetch is slow

7. **Sector z-scores (Fix 1) are KEPT** — they are orthogonal to segment ranking. A stock is scored relative to BOTH its sector AND its cap tier.

8. **ADTV is important but not blocking** — if ADTV fetch is slow, add `cap_tier` first (using market cap only), get the rest of the pipeline working, and add ADTV in a follow-up.

9. **Test after EACH file change**, not all at once. Change 03_screener.py → test → change 28_accruals.py → test → etc.

10. **The total cap of ±12 on B-phase signals (Fix 7) stays unchanged.** Tier confidence multipliers scale the INDIVIDUAL signal adjustments before they're summed and capped.