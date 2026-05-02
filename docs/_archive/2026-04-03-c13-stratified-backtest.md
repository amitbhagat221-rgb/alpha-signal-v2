# Session C13 — Segment-Stratified Backtest + VIX Regime Module
# Claude Code Implementation Instructions
# Date: 2026-04-03
# Prereq: C12 complete. universe.csv has cap_tier, adtv_6m_cr columns.

## OBJECTIVE

Two builds:
1. Add `--by-tier` flag to `24_backtester.py` that computes IC per signal PER cap_tier. This is the moment of truth — we find out if "dead" signals (Piotroski t=0.33, promoter t=-0.15, momentum t=0.74 on unified universe) come alive within their natural segment.
2. Build `32_regime_module.py` — fetches India VIX daily, computes regime state (CALM/NORMAL/CAUTION/CRISIS), outputs allocation shift recommendations.

## CRITICAL RULES (from CLAUDE.md)

1. Always activate venv first: `source ~/alpha-signal/venv/bin/activate`
2. Never run two harvester scripts simultaneously
3. Smoke test before full runs
4. 2-second delay between API calls
5. pip installs: always use `--break-system-packages`

## PART 1: SEGMENT-STRATIFIED BACKTESTER

### 1a. Understand Current Backtester

```bash
source ~/alpha-signal/venv/bin/activate
cd ~/alpha-signal

# Read the existing backtester
cat scripts/24_backtester.py | head -100
grep -n "def " scripts/24_backtester.py
grep -n "ic\|IC\|spearman\|rank" scripts/24_backtester.py | head -30

# Check what modes exist
grep -n "proxy\|recon\|pit\|PIT" scripts/24_backtester.py | head -20

# Check existing outputs
ls data/backtest/
head -5 data/backtest/signal_validation_report.csv 2>/dev/null
```

The backtester has 3 modes:
- **PIT** (point-in-time): uses historical enriched snapshots (~3 weeks of data, too few periods)
- **Proxy**: current signal values projected over 3yr price history. Good for slow-moving fundamentals.
- **Recon** (`--recon`): rebuilds signals from raw data with filing lags. No look-ahead bias.

The `--by-tier` enhancement applies to ALL modes but is most useful with **proxy** mode (which has 35 monthly periods) and **recon** mode.

### 1b. Add --by-tier Flag

Add a new CLI flag:
```python
parser.add_argument('--by-tier', action='store_true', help='Compute IC per cap_tier segment')
```

### 1c. Core Logic: Stratified IC Computation

After the existing IC computation (which produces universe-wide IC per period), add a stratified layer:

```python
if args.by_tier:
    # Load cap_tier from universe.csv
    universe = pd.read_csv('data/harvester/universe.csv', usecols=['ticker', 'sid', 'cap_tier'])
    
    # Merge cap_tier into the signal+return dataframe
    # (the join key depends on mode — check what the existing df uses: ticker, sid, or symbol)
    
    tier_results = []
    for tier in ['LARGE', 'MID', 'SMALL']:
        tier_df = merged_df[merged_df['cap_tier'] == tier]
        if len(tier_df) < 30:  # minimum stocks for meaningful IC
            continue
        
        for signal_col in signal_columns:
            ics = []
            for period in periods:
                period_df = tier_df[tier_df['period'] == period]
                if len(period_df) < 20:
                    continue
                ic = period_df[signal_col].corr(period_df['fwd_return'], method='spearman')
                ics.append(ic)
            
            if len(ics) >= 10:  # minimum periods for meaningful t-stat
                mean_ic = np.mean(ics)
                std_ic = np.std(ics, ddof=1)
                icir = mean_ic / std_ic if std_ic > 0 else 0
                t_stat = mean_ic / (std_ic / np.sqrt(len(ics))) if std_ic > 0 else 0
                
                tier_results.append({
                    'signal': signal_col,
                    'cap_tier': tier,
                    'n_periods': len(ics),
                    'n_stocks_avg': int(tier_df.groupby('period').size().mean()),
                    'mean_ic': mean_ic,
                    'std_ic': std_ic,
                    'icir': icir,
                    't_stat': t_stat,
                })
    
    tier_report = pd.DataFrame(tier_results)
    tier_report.to_csv('data/backtest/signal_validation_by_tier.csv', index=False)
    
    # Pretty print
    print("\n" + "="*80)
    print("SEGMENT-STRATIFIED IC REPORT")
    print("="*80)
    for tier in ['LARGE', 'MID', 'SMALL']:
        print(f"\n--- {tier} ---")
        sub = tier_report[tier_report['cap_tier'] == tier].sort_values('t_stat', ascending=False)
        for _, row in sub.iterrows():
            verdict = "✓ KEEP" if abs(row['t_stat']) >= 2.5 else "✗ DROP"
            direction = "INVERTED" if row['t_stat'] < -2.0 else ""
            print(f"  {row['signal']:20s}  IC={row['mean_ic']:+.3f}  ICIR={row['icir']:+.3f}  "
                  f"t={row['t_stat']:+.2f}  n={row['n_periods']:2d} periods  "
                  f"~{row['n_stocks_avg']} stocks  {verdict} {direction}")
```

