# Alpha Signal — System Hardening Plan

> From prototype to production-grade. Every practice here is borrowed from
> real quantitative trading pipelines and battle-tested data platforms.
>
> Created: 2026-04-09 | Owner: Amit Bhagat

---

## The Core Problem

Alpha Signal grew organically: 500 stocks → 2,500 stocks, scripts added one at a time,
each conversation with Claude Code building on assumptions from the last. The result:

- **Two parallel universes** running inside the same system (501 vs 2,500 stocks)
- **No contracts** between pipeline stages — any script can write anything
- **No tests** — zero. Not a single unit test, integration test, or smoke test
- **No alerting** — if a script fails at 3:30 AM, nobody knows until the email looks wrong
- **Silent failures** — pipeline continues even when a script crashes
- **Scattered configuration** — thresholds hardcoded in 20+ files
- **No schema enforcement** — CSVs drift silently between versions
- **Growing data without cleanup** — insider_archive.csv is 11MB with duplicate rows
- **Manual-only health checks** — dashboard shows file age but doesn't alert anyone

This is normal for a prototype. But the system is now complex enough that **the next bug
won't be in a script — it will be in the assumptions between scripts.** That's the class
of bug you can't find by reading code. You find it by enforcing contracts.

---

## What Real Systems Do (and why)

These practices come from production data pipelines at quant firms, fintech platforms,
and data engineering teams. They're not aspirational — they're the minimum for a system
that runs unattended and makes financial decisions.

### 1. Single Source of Truth for Configuration

**The problem:** Universe defined in 3 places (`nifty500_list.csv`, `universe.csv`,
`stock_metadata.csv`). Thresholds scattered across scripts. Credential exports in
shell scripts.

**What real systems do:**
- One config file (YAML or Python) that ALL scripts import
- Universe definition is ONE file, ONE path, ONE schema
- Every threshold has a name, a value, and a comment explaining why that number
- Credentials in environment variables or a secrets manager, never in code

**Proposed structure:**
```python
# config/pipeline_config.py — THE source of truth

# ── Universe ──
UNIVERSE_FILE = DATA_DIR / "harvester" / "universe.csv"   # 2,500 stocks, canonical
UNIVERSE_REQUIRED_COLUMNS = ["sid", "ticker", "name", "sector", "cap_tier", "adtv_6m_cr"]

# ── Pipeline Behavior ──
API_DELAY_SECONDS = 2.0
CHECKPOINT_INTERVAL = 200
MAX_RETRY_ATTEMPTS = 3

# ── Signal Thresholds ──
SIGNAL_THRESHOLDS = {
    "piotroski_quality_min": 7,       # F-Score ≥ 7 for quality boost
    "accruals_penalty_max": -0.03,    # Below this → penalty
    "consensus_upside_min": 0.10,     # 10% price target upside
    "insider_min_value_lakhs": 10,    # Ignore trades below ₹10L
    "sentiment_surge_momentum": 0.15, # Momentum threshold for surge signal
    "sentiment_min_articles": 2,      # Min articles for any signal
}

# ── Screener Filters ──
SCREENER_FILTERS = {
    "min_avg_volume": 100_000,
    "min_market_cap_cr": 500,
    # ... all from current settings.py
}

# ── Quality Gate (D14) ──
QUALITY_GATE = {
    "hard_exclude_piotroski_max": 1,
    "hard_exclude_altman_z_max": 0.5,
    "penalty_pledge_pct_max": 50,
    # ... all from 33_quality_gate.py
}
```

**Migration path:**
1. Create `config/pipeline_config.py` with ALL constants from ALL scripts
2. One script at a time, replace hardcoded values with imports
3. Add a validation function that checks all values are sane at pipeline start
4. Delete the old scattered constants only after the import works

---

### 2. Data Contracts (Schema Registry)

**The problem:** `06_fetch_news.py` writes `symbols_str` as a comma-separated string.
`07_sentiment_scorer.py` splits on commas. If the format changes, nothing breaks
immediately — it just produces wrong sentiment scores silently.

