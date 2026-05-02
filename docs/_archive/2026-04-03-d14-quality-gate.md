# Session D14 — Small-Cap Quality Gate
# Claude Code Implementation Instructions
# Date: 2026-04-04
# Prereq: C12 (cap_tier), C13 (stratified backtest), C13b (36-period reconstruction)
# Key validation: Piotroski t=2.81 in SMALL confirms quality gate is empirically justified

## OBJECTIVE

Build `33_quality_gate.py` — a quality screening layer that removes the worst junk from the small-cap universe before factor scoring, while keeping the gate soft enough to not over-exclude.

Design philosophy: **Graduated penalty, not binary kill switch.** Hard exclusion only for the most extreme cases. Everything else gets a quality penalty score that feeds into the small-cap model as a weight modifier.

## WHY THIS MATTERS

The small-cap universe (2,250 stocks) contains:
- ~500 stocks with no yfinance price data (likely delisted/suspended/zombie)
- ~200-300 more that are shell companies, GSM-listed, or loss-making for 3+ years
- The Marcellus evidence: forensic screening alone adds ~5.5% p.a.
- Asness (2018): controlling for quality more than doubles the size premium
- Our own data: Piotroski t=2.81 in small caps confirms quality discriminates returns

But being too aggressive kills the universe size and removes potential multibaggers that are temporarily distressed. The gate should remove the **uninvestable**, not the **risky**.

## THREE-TIER GATE DESIGN

### Tier 1: HARD EXCLUSION (uninvestable — remove entirely)

These stocks should never appear in any ranking or output. They are not risky investments — they are uninvestable.

```python
HARD_EXCLUSION_CRITERIA = {
    'no_price_data': True,           # No yfinance price data = likely delisted/suspended
    'net_loss_3_consecutive_years': True,  # Loss in ALL of last 3 fiscal years (not 2 of 3)
    'negative_equity': True,          # Book value < 0 = technically insolvent
    'piotroski_f_score_0_or_1': True, # F-Score 0-1 = almost every fundamental deteriorating
    'altman_z_below_0.5': True,       # Deep distress zone (not 1.1 — that's too aggressive)
}
```

**NOTE:** The threshold is intentionally MORE lenient than the original CLAUDE.md spec:
- Loss in ALL 3 years (not 2 of 3) — a company that was profitable 1 out of 3 years might be turning around
- Piotroski ≤ 1 (not ≤ 3) — F-Score of 2-3 is weak but not junk. It gets penalised, not excluded.
- Z-Score below 0.5 (not 1.1) — the grey zone (1.1-2.6) contains many legitimate small caps

**Expected exclusion:** ~300-400 stocks (13-18% of small-cap universe). Tight enough to remove genuine junk, loose enough to keep turnaround stories.

### Tier 2: HEAVY PENALTY (high risk — stays in universe but penalised)

These stocks remain in the ranking but receive a quality penalty that reduces their composite score. They need very strong value/promoter signals to overcome the penalty.

```python
HEAVY_PENALTY_CRITERIA = {
    'net_loss_2_of_3_years': -0.25,      # Quality score reduced by 0.25 (on 0-1 scale)
    'negative_3yr_cumulative_fcf': -0.20, # Burning cash consistently
    'promoter_pledge_above_50pct': -0.25, # High pledge = margin call risk
    'piotroski_f_score_2_or_3': -0.15,    # Weak fundamentals
    'altman_z_0.5_to_1.1': -0.15,         # Distress zone
    'qualified_audit_opinion': -0.20,      # If we can detect this (proxy: Beneish M > -1.78)
}
# Penalties are ADDITIVE. A stock can accumulate multiple penalties.
# Total penalty capped at -0.60 (don't completely zero out the score)
```

### Tier 3: QUALITY COMPOSITE SCORE (positive signal for survivors)

After exclusions and penalties, compute a quality composite score (0 to 1) for all surviving small-cap stocks. This feeds into the small-cap model as the "quality" signal component.