### 1d. Also Compute Long/Short Spread Per Tier

For each signal within each tier, compute quintile L/S returns:

```python
# Within each tier and period:
# Q1 = top quintile of signal, Q5 = bottom quintile
# L/S spread = mean(Q1 returns) - mean(Q5 returns)
# This gives annualized L/S in addition to IC
```

This is important because IC can be positive but L/S can be negative if the relationship is noisy. Both metrics should be in the tier report.

### 1e. Handle the Join Correctly

The backtester currently works with different identifiers depending on mode:
- Proxy mode likely uses NSE symbols/tickers from the enriched CSV
- Recon mode may use internal identifiers

CHECK the existing code to see how stocks are identified. The join path to `cap_tier` from universe.csv may be:
- Direct: `ticker` column matches
- Via universe: `symbol` → `universe.ticker` → `universe.cap_tier`
- Via sid: `sid` in signal CSV → `universe.sid`

Read the existing code carefully before choosing join strategy. The C12 session's integration script (08) already has the join pattern — look at how IT gets cap_tier onto the enriched dataframe.

### 1f. Price Data for Full Universe

The current backtester may only have prices for ~500-600 stocks (the screener universe). For meaningful per-tier IC, we need prices for MORE stocks — ideally all 2,500, but at minimum the top ~500 per tier.

**Check what price data exists:**
```bash
# Check if there's a cached price directory
ls data/backtest/prices/ 2>/dev/null
ls data/backtest/*.parquet 2>/dev/null
# Check the backtester's download function
grep -n "download\|yfinance\|price" scripts/24_backtester.py | head -20
```

**If the backtester already downloads prices:** Add logic to ensure it downloads for stocks across ALL tiers, not just the screener universe. The `--no-download` flag should use cached prices; without it, it should download fresh.

**If prices need separate download:** The backtester's `--recon` flag already downloads 3yr prices. Extend it to cover all 2,500 stocks (or at minimum: all 100 LARGE + 150 MID + top 500 SMALL by ADTV). This is the slow part — 2-3 hours for 2,500 tickers via yfinance.

**IMPORTANT:** The backtester already has a `--no-download` flag. For the first run with `--by-tier`, you WILL need to download prices for stocks not previously covered. Subsequent runs can use `--no-download`.

### 1g. Proxy Mode with Tier

In proxy mode, the backtester projects current signal values back over 3yr price history. For `--by-tier`:
1. Load current signal values (piotroski, accruals, consensus, promoter, smart_money, value scores)
2. Load cap_tier per stock
3. Load 3yr monthly returns per stock
4. For each month: compute Spearman rank correlation between signal and next-month return, WITHIN each cap_tier
5. Aggregate across months → IC, ICIR, t-stat per signal per tier

### 1h. Run Commands

```bash
# Smoke test (quick check with --no-download if prices cached)
python scripts/24_backtester.py --by-tier --no-download --smoke

# Full proxy run (uses cached prices if available)
python scripts/24_backtester.py --by-tier --no-download

# Full run with fresh price download (SLOW — 2-3 hours)
python scripts/24_backtester.py --by-tier

# Recon mode with tier stratification
python scripts/24_backtester.py --by-tier --recon
```

### 1i. Expected Results (Hypotheses to Test)

Based on deep research, we EXPECT:

| Signal | Large | Mid | Small | Rationale |
|--------|-------|-----|-------|-----------|
| consensus | t>3.0 ✓ | t~2.0 | t<1.0 | Coverage concentrates in large caps |
| value/EY | t<1.0 | t~1.5 | t>2.5 ✓ | Value premium lives in small caps |
| piotroski | t<1.0 | t~1.5 | t>2.0 ✓? | Quality screen most useful where junk lives |
| promoter | t<1.0 | t~1.5 | t>2.0 ✓? | Info asymmetry highest in small caps |
| momentum | t>2.0 ✓? | t~1.5 | t<0 | Reverses in illiquid stocks |
| accruals | t<-1.0 | t~0 | t<-2.0 | INVERTED everywhere in India |
| smart_money | t>1.5? | t~1.0 | t<1.0 | Bulk deals are large-cap phenomenon |

If even 2-3 of these hypotheses confirm, v3 is validated. The architecture is correct.

### 1j. Output Files