**What real systems do:**
- Every CSV has a **declared schema**: column names, types, nullable or not
- Every script **validates its inputs** before processing and **validates its outputs** before writing
- Schema violations cause **loud failures**, not silent corruption

**Proposed implementation:**
```python
# config/schemas.py — data contracts for every pipeline artifact

from dataclasses import dataclass, field
from typing import List, Optional

SCHEMAS = {
    "universe": {
        "path": "data/harvester/universe.csv",
        "columns": {
            "sid":          {"type": "str",   "nullable": False, "unique": True},
            "ticker":       {"type": "str",   "nullable": False},
            "name":         {"type": "str",   "nullable": False},
            "sector":       {"type": "str",   "nullable": False},
            "cap_tier":     {"type": "str",   "nullable": False, "values": ["LARGE", "MID", "SMALL"]},
            "adtv_6m_cr":   {"type": "float", "nullable": True,  "min": 0},
            "market_cap_cr":{"type": "float", "nullable": True,  "min": 0},
        },
        "min_rows": 2000,
        "max_rows": 3000,
    },

    "news_archive": {
        "path": "data/news/news_archive.csv",
        "columns": {
            "article_id":   {"type": "str",   "nullable": False, "unique": True},
            "title":        {"type": "str",   "nullable": False},
            "symbols_str":  {"type": "str",   "nullable": True},
            "source":       {"type": "str",   "nullable": False},
            "published_at": {"type": "str",   "nullable": False},
        },
        "min_rows": 100,
    },

    "insider_signals": {
        "path": "data/insider/latest_insider_signals.csv",
        "columns": {
            "symbol":       {"type": "str",   "nullable": False},
            "signal_type":  {"type": "str",   "nullable": False},
            "score_impact":  {"type": "float", "nullable": False},
        },
    },

    # ... one entry for every CSV the pipeline produces
}


def validate_dataframe(df, schema_name):
    """Validate a DataFrame against its declared schema. Raises on violation."""
    schema = SCHEMAS[schema_name]
    errors = []

    for col, rules in schema["columns"].items():
        if col not in df.columns:
            errors.append(f"Missing column: {col}")
            continue
        if not rules["nullable"] and df[col].isna().any():
            n_null = df[col].isna().sum()
            errors.append(f"{col}: {n_null} unexpected nulls")
        if "unique" in rules and rules["unique"] and df[col].duplicated().any():
            n_dup = df[col].duplicated().sum()
            errors.append(f"{col}: {n_dup} duplicate values")
        if "values" in rules:
            bad = set(df[col].dropna().unique()) - set(rules["values"])
            if bad:
                errors.append(f"{col}: unexpected values {bad}")
        if "min" in rules:
            violations = (df[col].dropna() < rules["min"]).sum()
            if violations:
                errors.append(f"{col}: {violations} values below min={rules['min']}")

    if "min_rows" in schema and len(df) < schema["min_rows"]:
        errors.append(f"Too few rows: {len(df)} < {schema['min_rows']}")
    if "max_rows" in schema and len(df) > schema["max_rows"]:
        errors.append(f"Too many rows: {len(df)} > {schema['max_rows']}")

    if errors:
        raise SchemaViolation(schema_name, errors)

    return True
```

**Usage in every script:**
```python
# At the START of any script that reads data:
df = pd.read_csv(UNIVERSE_FILE)
validate_dataframe(df, "universe")  # fails loud if schema changed

# At the END of any script that writes data:
validate_dataframe(output_df, "insider_signals")
output_df.to_csv(OUTPUT_PATH, index=False)
```

---

### 3. Pipeline Orchestrator with Error Handling

**The problem:** `run_pipeline.sh` runs 20 scripts sequentially with no error checking.
If script 6 crashes, scripts 7-20 still run on stale/missing data. Nobody knows until
they check the dashboard.

**What real systems do:**
- Each step checks the exit code of the previous step
- Critical failures stop the pipeline and alert the owner
- Non-critical failures are logged but pipeline continues with a warning
- Every run produces a structured log (JSON) with status per step

