# Session C13b — Full Historical Signal Reconstruction (36 Monthly Periods)
# Claude Code Implementation Instructions — DEFINITIVE VERSION
# Date: 2026-04-03
# Prereq: C12 complete, C13 complete. universe.csv has cap_tier.

## OBJECTIVE

Build a comprehensive historical signal reconstructor that computes per-tier IC with **36 monthly evaluation dates** (April 2023 – March 2026) for every signal where data permits. This is not a toy — 36 periods gives publishable-quality t-statistics that definitively answer which signals work in which cap tier.

Also: set up daily PIT signal accumulation going forward so we never need to reconstruct again.

## WHAT DATA EXISTS ON THE VM

| File | Location | Depth | Rows |
|------|----------|-------|------|
| universe.csv (with cap_tier) | data/harvester/ | current | 2,500 |
| annual_balancesheet.csv | data/harvester/ | 10 years | 19,196 |
| annual_cashflow.csv | data/harvester/ | 10 years | 19,155 |
| quarterly_income.csv | data/harvester/ | 10 quarters | 21,571 |
| shareholding.csv | data/harvester/ | 6 quarters | 14,135 |
| piotroski.csv | data/signals/ | current snapshot | 1,978 |
| accruals.csv | data/signals/ | current snapshot | 2,426 |
| promoter.csv | data/signals/ | current snapshot | 2,438 |
| smart_money_score.csv | data/smart_money/ | current snapshot | 2,464 |
| consensus.csv | data/analyst/ | current snapshot | 2,439 |

## WHAT DATA IS MISSING (2 items only)

### Missing Item 1: 3-year daily OHLCV for all 2,500 stocks

**Why:** Forward returns + momentum computation at every eval date.
**How:** yfinance batch download. 2,500 tickers × 3yr daily OHLCV.
**Time:** 2-3 hours.
**Store at:** `data/backtest/prices/` — one CSV per stock or one big parquet.

```python
import yfinance as yf
import pandas as pd
import time
import os

def download_all_prices(universe_path='data/harvester/universe.csv',
                        output_dir='data/backtest/prices/',
                        period='3y', chunk_size=50, delay=2):
    """Download 3yr daily OHLCV for all stocks in universe."""
    os.makedirs(output_dir, exist_ok=True)
    universe = pd.read_csv(universe_path)
    tickers = [f"{t}.NS" for t in universe['ticker'].dropna()]
    
    # Checkpoint: skip already downloaded
    done_file = os.path.join(output_dir, '_downloaded.txt')
    done = set()
    if os.path.exists(done_file):
        done = set(open(done_file).read().splitlines())
    
    remaining = [t for t in tickers if t not in done]
    print(f"Downloading {len(remaining)} tickers ({len(done)} already cached)")
    
    for i in range(0, len(remaining), chunk_size):
        chunk = remaining[i:i+chunk_size]
        try:
            data = yf.download(chunk, period=period, group_by='ticker', threads=True)
            for ticker in chunk:
                try:
                    if len(chunk) == 1:
                        df = data
                    else:
                        df = data[ticker] if ticker in data.columns.get_level_values(0) else pd.DataFrame()
                    if df is not None and len(df) > 0:
                        safe_name = ticker.replace('.', '_')
                        df.to_csv(os.path.join(output_dir, f"{safe_name}.csv"))
                        done.add(ticker)
                except Exception:
                    pass
            # Checkpoint
            with open(done_file, 'w') as f:
                f.write('\n'.join(done))
            print(f"  Downloaded {len(done)}/{len(tickers)} ({i+chunk_size}/{len(remaining)} this run)")
        except Exception as e:
            print(f"  Chunk error at {i}: {e}")
        time.sleep(delay)
    
    print(f"Done. {len(done)}/{len(tickers)} stocks have price data.")
```

**Alternatively:** Check if the backtester's `--recon` mode already cached prices:
```bash
ls -la data/backtest/prices/ 2>/dev/null
ls data/backtest/*.csv data/backtest/*.parquet 2>/dev/null
grep -n "save\|cache\|price.*csv\|parquet" scripts/24_backtester.py | head -20
```
If cached, REUSE. Don't re-download.

### Missing Item 2: 6 months of bhavcopy files (on user's local machine)

**Why:** Delivery % history for smart money signal reconstruction.
**How:** User uploads from local Windows machine to VM.
**Format expected:** NSE bhavcopy files named like `sec_bhavdata_full_DDMMYYYY.csv` containing columns including `SYMBOL`, `SERIES`, `CLOSE_PRICE`, `TTL_TRD_QNTY`, `DELIV_QTY`, `DELIV_PER`, `TURNOVER_LACS`.

**Upload instructions (user runs on local Windows):**
```powershell
# From PowerShell on local machine:
scp -i <your-key> C:\path\to\bhavcopy\sec_bhavdata_full_*.csv ubuntu@<vm-ip>:~/alpha-signal/data/smart_money/raw/
```