- `data/backtest/signal_validation_by_tier.csv` — per-signal, per-tier IC/ICIR/t-stat
- `data/backtest/tier_ls_spreads.csv` — per-signal, per-tier quintile L/S returns
- Update `data/backtest/backtest_report.html` with a new "By Tier" section
- Print summary table to stdout

---

## PART 2: VIX REGIME MODULE

### 2a. Create `scripts/32_regime_module.py`

NOTE: Check if `32_regime_module.py` already exists from a previous session or if there's a naming conflict with the tier assignment script. The CLAUDE.md lists `32_regime_module.py` but C12 created `32_tier_assignment.py`. If there's a conflict, use the next available number or check what exists:

```bash
ls scripts/32_* scripts/33_* 2>/dev/null
```

If 32 is taken by tier_assignment, use a different number or rename per CLAUDE.md convention.

### 2b. Fetch India VIX Daily

```python
import yfinance as yf

def fetch_india_vix(period='3y'):
    """Fetch India VIX daily data from yfinance."""
    vix = yf.download('^INDIAVIX', period=period)
    # Returns OHLCV — use 'Close' as the VIX level
    # Save to data/reference/india_vix.csv
    vix[['Close']].rename(columns={'Close': 'vix'}).to_csv('data/reference/india_vix.csv')
    return vix
```

**Verify this works from Oracle VM:**
```bash
python -c "import yfinance as yf; df = yf.download('^INDIAVIX', period='1mo'); print(df.tail())"
```

If `^INDIAVIX` doesn't work, try `INDIAVIX.NS` or `NIFVIX.NS`.

### 2c. Regime Classification

```python
REGIME_THRESHOLDS = {
    'CALM':    (0, 13),      # VIX <= 13: overweight mid+small
    'NORMAL':  (13, 25),     # VIX 13-25: baseline allocation
    'CAUTION': (25, 35),     # VIX 25-35: overweight large, reduce small
    'CRISIS':  (35, float('inf')),  # VIX > 35: maximum defensive
}

ALLOCATION_WEIGHTS = {
    'CALM':    {'LARGE': 0.30, 'MID': 0.35, 'SMALL': 0.35},
    'NORMAL':  {'LARGE': 0.40, 'MID': 0.30, 'SMALL': 0.30},
    'CAUTION': {'LARGE': 0.55, 'MID': 0.25, 'SMALL': 0.20},
    'CRISIS':  {'LARGE': 0.70, 'MID': 0.20, 'SMALL': 0.10},
}
```

### 2d. Hysteresis Logic

Don't flip-flop on regime changes. Require persistence:

```python
def compute_regime(vix_series, lookback=3):
    """
    Assign regime based on VIX level.
    Hysteresis: require VIX to stay in new regime for `lookback` consecutive days
    before officially transitioning.
    """
    current_vix = vix_series.iloc[-1]
    
    # Determine raw regime from current VIX
    raw_regime = 'NORMAL'
    for regime, (low, high) in REGIME_THRESHOLDS.items():
        if low <= current_vix < high:
            raw_regime = regime
            break
    
    # Check if last `lookback` days all agree
    recent = vix_series.iloc[-lookback:]
    regimes = []
    for v in recent:
        for regime, (low, high) in REGIME_THRESHOLDS.items():
            if low <= v < high:
                regimes.append(regime)
                break
    
    if len(set(regimes)) == 1:
        # All recent days agree — transition confirmed
        return raw_regime
    else:
        # Mixed signals — stay in previous regime (default NORMAL)
        # In production, read previous regime from a state file
        return _read_previous_regime() or 'NORMAL'
```

### 2e. Output

The module should produce:

1. **`data/reference/india_vix.csv`** — daily VIX history (refreshed daily via cron)
2. **`data/reference/regime_state.json`** — current regime + allocation weights:
```json
{
    "date": "2026-04-03",
    "vix_close": 14.2,
    "regime": "NORMAL",
    "regime_since": "2026-03-15",
    "allocation": {"LARGE": 0.40, "MID": 0.30, "SMALL": 0.30},
    "previous_regime": "CAUTION",
    "transition_date": "2026-03-15"
}
```
3. **Stdout summary** when run:
```
India VIX: 14.2 (as of 2026-04-03)
Regime: NORMAL (since 2026-03-15)
Allocation: LARGE=40% | MID=30% | SMALL=30%
```

### 2f. Integration with Pipeline

In `run_pipeline.sh`, add the regime module to the daily cron sequence:
```bash
# After existing steps, before scoring:
python scripts/32_regime_module.py --refresh
```

The allocation weights from `regime_state.json` will be consumed by `36_segment_models.py` (D17) when it's built. For now, the module just produces the state file.

### 2g. CLI Interface