**Proposed replacement:**
```python
#!/usr/bin/env python3
"""
run_pipeline.py — Orchestrator with error handling, validation, and alerting.
Replaces run_pipeline.sh.
"""
import subprocess, sys, json, time
from datetime import datetime
from pathlib import Path
from config.pipeline_config import *
from config.schemas import validate_dataframe

PIPELINE = [
    # (script, critical?, description, expected_outputs)
    ("06_fetch_news.py",               True,  "Fetch news",          ["data/news/news_archive.csv"]),
    ("07_sentiment_scorer.py",         True,  "Score sentiment",     ["data/sentiment/latest_stock_sentiment.csv"]),
    ("09_insider_tracker.py",          False, "Track insiders",      ["data/insider/latest_insider_signals.csv"]),
    ("18_earnings_calendar.py",        False, "Earnings calendar",   ["data/events/earnings_calendar.csv"]),
    ("10_ai_news_classifier.py",       False, "AI classify news",    ["data/ai/latest_event_signals.csv"]),
    ("17_forensic_guard.py",           False, "Forensic scores",     ["data/forensic/forensic_scores.csv"]),
    ("14_macro_pulse.py",              False, "Macro pulse",         ["data/macro/macro_pulse.csv"]),
    ("16_smart_money.py",              True,  "Smart money",         ["data/smart_money/smart_money_score.csv"]),
    ("33_regime_module.py --refresh",  False, "VIX regime",          ["data/reference/regime_state.json"]),
    ("03_screener.py",                 True,  "Base screener",       []),  # writes dated file
    ("27_piotroski.py",                True,  "Piotroski F-Score",   ["data/signals/piotroski.csv"]),
    ("28_accruals.py",                 True,  "Accruals quality",    ["data/signals/accruals.csv"]),
    ("31_forecast_history_harvester.py --resume", False, "Forecast history", []),
    ("29_consensus_signal.py",         True,  "Consensus signal",    ["data/signals/consensus.csv"]),
    ("30_promoter_signal.py",          True,  "Promoter signal",     ["data/signals/promoter.csv"]),
    ("08_integrate_sentiment.py",      True,  "Integrate all",       ["data/latest_picks.csv"]),
    ("13_sector_analysis.py",          False, "Sector analysis",     []),
    ("26_snapshot_archiver.py",        True,  "Archive snapshot",    []),
    ("11_ai_dossier.py",               False, "AI dossier",          []),
    ("04_send_email.py",               False, "Send email",          []),
]

def run_step(script, critical, description, expected_outputs, log):
    """Run one pipeline step. Returns (success, duration, error_msg)."""
    start = time.time()
    cmd = f"python3 scripts/{script}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
    duration = time.time() - start

    step_log = {
        "script": script,
        "description": description,
        "critical": critical,
        "exit_code": result.returncode,
        "duration_sec": round(duration, 1),
        "stdout_tail": result.stdout[-500:] if result.stdout else "",
        "stderr_tail": result.stderr[-500:] if result.stderr else "",
    }

    # Check outputs exist and are fresh
    for path in expected_outputs:
        p = Path(path)
        if not p.exists():
            step_log["output_missing"] = str(p)
        elif (datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)).seconds > 3600:
            step_log["output_stale"] = str(p)

    log["steps"].append(step_log)

    if result.returncode != 0:
        msg = f"FAILED: {description} (exit {result.returncode})"
        if critical:
            log["status"] = "FAILED"
            log["failure_reason"] = msg
            send_alert(f"🔴 Pipeline FAILED at {description}\n{result.stderr[-200:]}")
            return False
        else:
            log["warnings"].append(msg)
    return True

def send_alert(message):
    """Send alert — start with email, add Slack/Telegram later."""
    print(f"ALERT: {message}")
    # TODO: integrate with 04_send_email or a lightweight notifier

def run_pipeline():
    log = {
        "date": datetime.now().isoformat(),
        "status": "SUCCESS",
        "warnings": [],
        "steps": [],
    }

    for script, critical, desc, outputs in PIPELINE:
        ok = run_step(script, critical, desc, outputs, log)
        if not ok and critical:
            break

    # Write structured log
    log_path = Path("output/pipeline_runs") / f"{datetime.now():%Y-%m-%d}.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(log, indent=2))

    print(f"\nPipeline {log['status']} — {len(log['steps'])} steps, "
          f"{len(log['warnings'])} warnings")
    return 0 if log["status"] == "SUCCESS" else 1

if __name__ == "__main__":
    sys.exit(run_pipeline())
```