```python
QUALITY_COMPOSITE_WEIGHTS = {
    'piotroski_f_score': 0.25,      # 0-9 scaled to 0-1 (validated t=2.81)
    'cfo_to_ebitda': 0.20,          # Cash conversion — CFO/EBITDA, higher = better
    'altman_z_score': 0.15,          # Financial health (Z″ for EM)
    'pledge_inverse': 0.10,          # 1 - (pledge%/100), higher = better
    'fcf_positive_years': 0.10,      # Count of positive FCF years out of last 3
    'beneish_inverse': 0.20,         # Forensic quality — 1 if M-Score < -2.22, 0 if > -1.78, interpolated
}
```

## STEP-BY-STEP IMPLEMENTATION

### Step 1: Read Existing Scripts and Data

```bash
source ~/alpha-signal/venv/bin/activate
cd ~/alpha-signal

# Read CLAUDE.md for full context
cat CLAUDE.md

# Understand existing Piotroski computation
cat scripts/27_piotroski.py | head -80
head -5 data/signals/piotroski.csv

# Understand existing Forensic Guard (Beneish + Altman)
cat scripts/17_forensic_guard.py | head -80
# Where does forensic guard output? Check:
grep -n "to_csv\|save\|output" scripts/17_forensic_guard.py

# Understand existing data
head -5 data/harvester/universe.csv
head -5 data/harvester/annual_cashflow.csv
head -5 data/harvester/annual_balancesheet.csv
head -5 data/harvester/quarterly_income.csv
head -5 data/harvester/shareholding.csv

# Check what columns are in Piotroski output
python -c "import pandas as pd; df=pd.read_csv('data/signals/piotroski.csv'); print(df.columns.tolist()); print(df.head(3))"

# Check what forensic guard outputs (Beneish M-Score, Altman Z-Score)
# Find the output file:
grep -rn "m_score\|z_score\|forensic" scripts/17_forensic_guard.py | head -20
```

### Step 2: Build `33_quality_gate.py`

```python
#!/usr/bin/env python3
"""
33_quality_gate.py — Small-Cap Quality Gate for Alpha Signal v3

Three-tier graduated quality screening:
  Tier 1: Hard exclusion (uninvestable — delisted, 3yr consecutive loss, negative equity, F≤1, Z<0.5)
  Tier 2: Heavy penalty (high risk — loss 2/3yr, neg FCF, high pledge, F=2-3, Z=0.5-1.1)  
  Tier 3: Quality composite score (positive signal for survivors)

Output: data/signals/quality_gate.csv
  Columns: sid, ticker, cap_tier, gate_status (EXCLUDED/PENALISED/PASS),
           quality_penalty, quality_composite, exclusion_reasons, penalty_reasons

Usage:
  python scripts/33_quality_gate.py              # full run
  python scripts/33_quality_gate.py --smoke      # 50 stocks only
  python scripts/33_quality_gate.py --stats      # print gate statistics without recomputing
"""
```

### Step 3: Data Loading

Load all required data sources:

```python
def load_all_data():
    universe = pd.read_csv('data/harvester/universe.csv')
    small_caps = universe[universe['cap_tier'] == 'SMALL'].copy()
    
    # Piotroski F-Score
    piotroski = pd.read_csv('data/signals/piotroski.csv')
    # CHECK column names: likely 'sid' and 'f_score' or similar
    
    # Annual cashflow (for FCF)
    annual_cf = pd.read_csv('data/harvester/annual_cashflow.csv')
    # CHECK: what column has FCF or operating CF and capex?
    
    # Annual balance sheet (for equity, total assets)
    annual_bs = pd.read_csv('data/harvester/annual_balancesheet.csv')
    # CHECK: what column has total equity / shareholders equity?
    
    # Quarterly income (for profit/loss detection)
    quarterly_income = pd.read_csv('data/harvester/quarterly_income.csv')
    # CHECK: what column has net profit?
    
    # Shareholding (for pledge %)
    shareholding = pd.read_csv('data/harvester/shareholding.csv')
    # CHECK: what column has promoter pledge %?
    
    # Forensic guard output (Beneish M-Score, Altman Z-Score)
    # Find where 17_forensic_guard.py saves its output:
    # It might be in the enriched CSV, or a separate file
    # grep the script to find out
    
    # Price data existence check
    import glob
    priced_tickers = set()
    for f in glob.glob('data/backtest/prices/*.csv'):
        t = os.path.basename(f).replace('_NS.csv', '').replace('.csv', '')
        priced_tickers.add(t)
    
    return small_caps, piotroski, annual_cf, annual_bs, quarterly_income, shareholding, priced_tickers
```