```bash
python scripts/32_regime_module.py --refresh    # fetch latest VIX + compute regime
python scripts/32_regime_module.py --history     # print last 30 days of regime
python scripts/32_regime_module.py --backtest    # compute regime for all historical dates (for backtester integration)
```

The `--backtest` flag is important: it produces a CSV of `(date, vix, regime, allocation_L, allocation_M, allocation_S)` for every trading day — this will be consumed by the backtester to apply regime-aware weighting to L/S portfolios.

### 2h. Smoke Test

```bash
python scripts/32_regime_module.py --refresh
# Should print current VIX, regime, allocation
cat data/reference/regime_state.json
```

---

## PART 3: FULL INTEGRATION TEST

After both parts are done:

```bash
source ~/alpha-signal/venv/bin/activate
cd ~/alpha-signal

# 1. Verify regime module works
python scripts/32_regime_module.py --refresh

# 2. Run stratified backtester (proxy mode, using cached prices if available)
python scripts/24_backtester.py --by-tier --no-download

# 3. If no cached prices for full universe, download first:
python scripts/24_backtester.py --by-tier

# 4. Examine results — THIS IS THE KEY OUTPUT
cat data/backtest/signal_validation_by_tier.csv

# 5. Quick analysis
python -c "
import pandas as pd
df = pd.read_csv('data/backtest/signal_validation_by_tier.csv')
print(df.to_string(index=False))
print()
print('=== SIGNALS WITH t >= 2.5 BY TIER ===')
valid = df[df['t_stat'].abs() >= 2.5].sort_values(['cap_tier', 't_stat'], ascending=[True, False])
print(valid.to_string(index=False))
"
```

---

## PART 4: GIT COMMIT

```bash
cd ~/alpha-signal
git add -A
git commit -m "C13: Segment-stratified backtest + VIX regime module

- MODIFIED: 24_backtester.py — added --by-tier flag for per-segment IC/ICIR/t-stat
- NEW: 32_regime_module.py (or appropriate number) — India VIX fetch + regime classification
- NEW: data/backtest/signal_validation_by_tier.csv — per-signal per-tier validation
- NEW: data/reference/india_vix.csv — daily VIX history
- NEW: data/reference/regime_state.json — current regime + allocation weights
- Hysteresis: 3-day persistence required for regime transitions
- Key finding: [FILL IN which signals validated per tier]
"
```

---

## IMPORTANT NOTES FOR CLAUDE CODE

1. **Read `24_backtester.py` thoroughly first.** It has complex logic for proxy/PIT/recon modes. The `--by-tier` addition should AUGMENT existing output, not replace it. Universe-wide IC is still computed — tier IC is additional.

2. **The price download is the bottleneck.** If the backtester already has cached prices for ~500 stocks, the `--by-tier` analysis on those 500 still gives useful signal — it just won't have great SMALL cap coverage. Run with `--no-download` first to see what's available, then decide if full download is needed.

3. **Minimum sample sizes matter.** Don't compute IC for a tier-signal combination with fewer than 20 stocks per period or fewer than 10 periods. Print warnings for thin slices.

4. **The LARGE tier only has 100 stocks.** With quintile sorts that's 20 per quintile — thin but usable. MID has 150 (30 per quintile — good). SMALL has 2,250 but you may only have prices for ~500 of them initially.

5. **Check for script number conflicts.** CLAUDE.md says `32_regime_module.py` but C12 may have used 32 for tier_assignment. Check `ls scripts/32_*` and use the correct number.

6. **VIX ticker verification.** Test `^INDIAVIX` from the VM before building the full module:
   ```bash
   python -c "import yfinance as yf; print(yf.download('^INDIAVIX', period='5d'))"
   ```
   If it fails, try `INDIAVIX.NS`, `^NSEBANK` (different index but confirms yfinance connectivity), or fall back to NSE website scraping.

7. **The regime module is LOW RISK / HIGH VALUE.** Even if VIX data fetch has issues, the module is small and self-contained. Don't let VIX problems block the backtester work.

8. **Focus on the backtester first.** The stratified IC results are the critical output of C13. The regime module is important but secondary. If time is constrained, complete Part 1 fully, commit, then do Part 2.

9. **Backtester results will inform D14-D17 decisions.** If promoter signal shows t>2.5 in SMALL tier, it stays in the small-cap model. If momentum shows t>2.5 in LARGE tier, it gets promoted to primary signal. If Piotroski comes alive in SMALL, the quality gate design in D14 is validated. Document all findings in the commit message.

10. **Existing `--recon` flag with `--by-tier`:** The recon mode reconstructs signals from raw fundamentals with filing lags. Running `--recon --by-tier` would give the gold-standard per-tier validation, but it's the slowest mode. Run proxy first, recon second if time permits.