---

### 4. The Universe Problem (fix first, fix once)

**The problem:** Three "universe" files, each used by different scripts:

| File | Stocks | Used by | Updated |
|------|--------|---------|---------|
| `nifty500_list.csv` | 501 | 06_news, 02_price | Weekly (Sat) |
| `stock_metadata.csv` | 501 | 03_screener, 09_insider, 13_sector, 17_forensic | Weekly (Sat) |
| `universe.csv` | 2,500 | 22_harvester, 27-30_signals, 32_tier, 38_reconstructor | Manual (~monthly) |

**The fix:**

`universe.csv` is the canonical universe. Period. Every script reads it.

But `stock_metadata.csv` has columns (PE, PB, ROE) that `universe.csv` doesn't.
And `nifty500_list.csv` has a simpler format that some scripts prefer.

**Solution: merge, don't replace.**

```
universe.csv (2,500 rows)
  ├── Core: sid, ticker, name, sector, cap_tier, adtv_6m_cr  [from 22_harvester + 32_tier]
  ├── Metadata: market_cap, pe, pb, roe, de, margins         [from yfinance, refreshed weekly]
  ├── Nifty500 flag: in_nifty500 (boolean)                   [from 01_fetch_universe]
  └── Slug: slug                                             [from 23_slug_mapper]
```

One file. One schema. Every script imports `UNIVERSE_FILE` from config and reads the
same 2,500 rows. Scripts that only need Nifty 500 stocks can filter on `in_nifty500 == True`.

**Migration steps:**
1. Add `in_nifty500`, `market_cap`, `pe_ratio`, `sector` columns to `universe.csv`
2. Write a `refresh_universe_metadata.py` that enriches `universe.csv` with yfinance data
3. Update `06_fetch_news.py` to read `universe.csv` instead of `nifty500_list.csv`
4. Update `09_insider_tracker.py` to read `universe.csv` instead of `stock_metadata.csv`
5. Update `03_screener.py`, `17_forensic_guard.py`, `13_sector_analysis.py`
6. After all scripts migrated: delete `nifty500_list.csv` and `stock_metadata.csv`
7. Remove `01_fetch_universe.py` and `02_fetch_price_data.py` (replaced by enrichment script)

---

### 5. Testing Strategy

**The problem:** Zero tests. Every change is a prayer.

**What real systems do:** Three layers of testing, each catching a different class of bug.

**Layer 1: Smoke Tests (run before every pipeline execution)**
```python
# tests/test_smoke.py — runs in 10 seconds, catches catastrophic issues

def test_universe_exists_and_valid():
    df = pd.read_csv(UNIVERSE_FILE)
    assert len(df) >= 2000, f"Universe too small: {len(df)}"
    assert "cap_tier" in df.columns
    assert set(df["cap_tier"].dropna().unique()) == {"LARGE", "MID", "SMALL"}

def test_all_signal_files_exist():
    for f in ["piotroski.csv", "accruals.csv", "consensus.csv", "promoter.csv"]:
        path = DATA_DIR / "signals" / f
        assert path.exists(), f"Missing signal file: {path}"

def test_price_data_not_empty():
    files = list((DATA_DIR / "price_data").glob("*.csv"))
    assert len(files) >= 400, f"Only {len(files)} price files"

def test_regime_state_valid():
    state = json.loads((DATA_DIR / "reference" / "regime_state.json").read_text())
    assert state["regime"] in ["CALM", "NORMAL", "CAUTION", "CRISIS"]
    assert 0 < state["vix"] < 100
```