### Step 4: Hard Exclusion Logic

```python
def apply_hard_exclusions(sid, ticker, piotroski_row, annual_data, priced_tickers):
    """
    Returns (is_excluded: bool, reasons: list[str])
    """
    reasons = []
    
    # 1. No price data
    if ticker not in priced_tickers:
        reasons.append('no_price_data')
    
    # 2. Net loss in ALL of last 3 fiscal years
    # Get last 3 years of annual net profit
    # Determine from quarterly_income (sum 4 quarters) or annual income
    # If ALL 3 are negative → exclude
    last_3yr_profits = get_last_n_years_profit(sid, annual_data, n=3)
    if last_3yr_profits is not None and len(last_3yr_profits) >= 3:
        if all(p < 0 for p in last_3yr_profits):
            reasons.append('net_loss_3_consecutive_years')
    
    # 3. Negative equity (book value < 0)
    latest_equity = get_latest_equity(sid, annual_bs)
    if latest_equity is not None and latest_equity < 0:
        reasons.append('negative_equity')
    
    # 4. Piotroski F-Score 0 or 1
    f_score = piotroski_row.get('f_score', None)  # adjust column name
    if f_score is not None and f_score <= 1:
        reasons.append(f'piotroski_f_score_{int(f_score)}')
    
    # 5. Altman Z″-Score below 0.5
    z_score = get_altman_z(sid)  # from forensic guard output
    if z_score is not None and z_score < 0.5:
        reasons.append(f'altman_z_{z_score:.2f}')
    
    is_excluded = len(reasons) > 0
    return is_excluded, reasons
```

### Step 5: Heavy Penalty Logic

```python
def compute_penalties(sid, ticker, piotroski_row, annual_data, shareholding_data):
    """
    Returns (total_penalty: float, reasons: list[str])
    Penalty is negative (reduces quality score).
    Capped at -0.60.
    """
    penalty = 0.0
    reasons = []
    
    # 1. Net loss 2 of 3 years (but not all 3 — those are excluded)
    last_3yr_profits = get_last_n_years_profit(sid, annual_data, n=3)
    if last_3yr_profits is not None and len(last_3yr_profits) >= 3:
        loss_count = sum(1 for p in last_3yr_profits if p < 0)
        if loss_count == 2:
            penalty -= 0.25
            reasons.append('net_loss_2_of_3_years')
    
    # 2. Negative 3-year cumulative FCF
    fcf_3yr = get_cumulative_fcf(sid, annual_cf, n=3)
    if fcf_3yr is not None and fcf_3yr < 0:
        penalty -= 0.20
        reasons.append('negative_3yr_cumulative_fcf')
    
    # 3. Promoter pledge above 50%
    pledge_pct = get_latest_pledge(sid, shareholding_data)
    if pledge_pct is not None and pledge_pct > 50:
        penalty -= 0.25
        reasons.append(f'promoter_pledge_{pledge_pct:.0f}pct')
    
    # 4. Piotroski F-Score 2 or 3
    f_score = piotroski_row.get('f_score', None)
    if f_score is not None and f_score in [2, 3]:
        penalty -= 0.15
        reasons.append(f'piotroski_f_score_{int(f_score)}')
    
    # 5. Altman Z between 0.5 and 1.1
    z_score = get_altman_z(sid)
    if z_score is not None and 0.5 <= z_score < 1.1:
        penalty -= 0.15
        reasons.append(f'altman_z_grey_{z_score:.2f}')
    
    # 6. Beneish M-Score above -1.78 (possible earnings manipulator)
    m_score = get_beneish_m(sid)
    if m_score is not None and m_score > -1.78:
        penalty -= 0.20
        reasons.append(f'beneish_m_{m_score:.2f}')
    
    # Cap total penalty at -0.60
    penalty = max(penalty, -0.60)
    
    return penalty, reasons
```