**If scp has key issues (like before), alternative:**
```bash
# On VM, pull via wget if files are accessible anywhere
# OR: tar the bhavcopy files locally, upload to a temp location, download on VM
```

**After upload, verify on VM:**
```bash
ls data/smart_money/raw/sec_bhavdata_full_* | wc -l
# Should show ~130 files (6 months × ~22 trading days/month)
head -3 data/smart_money/raw/sec_bhavdata_full_*.csv | head -10
```

---

## THE 36 MONTHLY EVALUATION DATES

One eval date per month: 1st trading day of the month (or nearest).
Going back 36 months from March 2026.

```python
EVAL_DATES = [
    '2023-04-03', '2023-05-02', '2023-06-01', '2023-07-03',
    '2023-08-01', '2023-09-01', '2023-10-02', '2023-11-01',
    '2023-12-01', '2024-01-02', '2024-02-01', '2024-03-01',
    '2024-04-01', '2024-05-02', '2024-06-03', '2024-07-01',
    '2024-08-01', '2024-09-02', '2024-10-01', '2024-11-01',
    '2024-12-02', '2025-01-02', '2025-02-03', '2025-03-03',
    '2025-04-01', '2025-05-02', '2025-06-02', '2025-07-01',
    '2025-08-01', '2025-09-01', '2025-10-01', '2025-11-03',
    '2025-12-01', '2026-01-02', '2026-02-02', '2026-03-03',
]
```

**NOTE:** These are approximate. The script should find the nearest actual trading day from price data. If a date is a holiday, use the next available trading day.

---

## SIGNAL-BY-SIGNAL RECONSTRUCTION SPEC

### Signal 1: Piotroski F-Score (9 binary criteria, score 0-9)

**Data sources:** `annual_balancesheet.csv` + `annual_cashflow.csv` + `quarterly_income.csv`
**Reconstruction depth:** All 36 eval dates
**Piecewise constant:** F-Score changes only when new annual results are filed.

**Filing calendar for Piotroski:**

| Fiscal Year End | Results filed by (75-day lag) | F-Score valid from | F-Score valid until |
|----------------|------------------------------|-------------------|-------------------|
| Mar 2016 | Jun 15, 2016 | Jun 15, 2016 | Jun 14, 2017 |
| Mar 2017 | Jun 15, 2017 | Jun 15, 2017 | Jun 14, 2018 |
| ... | ... | ... | ... |
| Mar 2023 | Jun 15, 2023 | Jun 15, 2023 | Jun 14, 2024 |
| Mar 2024 | Jun 15, 2024 | Jun 15, 2024 | Jun 14, 2025 |
| Mar 2025 | Jun 15, 2025 | Jun 15, 2025 | present |

**Logic for each eval_date:**
```python
def get_available_piotroski_fy(eval_date):
    """Which fiscal year's annual data would be available on eval_date?"""
    year = eval_date.year
    month = eval_date.month
    
    if month >= 7:  # Jul onwards: current FY-1 annual data available
        return f"FY{year}"      # e.g., eval Jul 2024 → FY2024 (ending Mar 2024) available
    elif month >= 1:  # Jan-Jun: previous FY annual available, current FY not yet filed
        return f"FY{year-1}"    # e.g., eval Mar 2024 → FY2023 (ending Mar 2023) available
    
    # Piotroski needs 2 consecutive FYs:
    # latest FY and previous FY
```

**Computation:** EXACTLY replicate what `27_piotroski.py` does. Read that script first:
```bash
cat scripts/27_piotroski.py
```