**Layer 2: Contract Tests (validate inputs/outputs of each script)**
```python
# tests/test_contracts.py — runs per-script, catches interface breaks

def test_06_news_output_schema():
    df = pd.read_csv("data/news/news_archive.csv", nrows=5)
    required = ["article_id", "title", "symbols_str", "source", "published_at"]
    for col in required:
        assert col in df.columns, f"Missing column {col} in news_archive"

def test_07_sentiment_output_schema():
    df = pd.read_csv("data/sentiment/latest_stock_sentiment.csv", nrows=5)
    required = ["symbol", "sentiment_7d", "sentiment_momentum", "articles_7d"]
    for col in required:
        assert col in df.columns

def test_insider_signals_score_range():
    df = pd.read_csv("data/insider/latest_insider_signals.csv")
    assert df["score_impact"].between(-25, 25).all(), "score_impact out of range"

def test_universe_no_duplicate_sids():
    df = pd.read_csv(UNIVERSE_FILE)
    assert df["sid"].is_unique, f"{df['sid'].duplicated().sum()} duplicate sids"
```

**Layer 3: Regression Tests (catch signal drift)**
```python
# tests/test_signals.py — runs weekly, catches silent data quality issues

def test_piotroski_score_distribution():
    df = pd.read_csv("data/signals/piotroski.csv")
    mean_f = df["piotroski_f_score"].mean()
    assert 3.0 < mean_f < 7.0, f"Piotroski mean={mean_f} looks wrong"

def test_sentiment_not_all_neutral():
    df = pd.read_csv("data/sentiment/latest_stock_sentiment.csv")
    non_zero = (df["sentiment_7d"].abs() > 0.01).mean()
    assert non_zero > 0.1, f"Only {non_zero:.0%} of stocks have non-zero sentiment"

def test_enriched_picks_count():
    from pathlib import Path
    latest = sorted(Path("data/screener_output").glob("enriched_*.csv"))[-1]
    df = pd.read_csv(latest)
    assert 10 <= len(df) <= 50, f"Enriched has {len(df)} rows — expected 10-50"
```

**Execution:**
```bash
# Before pipeline runs (in run_pipeline.py):
pytest tests/test_smoke.py -x --tb=short  # fail fast

# After pipeline runs:
pytest tests/test_contracts.py --tb=short

# Weekly (Saturday after refresh):
pytest tests/ --tb=short
```

---

### 6. Data Lineage & Pipeline Log

**The problem:** You can't tell which script produced which file, when, or from what inputs.
If `piotroski.csv` looks wrong, you have to manually trace backward.

**What real systems do:**
- Every output file has a **provenance record**: who wrote it, when, from what inputs, git hash
- A central **lineage log** tracks the full DAG of data dependencies

**Simple implementation (no new dependencies):**
```python
# utils/lineage.py

import json, hashlib
from datetime import datetime
from pathlib import Path

LINEAGE_DIR = Path("data/_lineage")
LINEAGE_DIR.mkdir(exist_ok=True)

def record_output(script_name, output_path, input_paths=None, metadata=None):
    """Record provenance for a pipeline output."""
    output_path = Path(output_path)

    record = {
        "output": str(output_path),
        "script": script_name,
        "timestamp": datetime.now().isoformat(),
        "output_size_bytes": output_path.stat().st_size if output_path.exists() else 0,
        "output_md5": hashlib.md5(output_path.read_bytes()).hexdigest()[:12]
                      if output_path.exists() else None,
        "inputs": {},
        "metadata": metadata or {},
    }

    if input_paths:
        for ip in input_paths:
            ip = Path(ip)
            if ip.exists():
                record["inputs"][str(ip)] = {
                    "size": ip.stat().st_size,
                    "modified": datetime.fromtimestamp(ip.stat().st_mtime).isoformat(),
                }

    # Write to per-file lineage record
    lineage_file = LINEAGE_DIR / f"{output_path.stem}.json"
    lineage_file.write_text(json.dumps(record, indent=2))

    return record
```