### Step 6: Quality Composite Score

```python
def compute_quality_composite(sid, piotroski_row, annual_data, shareholding_data):
    """
    Compute quality composite score (0 to 1) for surviving stocks.
    Higher = better quality.
    """
    components = {}
    weights = {}
    
    # 1. Piotroski F-Score (0-9 → 0-1)
    f_score = piotroski_row.get('f_score', None)
    if f_score is not None:
        components['piotroski'] = f_score / 9.0
        weights['piotroski'] = 0.25
    
    # 2. CFO/EBITDA cash conversion
    cfo = get_latest_annual_cfo(sid, annual_cf)
    ebitda = get_latest_annual_ebitda(sid)  # may need to derive from income + depreciation
    if cfo is not None and ebitda is not None and ebitda > 0:
        ratio = min(cfo / ebitda, 2.0)  # cap at 2.0 to prevent outliers
        components['cfo_to_ebitda'] = min(ratio / 1.5, 1.0)  # 1.5x conversion = perfect score
        weights['cfo_to_ebitda'] = 0.20
    
    # 3. Altman Z″-Score
    z_score = get_altman_z(sid)
    if z_score is not None:
        # Map Z to 0-1: Z<1.1 → 0, Z=1.1-2.6 → linear, Z>2.6 → 1.0
        if z_score < 1.1:
            components['altman_z'] = 0.0
        elif z_score > 2.6:
            components['altman_z'] = 1.0
        else:
            components['altman_z'] = (z_score - 1.1) / (2.6 - 1.1)
        weights['altman_z'] = 0.15
    
    # 4. Pledge inverse
    pledge_pct = get_latest_pledge(sid, shareholding_data)
    if pledge_pct is not None:
        components['pledge_inverse'] = max(0, 1 - (pledge_pct / 100))
        weights['pledge_inverse'] = 0.10
    
    # 5. FCF positive years (out of last 3)
    fcf_years = get_annual_fcf_signs(sid, annual_cf, n=3)
    if fcf_years is not None and len(fcf_years) > 0:
        components['fcf_positive'] = sum(1 for f in fcf_years if f > 0) / len(fcf_years)
        weights['fcf_positive'] = 0.10
    
    # 6. Beneish M-Score (forensic quality)
    m_score = get_beneish_m(sid)
    if m_score is not None:
        # M < -2.22 = likely clean (score 1.0)
        # M > -1.78 = likely manipulator (score 0.0)
        # Linear interpolation between
        if m_score < -2.22:
            components['beneish'] = 1.0
        elif m_score > -1.78:
            components['beneish'] = 0.0
        else:
            components['beneish'] = (m_score - (-1.78)) / (-2.22 - (-1.78))
        weights['beneish'] = 0.20
    
    # Weighted average (NaN-tolerant: exclude missing components)
    if not components:
        return np.nan, {}
    
    total_weight = sum(weights[k] for k in components)
    if total_weight == 0:
        return np.nan, components
    
    composite = sum(components[k] * weights[k] for k in components) / total_weight
    return composite, components
```

### Step 7: Main Loop