The 9 criteria typically are:
1. ROA positive (NI > 0)
2. OCF positive
3. ΔROA positive (ROA increased YoY)
4. Accruals (OCF > NI)
5. ΔLeverage decreased (LT debt / avg assets)
6. ΔLiquidity increased (current ratio)
7. No equity issuance (shares didn't increase)
8. ΔMargin increased (gross margin)
9. ΔTurnover increased (asset turnover)

Each criterion uses annual balance sheet / cashflow / income data. The EXACT column names come from the existing script — read it.

**Output per stock per eval_date:** `piotroski_f_score` (integer 0-9)

---

### Signal 2: Accruals (CF + BS components)

**Data sources:** `annual_balancesheet.csv` + `annual_cashflow.csv` + `quarterly_income.csv`
**Reconstruction depth:**
- CF accruals + BS accruals: **36 eval dates** (uses annual data, same availability as Piotroski)
- EPS CV + earnings beat rate: **~8-10 eval dates only** (needs 8 quarterly EPS, only have 10 quarters)

**Filing calendar:** Same as Piotroski for annual components. For quarterly EPS components:

| Quarter End | Results filed by (60-day lag) | Available from |
|-------------|------------------------------|----------------|
| Q1 (Jun 30) | ~Sep 1 | Sep 1 |
| Q2 (Sep 30) | ~Dec 1 | Dec 1 |
| Q3 (Dec 31) | ~Mar 1 | Mar 1 |
| Q4 (Mar 31) | ~Jun 15 (annual, 75-day) | Jun 15 |

**Computation:** EXACTLY replicate what `28_accruals.py` does. Read it first:
```bash
cat scripts/28_accruals.py
```

Components:
- `cf_accruals_ratio` = (LTM NI − annual OCF) / avg_total_assets — **36 periods**
- `bs_accruals_ratio` = Sloan (ΔCA−ΔCash)−(ΔCL−ΔSTD)−Dep / avg_assets — **36 periods**, skip for Financials
- `eps_cv` = std(last 8Q EPS) / |mean(last 8Q EPS)| — **only eval dates where 8Q of quarterly income exist**
- `earnings_beat_rate` = fraction of last 4Q where NI > same Q prior year — **same constraint as eps_cv**

**Strategy:** Compute the full accruals signal (all 4 components) where possible. Where eps_cv/beat_rate aren't available (before ~late 2024), compute partial signal using CF+BS only (70% of weight). Track `signal_coverage` flag: 'full' vs 'partial_cf_bs_only'.

**Output per stock per eval_date:** `accruals_cf_ratio`, `accruals_bs_ratio`, `eps_cv`, `earnings_beat_rate`, `accruals_signal` (composite 0-1), `signal_coverage`

---

### Signal 3: Promoter (QoQ + trend + pledge)

**Data source:** `shareholding.csv` (6 quarters)
**Reconstruction depth:**
- `promoter_qoq`: **~12-15 eval dates** (needs 2 consecutive quarters of shareholding)
- `promoter_trend_4q`: **~3 eval dates** (needs 5 quarters — only 1 quarter of runway)
- `pledge_quality`: **~15 eval dates** (same as QoQ)

**First, determine shareholding data range:**
```bash
# Check what quarters exist in shareholding.csv
python -c "
import pandas as pd
df = pd.read_csv('data/harvester/shareholding.csv')
print('Columns:', df.columns.tolist())
# Find the date/quarter column and print unique values
for col in df.columns:
    if 'date' in col.lower() or 'quarter' in col.lower() or 'period' in col.lower():
        print(f'{col}: {sorted(df[col].unique())}')
"
```

**Filing lag:** Shareholding patterns must be disclosed within 21 days of quarter-end.

| Quarter End | Shareholding available from |
|-------------|---------------------------|
| Jun 30, 2024 | Jul 21, 2024 |
| Sep 30, 2024 | Oct 21, 2024 |
| Dec 31, 2024 | Jan 21, 2025 |
| Mar 31, 2025 | Apr 21, 2025 |
| Jun 30, 2025 | Jul 21, 2025 |
| Sep 30, 2025 | Oct 21, 2025 |

(Approximate — adjust based on actual quarters in the data.)

**For each eval_date:**
```python
def get_available_shareholding(eval_date, shareholding_df, filing_lag_days=21):
    """Return shareholding quarters filed before eval_date."""
    # shareholding has a quarter/period column — determine its format first
    # Filter to quarters where quarter_end + 21 days <= eval_date
    # Sort descending by quarter
    # Return: latest, previous, 4-quarters-ago (if available)
    pass
```

**Computation:** Replicate `30_promoter_signal.py`. Read it:
```bash
cat scripts/30_promoter_signal.py
```

**Strategy:** For eval_dates before shareholding data starts → signal is NaN for that date (skip in IC computation). For eval_dates with only 2 quarters → compute QoQ only, skip trend_4q. Track coverage.

**Output per stock per eval_date:** `promoter_qoq`, `promoter_trend_4q`, `pledge_quality`, `promoter_signal` (composite), `signal_coverage`

---

### Signal 4: Value (Earnings Yield + Book-to-Price)

**Data sources:** `quarterly_income.csv` + `annual_balancesheet.csv` + stock prices
**Reconstruction depth:**
- `book_to_price`: **36 eval dates** (book value from annual BS, updated annually)
- `earnings_yield` (TTM EPS / price): **~18 eval dates** (needs 4 quarters of income → 10Q - 4Q = 6Q runway ≈ 18 months back)

**Computation:**
```python
def reconstruct_value(sid, eval_date, quarterly_income, annual_bs, price):
    """
    earnings_yield = TTM_EPS / price_on_eval_date
    book_to_price = book_value_per_share / price_on_eval_date
    """
    # TTM EPS = sum of last 4 filed quarters' EPS
    # Book value = latest annual book value (with 75-day lag)
    # Price = actual closing price on eval_date from downloaded OHLCV
    pass
```

**Note:** The existing `--recon` mode in `24_backtester.py` already does value_recon. Check if we can reuse its output or logic:
```bash
grep -n "value_recon\|earnings_yield\|book_to_price" scripts/24_backtester.py | head -20
```

If the recon mode already produces per-stock value signals at historical dates, IMPORT those results rather than recomputing.

**Output per stock per eval_date:** `earnings_yield`, `book_to_price`, `value_signal` (composite)

---

### Signal 5: Momentum (Risk-Adjusted 6M + 12M)

**Data source:** Stock prices ONLY (no fundamentals)
**Reconstruction depth:** **~24 eval dates** (36 months minus 12 months lookback needed for 12M momentum)

**Computation:**
```python
def reconstruct_momentum(ticker, eval_date, prices_df):
    """
    For each eval_date, compute:
    - ret_6m = price[-22 trading days] / price[-132 trading days] - 1 (skip most recent month)
    - ret_12m = price[-22] / price[-264] - 1 (skip most recent month)
    - vol_6m = daily return std over 132 days
    - vol_12m = daily return std over 264 days
    - mom_6m_adj = ret_6m / vol_6m (Sharpe-like, per Fix 4)
    - mom_12m_adj = ret_12m / vol_12m
    """
    # Need 264 + 22 = 286 trading days of price BEFORE eval_date
    # With 3yr ≈ 750 trading days of data, first valid eval_date ≈ month 14 from start
    pass
```

**Jegadeesh-Titman skip-month** (Fix 4): return is computed ending 1 month (22 trading days) ago, not to current date.

**Output per stock per eval_date:** `ret_6m`, `ret_12m`, `vol_6m`, `vol_12m`, `mom_6m_adj`, `mom_12m_adj`

---

### Signal 6: Smart Money (Delivery %)

**Data source:** Bhavcopy files in `data/smart_money/raw/`
**Reconstruction depth:** **~5-6 eval dates** (limited to months where 30 days of bhavcopy exist before eval_date)
**Requires:** User uploads 6 months of bhavcopy from local machine (see Missing Item 2 above)

**Computation:**
```python
def reconstruct_delivery_score(ticker, eval_date, bhavcopy_dir='data/smart_money/raw/'):
    """
    For each eval_date:
    - Load all bhavcopy files from (eval_date - 30 calendar days) to eval_date
    - Filter for this ticker, SERIES == 'EQ' (strip whitespace!)
    - Compute: avg_delivery_pct = mean(DELIV_PER) over 30-day window
    - This is the raw delivery % signal
    """
    # Find bhav files in date range
    # Parse filename: sec_bhavdata_full_DDMMYYYY.csv
    # Filter, compute mean delivery %
    pass
```

**IMPORTANT:** SERIES column has leading whitespace in raw bhavcopy — always `str.strip()` before filtering.

**Output per stock per eval_date:** `avg_delivery_pct_30d`

---

### Signal 7: Consensus — CANNOT RECONSTRUCT

No historical analyst estimates data exists. Skip entirely.
Will be PIT-tested via daily accumulation only (Build 2).

---

## SIGNAL RECONSTRUCTION COVERAGE MATRIX

| Signal | Eval dates possible (out of 36) | Stocks per date | t-stat quality |
|--------|--------------------------------|-----------------|----------------|
| Piotroski F-Score | **36** | ~1,500-2,000 | **Excellent** |
| Accruals CF+BS | **36** | ~1,500-2,000 | **Excellent** |
| Accruals full (incl EPS) | **~8-10** | ~1,500-2,000 | Marginal |
| Value book-to-price | **36** | ~1,500-2,000 | **Excellent** |
| Value earnings yield | **~18** | ~1,500-2,000 | **Good** |
| Momentum risk-adj | **~24** | ~1,500-2,000 | **Excellent** |
| Promoter QoQ | **~12-15** | ~2,000 | **Borderline-Good** |
| Promoter trend_4q | **~3** | ~2,000 | Skip (too few) |
| Smart Money delivery% | **~5-6** | ~2,000 | Directional only |
| Consensus | **0** | — | Cannot reconstruct |

---

## SCRIPT ARCHITECTURE: `38_signal_reconstructor.py`

### Main flow

```python
def main():
    args = parse_args()  # --smoke, --signal, --no-download, --eval-dates
    
    # 1. Load all raw data
    universe = pd.read_csv('data/harvester/universe.csv')
    annual_bs = pd.read_csv('data/harvester/annual_balancesheet.csv')
    annual_cf = pd.read_csv('data/harvester/annual_cashflow.csv')
    quarterly_income = pd.read_csv('data/harvester/quarterly_income.csv')
    shareholding = pd.read_csv('data/harvester/shareholding.csv')
    
    # 2. Load or download prices
    prices = load_all_prices('data/backtest/prices/')  # dict: ticker → DataFrame
    if not prices and not args.no_download:
        download_all_prices()
        prices = load_all_prices('data/backtest/prices/')
    
    # 3. Define eval dates
    eval_dates = EVAL_DATES  # 36 monthly dates
    if args.smoke:
        eval_dates = eval_dates[-3:]  # last 3 months only
    
    # 4. For each eval_date: reconstruct all signals for all stocks
    all_results = []
    for eval_date in eval_dates:
        eval_dt = pd.Timestamp(eval_date)
        print(f"\nReconstructing signals for {eval_date}...")
        
        # Determine which financial data is available at this date
        available_fy = get_latest_available_fy(eval_dt)  # e.g., 'FY2024'
        prev_fy = get_previous_fy(available_fy)
        available_quarters = get_available_quarters(eval_dt, quarterly_income)
        available_shareholding = get_available_shareholding_quarters(eval_dt, shareholding)
        
        stock_count = 0
        for _, stock in universe.iterrows():
            sid = stock['sid']
            ticker = stock['ticker']
            cap_tier = stock['cap_tier']
            sector = stock['sector']
            
            # Get forward 20-day return
            fwd_ret = compute_fwd_return(prices, ticker, eval_dt, days=20)
            if fwd_ret is None:
                continue  # no price data for this stock
            
            # Get price on eval_date (for value signals)
            price = get_price_on_date(prices, ticker, eval_dt)
            if price is None or price <= 0:
                continue
            
            row = {
                'eval_date': eval_date,
                'sid': sid,
                'ticker': ticker,
                'cap_tier': cap_tier,
                'sector': sector,
                'fwd_return_20d': fwd_ret,
                'price': price,
            }
            
            # Piotroski (36 dates)
            row['piotroski_f_score'] = compute_piotroski_at_date(
                sid, available_fy, prev_fy, annual_bs, annual_cf, quarterly_income, sector)
            
            # Accruals (36 dates for CF/BS, fewer for EPS components)
            accruals = compute_accruals_at_date(
                sid, available_fy, prev_fy, available_quarters,
                annual_bs, annual_cf, quarterly_income, sector)
            row.update(accruals)  # cf_accruals_ratio, bs_accruals_ratio, eps_cv, beat_rate
            
            # Value (36 dates for B/P, ~18 for E/Y)
            value = compute_value_at_date(
                sid, available_fy, available_quarters, annual_bs, quarterly_income, price)
            row.update(value)  # earnings_yield, book_to_price
            
            # Momentum (24 dates)
            momentum = compute_momentum_at_date(ticker, eval_dt, prices)
            row.update(momentum)  # mom_6m_adj, mom_12m_adj
            
            # Promoter (12-15 dates)
            promoter = compute_promoter_at_date(sid, available_shareholding, shareholding)
            row.update(promoter)  # promoter_qoq, pledge_quality
            
            # Smart money delivery% (5-6 dates, only if bhavcopy files exist)
            delivery = compute_delivery_at_date(ticker, eval_dt, 'data/smart_money/raw/')
            row.update(delivery)  # avg_delivery_pct_30d
            
            all_results.append(row)
            stock_count += 1
        
        print(f"  {eval_date}: {stock_count} stocks reconstructed")
    
    # 5. Save full results
    results_df = pd.DataFrame(all_results)
    results_df.to_csv('data/backtest/reconstructed_signals.csv', index=False)
    print(f"\nSaved {len(results_df)} rows to data/backtest/reconstructed_signals.csv")
    
    # 6. Compute IC per signal per tier
    compute_and_print_stratified_ic(results_df)
    
    # 7. Save IC report
    # data/backtest/reconstructed_ic_by_tier.csv
```

### IC computation function

```python
def compute_and_print_stratified_ic(results_df):
    """Compute Spearman IC per signal per cap_tier across eval dates."""
    
    signal_columns = [
        'piotroski_f_score',
        'cf_accruals_ratio',     # NOTE: lower = better quality, so IC should be NEGATIVE
        'bs_accruals_ratio',     # Same — lower = better
        'accruals_composite',    # Higher = better (already inverted in computation)
        'earnings_yield',        # Higher = cheaper = better
        'book_to_price',         # Higher = cheaper = better
        'mom_6m_adj',            # Higher = stronger momentum = better
        'mom_12m_adj',           # Same
        'promoter_qoq',         # Higher = more buying = better
        'pledge_quality',        # Higher = less pledging = better
        'avg_delivery_pct_30d',  # Higher = more conviction = better?
    ]
    
    ic_results = []
    
    for signal_col in signal_columns:
        for tier in ['LARGE', 'MID', 'SMALL']:
            tier_data = results_df[results_df['cap_tier'] == tier]
            
            ics = []
            for eval_date in tier_data['eval_date'].unique():
                period_data = tier_data[tier_data['eval_date'] == eval_date]
                clean = period_data[[signal_col, 'fwd_return_20d']].dropna()
                
                if len(clean) < 20:  # minimum stocks per period
                    continue
                
                ic = clean[signal_col].corr(clean['fwd_return_20d'], method='spearman')
                if not pd.isna(ic):
                    ics.append(ic)
            
            if len(ics) < 4:  # minimum periods
                continue
            
            mean_ic = np.mean(ics)
            std_ic = np.std(ics, ddof=1)
            icir = mean_ic / std_ic if std_ic > 0 else 0
            t_stat = mean_ic / (std_ic / np.sqrt(len(ics))) if std_ic > 0 else 0
            
            # L/S spread: quintile 1 vs quintile 5
            ls_spreads = []
            for eval_date in tier_data['eval_date'].unique():
                period_data = tier_data[tier_data['eval_date'] == eval_date]
                clean = period_data[[signal_col, 'fwd_return_20d']].dropna()
                if len(clean) < 25:  # need at least 5 per quintile
                    continue
                clean['quintile'] = pd.qcut(clean[signal_col], 5, labels=False, duplicates='drop')
                q1_ret = clean[clean['quintile'] == 4]['fwd_return_20d'].mean()  # top quintile
                q5_ret = clean[clean['quintile'] == 0]['fwd_return_20d'].mean()  # bottom quintile
                ls_spreads.append(q1_ret - q5_ret)
            
            avg_ls = np.mean(ls_spreads) * 100 if ls_spreads else 0  # as percentage
            
            ic_results.append({
                'signal': signal_col,
                'cap_tier': tier,
                'n_periods': len(ics),
                'n_stocks_avg': int(tier_data.groupby('eval_date')[signal_col].count().mean()),
                'mean_ic': round(mean_ic, 4),
                'std_ic': round(std_ic, 4),
                'icir': round(icir, 3),
                't_stat': round(t_stat, 2),
                'avg_ls_pct': round(avg_ls, 2),
                'verdict': 'KEEP' if abs(t_stat) >= 2.5 else ('WEAK' if abs(t_stat) >= 1.5 else 'DROP'),
            })
    
    ic_df = pd.DataFrame(ic_results)
    ic_df.to_csv('data/backtest/reconstructed_ic_by_tier.csv', index=False)
    
    # Pretty print
    print("\n" + "=" * 100)
    print("HISTORICAL SIGNAL RECONSTRUCTION — IC BY TIER")
    print(f"{'Signal':30s} {'Tier':6s} {'IC':>8s} {'ICIR':>8s} {'t-stat':>8s} {'L/S%':>8s} {'N':>4s} {'Verdict'}")
    print("=" * 100)
    
    for tier in ['LARGE', 'MID', 'SMALL']:
        print(f"\n--- {tier} ---")
        sub = ic_df[ic_df['cap_tier'] == tier].sort_values('t_stat', ascending=False)
        for _, row in sub.iterrows():
            inv = " INVERTED" if row['t_stat'] < -2.0 else ""
            print(f"  {row['signal']:30s} {row['cap_tier']:6s} {row['mean_ic']:+8.4f} "
                  f"{row['icir']:+8.3f} {row['t_stat']:+8.2f} {row['avg_ls_pct']:+8.2f} "
                  f"{row['n_periods']:4d}   {row['verdict']}{inv}")
```

### CLI

```bash
python scripts/38_signal_reconstructor.py                        # full: 36 dates × all signals × all stocks
python scripts/38_signal_reconstructor.py --smoke                # 3 dates × 100 stocks
python scripts/38_signal_reconstructor.py --no-download          # skip price download, use cache
python scripts/38_signal_reconstructor.py --signal piotroski     # single signal only
python scripts/38_signal_reconstructor.py --eval-dates 2025-01-02,2025-06-02,2026-01-02  # custom dates
```

---

## BUILD 2: DAILY PIT SIGNAL ACCUMULATOR

### Enhance `26_snapshot_archiver.py`

Read existing script first:
```bash
cat scripts/26_snapshot_archiver.py
```

Add a NEW function `archive_signal_snapshot()` called after the existing archiving logic.

### Exact schema: `data/snapshots/signal_snapshots.csv`

```
snapshot_date          - YYYY-MM-DD
sid                    - Tickertape SID
ticker                 - NSE symbol
cap_tier               - LARGE/MID/SMALL
cmp                    - Closing price on snapshot_date
market_cap             - In Rs (from universe.csv)
adtv_6m_cr             - In crores (from universe.csv)
piotroski_f_score      - 0-9 from data/signals/piotroski.csv
accruals_signal        - 0-1 from data/signals/accruals.csv
consensus_signal       - 0-1 from data/signals/consensus.csv
promoter_signal        - 0-1 from data/signals/promoter.csv
promoter_qoq           - Raw QoQ from data/signals/promoter.csv
smart_money_score      - 0-100 from data/smart_money/smart_money_score.csv
earnings_yield         - From enriched output (if available)
final_score            - From enriched output (if available)
```

### Implementation

```python
import os
import pandas as pd
from datetime import date

def archive_signal_snapshot():
    """Archive today's signal values for all stocks. Called daily after pipeline."""
    today = date.today().isoformat()
    
    # Load universe with tier info
    universe = pd.read_csv('data/harvester/universe.csv',
                           usecols=['sid', 'ticker', 'cap_tier', 'market_cap', 'adtv_6m_cr'])
    
    # Load each signal file — use safe loading (file may not exist)
    def safe_load(path, key_col='sid', value_cols=None):
        if not os.path.exists(path):
            return pd.DataFrame(columns=[key_col] + (value_cols or []))
        df = pd.read_csv(path)
        cols = [key_col] + [c for c in (value_cols or []) if c in df.columns]
        return df[[c for c in cols if c in df.columns]]
    
    piotroski = safe_load('data/signals/piotroski.csv', 'sid', ['f_score'])
    accruals = safe_load('data/signals/accruals.csv', 'sid', ['accruals_signal'])
    consensus = safe_load('data/signals/consensus.csv', 'sid', ['consensus_signal'])
    promoter = safe_load('data/signals/promoter.csv', 'sid', ['promoter_signal', 'promoter_qoq'])
    
    # Smart money uses symbol/ticker, not sid
    smart = safe_load('data/smart_money/smart_money_score.csv', 'symbol', ['smart_money_score'])
    
    # Merge all onto universe
    snapshot = universe.copy()
    snapshot = snapshot.merge(piotroski.rename(columns={'f_score': 'piotroski_f_score'}), on='sid', how='left')
    snapshot = snapshot.merge(accruals, on='sid', how='left')
    snapshot = snapshot.merge(consensus, on='sid', how='left')
    snapshot = snapshot.merge(promoter, on='sid', how='left')
    snapshot = snapshot.merge(smart, left_on='ticker', right_on='symbol', how='left')
    
    # Try to get CMP + earnings_yield + final_score from latest enriched file
    enriched_dir = 'screener_output'  # CHECK actual directory name
    if os.path.isdir(enriched_dir):
        files = sorted([f for f in os.listdir(enriched_dir) if f.startswith('enriched_')])
        if files:
            latest = pd.read_csv(os.path.join(enriched_dir, files[-1]))
            # Adjust column names based on actual enriched file structure
            ecols = {'symbol': 'ticker'}  # rename to match
            for col in ['cmp', 'earnings_yield', 'final_score']:
                if col in latest.columns:
                    ecols[col] = col
            latest = latest.rename(columns={'symbol': 'e_ticker'})
            # Merge on ticker
            if 'cmp' in latest.columns:
                snapshot = snapshot.merge(
                    latest[['e_ticker', 'cmp', 'earnings_yield', 'final_score']].rename(
                        columns={'e_ticker': 'ticker'}),
                    on='ticker', how='left'
                )
    
    snapshot['snapshot_date'] = today
    
    # Drop duplicates if any from merges
    snapshot = snapshot.drop_duplicates(subset=['sid', 'snapshot_date'])
    
    # Append to cumulative file
    archive_path = 'data/snapshots/signal_snapshots.csv'
    if os.path.exists(archive_path):
        snapshot.to_csv(archive_path, mode='a', header=False, index=False)
    else:
        snapshot.to_csv(archive_path, index=False)
    
    # Report
    total_rows = sum(1 for _ in open(archive_path)) - 1
    days = total_rows // len(snapshot)
    print(f"Signal snapshot: {len(snapshot)} stocks archived for {today}")
    print(f"Cumulative: {total_rows} rows ({days} trading days)")
    print(f"PIT IC viable in: ~{max(0, 130 - total_rows // len(snapshot))} more trading days")
```

### Add call to existing 26_snapshot_archiver.py

At the END of the existing `main()` or whatever the entry point is:
```python
# After existing enriched snapshot logic:
archive_signal_snapshot()
```

### Verify cron integration

```bash
grep "26_snapshot\|snapshot_archiver" run_pipeline.sh
```
No new cron entry needed — the enhancement is inside the existing script.

---

## EXECUTION ORDER

```bash
source ~/alpha-signal/venv/bin/activate
cd ~/alpha-signal

# 0. Upload bhavcopy files from local machine (user does this separately via scp)
#    Verify:
ls data/smart_money/raw/sec_bhavdata_full_* 2>/dev/null | wc -l

# 1. Kick off recon-by-tier in background
nohup python scripts/24_backtester.py --recon --by-tier > data/backtest/recon_by_tier.log 2>&1 &
echo "Recon PID: $!"

# 2. Build 38_signal_reconstructor.py (main work)
#    Read existing scripts FIRST:
cat scripts/27_piotroski.py    # understand Piotroski computation
cat scripts/28_accruals.py     # understand Accruals computation
cat scripts/30_promoter_signal.py  # understand Promoter computation
head -5 data/harvester/annual_balancesheet.csv  # column names
head -5 data/harvester/annual_cashflow.csv
head -5 data/harvester/quarterly_income.csv
head -5 data/harvester/shareholding.csv

# 3. Smoke test reconstructor
python scripts/38_signal_reconstructor.py --smoke

# 4. Full reconstruction run (may take 1-2 hours — lots of computation)
python scripts/38_signal_reconstructor.py --no-download  # if prices already cached from recon
# OR:
python scripts/38_signal_reconstructor.py  # downloads prices if needed

# 5. Enhance 26_snapshot_archiver.py with signal accumulator
# Then test:
python scripts/26_snapshot_archiver.py
head -5 data/snapshots/signal_snapshots.csv
wc -l data/snapshots/signal_snapshots.csv

# 6. Check recon-by-tier results
tail -50 data/backtest/recon_by_tier.log
python -c "
import pandas as pd
df = pd.read_csv('data/backtest/signal_validation_by_tier.csv')
recon = df[df['signal'].str.contains('recon', na=False)]
print(recon.sort_values(['signal','cap_tier']).to_string(index=False))
"

# 7. Check reconstruction results — THE KEY OUTPUT
python -c "
import pandas as pd
df = pd.read_csv('data/backtest/reconstructed_ic_by_tier.csv')
print(df.sort_values(['signal','cap_tier']).to_string(index=False))
print()
print('=== SIGNALS WITH |t| >= 2.0 ===')
strong = df[df['t_stat'].abs() >= 2.0].sort_values(['cap_tier','t_stat'], ascending=[True,False])
for _, r in strong.iterrows():
    print(f\"  {r['signal']:30s} {r['cap_tier']:6s} t={r['t_stat']:+.2f} IC={r['mean_ic']:+.4f} L/S={r['avg_ls_pct']:+.1f}% {r['verdict']}\")
"

# 8. Git commit
git add -A
git commit -m "C13b: Full historical signal reconstruction (36 monthly periods) + PIT accumulation

- NEW: 38_signal_reconstructor.py — reconstructs 6 signals at 36 monthly eval dates
  (Apr 2023 – Mar 2026) with 60/75/21-day filing lags per SEBI requirements
- ENHANCED: 26_snapshot_archiver.py — daily signal value accumulation for PIT testing
- Signals reconstructed: Piotroski (36 periods), Accruals CF/BS (36), Value (36/18),
  Momentum (24), Promoter QoQ (12-15), Smart Money delivery% (5-6)
- Per-tier IC with t-stats for all signals — definitive segment validation
- Output: reconstructed_signals.csv, reconstructed_ic_by_tier.csv
- PIT accumulation started: signal_snapshots.csv grows ~2,500 rows/trading day
- Key findings: [FILL IN]
"
```

---

## EXPECTED RUN TIME

| Step | Time | Can parallelize? |
|------|------|-----------------|
| Price download (if needed) | 2-3 hours | Run in background |
| Signal reconstruction (36 dates × 2,500 stocks × 6 signals) | 1-2 hours | After prices ready |
| Snapshot archiver enhancement | 15 minutes | Anytime |
| Recon-by-tier background job | 2-3 hours | Background from start |
| **Total wall clock** | **3-4 hours** | (price download + reconstruction overlap with recon-by-tier) |

---

## CRITICAL NOTES

1. **READ THE EXISTING SIGNAL SCRIPTS FIRST.** The reconstruction must replicate their EXACT logic with date-filtered inputs. If 27_piotroski.py uses column name `Total Assets`, the reconstructor must use `Total Assets`, not `total_assets`.

2. **Filing lag is sacred.** Triple-check that no financial data is used before its filing date. If in doubt, add MORE lag, not less. Look-ahead bias makes all results worthless.

3. **Piotroski is piecewise constant.** The F-Score computed from FY2024 annual data (available ~Jun 15, 2024) is the SAME for eval dates Jul 2024, Aug 2024, Sep 2024... until Jun 2025 when FY2025 data arrives. Don't recompute it at every monthly date — compute once per FY transition and reuse.

4. **The `--recon --by-tier` run and the reconstructor are complementary.** Recon covers value/quality/momentum/growth (the signals it was originally built for). The reconstructor adds Piotroski/Promoter/Accruals/SmartMoney. Together they cover everything.

5. **NaN handling:** Many stocks will have NaN for some signals at some dates (insufficient data). This is CORRECT behavior. The IC computation should dropna() per signal per period. Track and report coverage (% non-NaN) per signal per tier.

6. **This is the definitive validation.** With 36 monthly periods and 1,500+ stocks per period, these are publication-grade IC statistics. If Piotroski shows t>2.5 in SMALL tier here, it's validated beyond reasonable doubt. If it shows t<1.0, it genuinely doesn't work in India regardless of what international papers say.