**Usage at end of every script:**
```python
# At the end of 27_piotroski.py:
from utils.lineage import record_output
record_output(
    script_name="27_piotroski.py",
    output_path="data/signals/piotroski.csv",
    input_paths=["data/harvester/annual_balancesheet.csv",
                 "data/harvester/quarterly_income.csv",
                 "data/harvester/annual_cashflow.csv"],
    metadata={"rows": len(df), "mean_f_score": df["piotroski_f_score"].mean()}
)
```

---

### 7. Monitoring & Alerting

**The problem:** The only way to know something failed is to check the dashboard manually
or read a 10,000-line log file.

**What real systems do:**
- **Heartbeat:** "pipeline ran successfully" message every morning
- **Failure alert:** immediate notification when something breaks
- **Staleness alert:** if a file hasn't been updated in >24h, something is wrong
- **Anomaly alert:** if today's output is drastically different from yesterday's

**Phase 1 (email-based, using existing infra):**
```python
# Add to end of run_pipeline.py:

def send_daily_summary(log):
    """Send pipeline summary via existing email infrastructure."""
    status = log["status"]
    warnings = log["warnings"]
    steps_ok = sum(1 for s in log["steps"] if s["exit_code"] == 0)
    steps_total = len(log["steps"])

    subject = f"{'✅' if status == 'SUCCESS' else '🔴'} Alpha Signal Pipeline — {datetime.now():%d %b}"
    body = f"""
    Status: {status}
    Steps: {steps_ok}/{steps_total} succeeded
    Warnings: {len(warnings)}

    {''.join(f'  ⚠️ {w}' + chr(10) for w in warnings)}
    """
    # Use existing 04_send_email infrastructure
```

**Phase 2 (Telegram bot — free, instant, mobile):**
```python
# utils/alerting.py — ~20 lines, uses free Telegram Bot API
import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN:
        return
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    )
```

---

### 8. Data Hygiene

**The problem:**
- `insider_archive.csv` is 11MB with no deduplication
- `article_scores_*.csv` growing at 1.5MB/day (45MB/month) with no cleanup
- `snapshot_*.csv` and `enriched_*.csv` accumulate daily copies
- `screener_output/` has one file per day, never cleaned

**What real systems do:**
- **Archive policy:** keep 90 days of daily files, then monthly summaries
- **Deduplication:** enforce unique keys on append
- **Size monitoring:** alert if a file grows beyond expected bounds

**Proposed cleanup script:**
```python
# scripts/99_data_hygiene.py — run weekly (Saturday)

def dedup_insider_archive():
    """Remove duplicate rows from insider_archive.csv."""
    df = pd.read_csv(INSIDER_ARCHIVE)
    before = len(df)
    df = df.drop_duplicates(subset=["symbol", "date", "transaction_type", "person"], keep="first")
    df.to_csv(INSIDER_ARCHIVE, index=False)
    print(f"Insider archive: {before} → {len(df)} rows ({before - len(df)} dupes removed)")

def cleanup_old_dailies(directory, pattern, keep_days=90):
    """Remove daily files older than keep_days."""
    cutoff = datetime.now() - timedelta(days=keep_days)
    for f in directory.glob(pattern):
        if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
            f.unlink()
            print(f"Removed: {f.name}")

def check_file_sizes():
    """Alert if any data file exceeds expected bounds."""
    limits = {
        "insider_archive.csv": 20_000_000,    # 20MB
        "news_archive.csv": 10_000_000,       # 10MB
        "all_snapshots.csv": 50_000_000,      # 50MB
    }
    for name, max_bytes in limits.items():
        # find file and check
        ...
```

---

## Implementation Sequence

This is ordered by **blast radius** — fixes that affect the most scripts first,
because they eliminate the most failure modes in one shot.