```python
def main():
    args = parse_args()
    
    # Load data
    small_caps, piotroski, annual_cf, annual_bs, quarterly_income, shareholding, priced_tickers = load_all_data()
    
    if args.smoke:
        small_caps = small_caps.head(50)
    
    results = []
    
    for _, stock in small_caps.iterrows():
        sid = stock['sid']
        ticker = stock['ticker']
        
        # Get Piotroski row for this stock
        pio_row = piotroski[piotroski['sid'] == sid].iloc[0].to_dict() if sid in piotroski['sid'].values else {}
        
        # Tier 1: Hard exclusion
        is_excluded, exclusion_reasons = apply_hard_exclusions(sid, ticker, pio_row, annual_data, priced_tickers)
        
        if is_excluded:
            results.append({
                'sid': sid,
                'ticker': ticker,
                'cap_tier': 'SMALL',
                'gate_status': 'EXCLUDED',
                'quality_penalty': -1.0,
                'quality_composite': np.nan,
                'exclusion_reasons': '|'.join(exclusion_reasons),
                'penalty_reasons': '',
                'f_score': pio_row.get('f_score', np.nan),
            })
            continue
        
        # Tier 2: Heavy penalty
        penalty, penalty_reasons = compute_penalties(sid, ticker, pio_row, annual_data, shareholding)
        
        # Tier 3: Quality composite
        composite, components = compute_quality_composite(sid, pio_row, annual_data, shareholding)
        
        # Apply penalty to composite
        adjusted_composite = max(0, (composite or 0) + penalty)
        
        gate_status = 'PENALISED' if penalty < 0 else 'PASS'
        
        results.append({
            'sid': sid,
            'ticker': ticker,
            'cap_tier': 'SMALL',
            'gate_status': gate_status,
            'quality_penalty': penalty,
            'quality_composite': composite,
            'quality_adjusted': adjusted_composite,
            'exclusion_reasons': '',
            'penalty_reasons': '|'.join(penalty_reasons),
            'f_score': pio_row.get('f_score', np.nan),
        })
    
    # Save
    results_df = pd.DataFrame(results)
    results_df.to_csv('data/signals/quality_gate.csv', index=False)
    
    # Statistics
    print_gate_statistics(results_df)
```

### Step 8: Statistics Output

```python
def print_gate_statistics(df):
    total = len(df)
    excluded = len(df[df['gate_status'] == 'EXCLUDED'])
    penalised = len(df[df['gate_status'] == 'PENALISED'])
    passed = len(df[df['gate_status'] == 'PASS'])
    
    print(f"\n{'='*70}")
    print(f"QUALITY GATE STATISTICS — SMALL CAP UNIVERSE")
    print(f"{'='*70}")
    print(f"Total small-cap stocks:    {total}")
    print(f"EXCLUDED (uninvestable):    {excluded} ({excluded/total*100:.1f}%)")
    print(f"PENALISED (high risk):     {penalised} ({penalised/total*100:.1f}%)")
    print(f"PASS (investable):         {passed} ({passed/total*100:.1f}%)")
    print(f"")
    print(f"Effective universe after gate: {penalised + passed} stocks")
    print(f"")
    
    # Exclusion reason breakdown
    if excluded > 0:
        excl = df[df['gate_status'] == 'EXCLUDED']
        all_reasons = '|'.join(excl['exclusion_reasons'].fillna('')).split('|')
        reason_counts = pd.Series(all_reasons).value_counts()
        print(f"Exclusion reasons:")
        for reason, count in reason_counts.items():
            if reason:
                print(f"  {reason:40s} {count:5d}")
    
    # Penalty reason breakdown
    if penalised > 0:
        pen = df[df['gate_status'] == 'PENALISED']
        all_reasons = '|'.join(pen['penalty_reasons'].fillna('')).split('|')
        reason_counts = pd.Series(all_reasons).value_counts()
        print(f"\nPenalty reasons:")
        for reason, count in reason_counts.items():
            if reason:
                print(f"  {reason:40s} {count:5d}")
    
    # Quality composite distribution for survivors
    survivors = df[df['gate_status'] != 'EXCLUDED']
    if len(survivors) > 0:
        print(f"\nQuality composite distribution (survivors):")
        print(f"  Mean:   {survivors['quality_composite'].mean():.3f}")
        print(f"  Median: {survivors['quality_composite'].median():.3f}")
        print(f"  Std:    {survivors['quality_composite'].std():.3f}")
        print(f"  Min:    {survivors['quality_composite'].min():.3f}")
        print(f"  Max:    {survivors['quality_composite'].max():.3f}")
    
    # Spot check: show 5 excluded, 5 penalised, 5 best pass
    print(f"\n--- Sample EXCLUDED stocks ---")
    print(df[df['gate_status'] == 'EXCLUDED'][['ticker', 'f_score', 'exclusion_reasons']].head(5).to_string(index=False))
    
    print(f"\n--- Sample PENALISED stocks ---")
    print(df[df['gate_status'] == 'PENALISED'][['ticker', 'f_score', 'quality_penalty', 'quality_adjusted', 'penalty_reasons']].head(5).to_string(index=False))
    
    print(f"\n--- Top 10 PASS stocks by quality ---")
    top = df[df['gate_status'] == 'PASS'].nlargest(10, 'quality_composite')
    print(top[['ticker', 'f_score', 'quality_composite']].to_string(index=False))
```

### Step 9: CLI Interface

```bash
python scripts/33_quality_gate.py              # full run on all 2,250 small caps
python scripts/33_quality_gate.py --smoke      # 50 stocks only
python scripts/33_quality_gate.py --stats      # print stats from existing quality_gate.csv
python scripts/33_quality_gate.py --detail TICKER  # show full breakdown for one stock
```

### Step 10: Integration with Pipeline

The quality gate output (`data/signals/quality_gate.csv`) will be consumed by `36_segment_models.py` (D17) when built. For now, it's a standalone signal file.

In the interim, `08_integrate_sentiment.py` can optionally read the gate:
```python
# After loading quality gate:
gate = pd.read_csv('data/signals/quality_gate.csv')
excluded_sids = set(gate[gate['gate_status'] == 'EXCLUDED']['sid'])

# In the enriched output, flag excluded stocks:
df['quality_gate'] = df['sid'].apply(lambda s: 'EXCLUDED' if s in excluded_sids else 'PASS')
# Don't actually remove them yet — just flag. D17 will use the flag.
```

### Step 11: Accessing Beneish M-Score and Altman Z-Score

The forensic guard (script 17) computes these. Check where it stores them:

```bash
# Check forensic guard output
grep -n "to_csv\|save\|write\|output" scripts/17_forensic_guard.py
# It might write to the enriched CSV, or have a separate cache
# If it's only in the enriched CSV, you'll need to either:
# a) Extract M-Score and Z-Score computation into a shared utility
# b) Run forensic guard first and read its output
# c) Recompute from raw data (the formulas are documented in CLAUDE.md)
```

If Beneish/Altman scores aren't easily accessible as a standalone CSV, compute them inline:

**Altman Z″ (Emerging Market):**
```python
Z'' = 3.25 + 6.56*(WC/TA) + 3.26*(RE/TA) + 6.72*(EBIT/TA) + 1.05*(BV_Equity/TL)
# WC = Working Capital = Current Assets - Current Liabilities
# TA = Total Assets
# RE = Retained Earnings
# EBIT = Earnings Before Interest and Tax
# BV_Equity = Book Value of Equity
# TL = Total Liabilities
```

**Beneish M-Score:** Complex 8-variable formula. Read `17_forensic_guard.py` for exact implementation. If it's too complex to extract, just use the existing output.

### Step 12: Full Pipeline Test