### Phase 1: Foundation (Week 1)
| Step | What | Why | Risk if skipped |
|------|------|-----|-----------------|
| 1a | Create `config/pipeline_config.py` | Single source of truth for all constants | Continued config drift |
| 1b | Create `config/schemas.py` with `validate_dataframe()` | Contracts between scripts | Silent data corruption |
| 1c | Create `tests/test_smoke.py` (5 tests) | Catch catastrophic failures | Pipeline runs on missing data |
| 1d | Create `utils/pipeline_runner.py` orchestrator | Error handling + structured logs | Silent 3 AM failures |

### Phase 2: Universe Unification (Week 2)
| Step | What | Why | Risk if skipped |
|------|------|-----|-----------------|
| 2a | Enrich `universe.csv` with metadata + nifty500 flag | Single universe file | Two parallel systems |
| 2b | Migrate `06_fetch_news.py` to read `universe.csv` | News covers 2,500 stocks | 2,000 stocks invisible to sentiment |
| 2c | Migrate `09_insider_tracker.py` | Insider signals for all stocks | Same |
| 2d | Migrate `03_screener.py`, `17_forensic_guard.py` | Consistent universe | Screener sees 501, signals see 2,500 |
| 2e | Retire `nifty500_list.csv`, `stock_metadata.csv` | No more confusion | Ghosts cause future bugs |

### Phase 3: Testing & Monitoring (Week 3)
| Step | What | Why | Risk if skipped |
|------|------|-----|-----------------|
| 3a | `tests/test_contracts.py` for all pipeline outputs | Catch schema breaks | Refactoring becomes terrifying |
| 3b | Add `record_output()` lineage to all scripts | Know what produced what | Can't debug stale data |
| 3c | Daily summary email after pipeline | Know pipeline health | Find out days later |
| 3d | Telegram bot for critical failures | Instant mobile alerts | Sleep through failures |

### Phase 4: Cleanup & Hygiene (Week 4)
| Step | What | Why | Risk if skipped |
|------|------|-----|-----------------|
| 4a | Dedup `insider_archive.csv` | 11MB → probably 3MB | Unbounded growth |
| 4b | `99_data_hygiene.py` weekly cleanup | Auto-clean old dailies | Disk fills up |
| 4c | Remove `.bak` files from `scripts/` | Reduce confusion | Accidental imports |
| 4d | Fix `33_` numbering collision | Clean script ordering | Confusion |

### Phase 5: Documentation (Ongoing)
| Step | What | Why |
|------|------|-----|
| 5a | Keep `AUDIT_NOTES.md` as living audit trail | Track what we understood and when |
| 5b | Each script gets a 5-line header docstring: inputs, outputs, cron schedule, owner | Self-documenting pipeline |
| 5c | `SYSTEM_ARCHITECTURE.md` — auto-generated from schemas + lineage | Always-current system map |

---

## Success Criteria

After all 5 phases, you should be able to answer YES to all of these:

- [ ] Can you add a new signal without touching any other script? (config-driven)
- [ ] If a script fails at 3 AM, do you know within 5 minutes? (alerting)
- [ ] Can you tell which scripts read `universe.csv`? (lineage)
- [ ] If `piotroski.csv` looks wrong, can you trace it to the input that changed? (lineage)
- [ ] Can you run the full pipeline on a new machine with just `git clone` + `pip install`? (reproducibility)
- [ ] Is there exactly ONE file that defines the stock universe? (single source of truth)
- [ ] If someone changes the schema of `consensus.csv`, does a test fail? (contracts)
- [ ] Can you see the last 30 days of pipeline runs with per-step status? (structured logs)

---

## What This Plan Does NOT Cover (and why)

- **Docker/containerization** — overkill for a single-VM, single-user system. Add when you need reproducibility across machines.
- **Airflow/Prefect/Dagster** — proper orchestrators, but the Python runner above gives 80% of the value at 5% of the complexity. Upgrade when you have >50 steps or multi-user.
- **Database** — CSVs are fine for 2,500 stocks × 20 signals. Consider SQLite when you hit 10,000+ rows per signal or need concurrent writes.
- **CI/CD** — you're the only developer. Run tests locally before committing. Add GitHub Actions when you have contributors.