```bash
source ~/alpha-signal/venv/bin/activate
cd ~/alpha-signal

# Run quality gate
python scripts/33_quality_gate.py --smoke   # test first
python scripts/33_quality_gate.py           # full run

# Verify output
head -10 data/signals/quality_gate.csv
python -c "
import pandas as pd
df = pd.read_csv('data/signals/quality_gate.csv')
print(df['gate_status'].value_counts())
print(f'Quality composite mean: {df[\"quality_composite\"].mean():.3f}')
"

# Validate: check if known junk stocks are excluded
# and known quality small-caps pass
python -c "
import pandas as pd
df = pd.read_csv('data/signals/quality_gate.csv')
# Check some specific stocks you know about
for ticker in ['RELIANCE', 'TCS', 'INFY']:  # these are LARGE, won't be here
    match = df[df['ticker'] == ticker]
    if len(match): print(f'{ticker}: {match.iloc[0][\"gate_status\"]}')
    else: print(f'{ticker}: not in small-cap universe (correct)')
# Look for known penny stocks / shell companies in excluded list
excluded = df[df['gate_status'] == 'EXCLUDED']
print(f'\\nExcluded count: {len(excluded)}')
print('Sample excluded:', excluded['ticker'].head(20).tolist())
"
```

### Step 13: Git Commit

```bash
git add -A
git commit -m "D14: Small-cap quality gate — graduated 3-tier design

- NEW: 33_quality_gate.py — quality screening for small-cap universe
- Tier 1 HARD EXCLUSION: no price data, 3yr consecutive loss, negative equity,
  Piotroski F≤1, Altman Z<0.5
- Tier 2 HEAVY PENALTY: loss 2/3yr (-0.25), neg FCF (-0.20), pledge>50% (-0.25),
  F=2-3 (-0.15), Z=0.5-1.1 (-0.15), Beneish>-1.78 (-0.20). Capped at -0.60.
- Tier 3 QUALITY COMPOSITE: Piotroski 25%, CFO/EBITDA 20%, Beneish 20%,
  Z-Score 15%, Pledge 10%, FCF years 10%
- Soft design: only ~15% excluded (true junk), rest penalised not killed
- Empirically justified: Piotroski t=2.81 in small caps (C13b reconstruction)
- Output: data/signals/quality_gate.csv (gate_status, quality_penalty, quality_composite)
- Stats: [FILL IN — EXCLUDED/PENALISED/PASS counts]
"
```

---

## IMPORTANT NOTES

1. **Read existing scripts first.** The column names in piotroski.csv, the forensic guard output format, the annual cashflow column names — all must be discovered from the actual code, not assumed.

2. **The gate applies ONLY to SMALL cap tier.** Large and mid caps pass through ungated. If you want quality scoring for mid caps too (Piotroski was t=2.23 there), compute the quality_composite for MID too but don't apply hard exclusions.

3. **Altman Z″ uses the EMERGING MARKET formula** (with 3.25 constant), not the original US formula. Check what `17_forensic_guard.py` uses — if it uses the US formula, note the discrepancy but use whatever is already computed for consistency.

4. **The `no_price_data` exclusion is the biggest category.** ~500 stocks have no yfinance price data. These are almost certainly delisted, suspended, or non-trading. They can't be invested in anyway, so excluding them is non-controversial.

5. **Run the --stats flag after to verify sanity.** The gate should exclude ~13-18% (300-400 stocks), penalise another ~15-25% (350-550 stocks), and pass ~55-70% (1,250-1,600 stocks). If exclusion is above 25%, the criteria are too aggressive — loosen thresholds. If below 10%, too lenient.

6. **The quality_composite score feeds into D17's small-cap model** as one of the signal components (currently spec'd at 0.20 weight in score_S). Stocks with higher quality_composite get a boost in the final ranking.

7. **Gate validation (long-term):** Track 12-month performance of EXCLUDED stocks. If >50% decline >30% or face adverse corporate action, the gate is working. Add this as a monitoring metric in the weekly dashboard.

8. **Don't worry about the LARGE-cap model being thin** (only consensus validated). That's okay — large caps are efficient, most retail alpha comes from mid and small caps. A thin large-cap model with one strong signal is better than a bloated one with noise signals.