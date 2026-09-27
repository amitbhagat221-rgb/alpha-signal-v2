# OPERATOR.md

**If you are reading this and Amit Bhagat is not reachable, this is the system you have inherited. Read all of it before touching anything.**

Alpha Signal v2 is a daily stock-intelligence system for Indian equities (NSE/BSE; universe = `stocks` table, ETFs excluded). It runs on cron, ranks stocks within market-cap tiers into `daily_picks`, writes LLM-narrated dossiers and emails a health report each morning. One human built it and there is no team. It is a research system: no live capital is managed by it.

This document is the bus factor: where things are, how not to break them, what to do when they break. The **working rules** (venv, never touching v1, credentials `eval`, no two harvesters at once, never `pkill -f "uvicorn cockpit.app"`, git hygiene) are in [CLAUDE.md → Critical Rules](CLAUDE.md). They are not repeated here.

---

## 0. Backups

- **DB, nightly 05:00 UTC:** `backup_db.sh` (in the repo dir, gitignored like all `*.sh` except the two run wrappers). It runs `VACUUM INTO` a snapshot, checks `PRAGMA integrity_check`, gzips it and runs `rclone copy` to `gdrive:alpha-signal-v2-backups`. The remote keeps dailies for 7 days and 1st-of-month snapshots long-term. If the remote is missing, it keeps the last 2 locally in `backups/`. Log: `output/backup.log`. rclone credentials live in `~/.config/rclone/rclone.conf`.
- **Restore:** `rclone copy gdrive:alpha-signal-v2-backups/alpha_signal_YYYYMMDD.db.gz .`, then `gunzip`. Stop both cockpit services first, then swap the file into `data/alpha_signal.db`.
- **Secrets + wiring: NOT scheduled.** `backup_secrets.sh` exists and GPG-encrypts credentials, crontab and the rclone token to Drive, but no cron runs it. Its passphrase file lives only on this VM. Schedule it and keep the passphrase in a password manager.
- Some history cannot be rebuilt from the backup's upstream sources: PIT snapshots, `analyst_consensus_snapshots`, sentiment and forward-only feeds exist only because they accumulated. Guard the backup.

---

## 1. The machine

- **Host:** Oracle Cloud VM, Ubuntu 24.04 ARM64, Python 3.12, user `ubuntu`.
- `/home/ubuntu/alpha-signal/` is **v1**. It holds the shared venv and the credentials file. All of v1's own crontab lines are commented out (kept for rollback).
- `/home/ubuntu/alpha-signal-v2/` is this repo and production. Sessions work in `.claude/worktrees/*`.
- **DB:** `data/alpha_signal.db`, a single SQLite file in WAL mode, ~8.6 GB on disk (2026-09-26; check with `ls -la`). For the table list, run `sqlite3 data/alpha_signal.db .tables` (≈135). There is also a DuckDB read replica (ADR 0031).

---

## 2. The cron (all UTC; IST = UTC + 5:30)

Cron lives in the crontab (`crontab -l`); back it up before editing (`crontab -l > ~/crontab.bak`). Since plan 0015 every v2 line except the backup is `/home/ubuntu/alpha-signal-v2/run.sh <job> >> <log> 2>&1`: **`run.sh` (in git) is the one preamble** — repo dir, venv, the read-only credential import, email variables, and the harvest `flock` for harvesting jobs. `DRY=1 ./run.sh <job>` prints what a job runs. Never add an inline cron one-liner; add a `case` to `run.sh`.

| When (UTC) | Job | Log (under `output/` unless noted) |
|---|---|---|
| When (UTC) | `run.sh` job | What | Log (under `output/` unless noted) |
|---|---|---|---|
| 03:30 daily | `morning` | the main pipeline (`pipeline.py`, harvest `flock`), then the DuckDB replica | `pipeline.log` |
| 04:00 daily | `health` | health email, plus URGENT email and ntfy push on CRITICAL | `health.log` |
| 04:20 / 12:20 / 20:20 | `screener_cookie` | Screener.in session keep-alive, ntfy push when auth dies | `screener_keepalive.log` |
| 04:30 on the 1st | `pt_snapshot` | `yfinance_analyst --snapshot` → `analyst_consensus_snapshots` | `yf_snapshot.log` |
| 05:00 daily | (`backup_db.sh`, own script) | DB → Google Drive (§0) | `backup.log` |
| 05:00 on the 1st | `expected_return` | appends the E[1Y] prediction to `data/expected_return_predictions.jsonl` | `logs/expected_return_cron.log` |
| 05:15 on the 2nd | `backtest` | monthly IC refresh (`pit_ic_by_tier_v2`) | `backtest_refresh.log` |
| 06:00 on the 1st + 15th | `screener_universe` | full Screener refresh (harvest `flock`) | `screener_universe_refresh.log` |
| 14:00 daily | `forward` | forward-only feeds after NSE EOD (FII/DII, surveillance, BSE announcements, scrip master; harvest `flock`) | `daily_forward.log` |
| 15:00 daily | `watchdog` | heals stale tables/files, emails on gaps | `watchdog.log` |
| 19:07 on the 1st | `tickertape` | Tickertape fundamentals (~4h, harvest `flock`) | `tickertape_cron.log` |

Inside the 03:30 pipeline, each step's `frequency` gates it: `daily`, `weekly` (Sundays), or `monthly` (the 1st); `--step <name>` ignores the gate. **Order is derived, not listed:** `graph.py` sorts the steps by their declared `reads`/`writes` with the email's critical path first (`config.PIPELINE['derived_order']`; set False to run the list order). Slow jobs the email doesn't need land after it by construction. Only two steps are `critical` and abort the run: `fetch_bhavcopy` (also when prices are stale) and `screener`. Every step writes a row to `pipeline_log`; `output/graph_shadow/` records the order and any table a step read without declaring it.

---

## 3. The services (always-on)

| Unit | Port | What |
|---|---|---|
| `alpha-cockpit.service` | 3000 | Main cockpit (picks, factor model, portfolio, MF research) |
| `alpha-cockpit-ops.service` | 3001 | Ops cockpit (`/system` Health Center, `/sql`, `/flow`, `/command`) |

```bash
sudo systemctl restart alpha-cockpit          # or alpha-cockpit-ops
sudo journalctl -u alpha-cockpit -n 100
```

---

## 4. The credentials

Every external secret is an `export` line in **`/home/ubuntu/alpha-signal/run_pipeline.sh`** (v1's file; read-only for v2). If it is lost, every integration dies at the next cron tick. Keys present (values intentionally not here):

| Key | Service | Reissue at |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API (dossiers, news/regulatory classification) | console.anthropic.com |
| `ALPHA_SIGNAL_EMAIL` + `ALPHA_SIGNAL_PASSWORD` | Gmail SMTP (health email, digest) | Google account → App Passwords |
| `SCREENER_USERNAME` + `SCREENER_PASSWORD` | screener.in (the live session is the cookie JSON in `~/.cache/`) | screener.in |
| `DATAGOV_API_KEY` | data.gov.in macro | data.gov.in/user/me |
| `FINNHUB_API_KEY` | Finnhub (held warm; code paths dead-end) | finnhub.io |
| `NTFY_TOPIC` *(optional)* | ntfy.sh phone push on CRITICAL | any string |

These sit in a plaintext shell file. Move them to a secret manager, or at least an encrypted file (see §0 on `backup_secrets.sh`).

---

## 5. The files that break the pipeline

1. **`config.py`**: `PIPELINE_STEPS` (order matters), `SCREEN` gates, `SIGNAL_WEIGHTS` (production; `_RETURN`/`_SHARPE` are non-production diagnostics), and `EXCLUDED_FROM_PICKS = ("MICRO",)`. Read ADR 0026 before touching the last one.
2. **`scoring/screener.py`**: the critical step that writes `daily_picks`. If it raises, no dossiers or email go out. The pick gate is in `_pick_eligible` (ADR 0021 → 0024).
3. **`db.py` + `schema.sql` + `tables.py`**: `init_db()` executes `schema.sql` (full DDL, regenerated from the live DB 2026-09-26), then `_COLUMN_MIGRATIONS`. A new column goes in `schema.sql` AND `_COLUMN_MIGRATIONS`; a new table in `schema.sql` AND `tables.TABLES` (`tests/test_tables.py` enforces it). CHECK-constraint changes need the table-recreate pattern (create `<t>__new`, copy, drop, rename).
4. **`/home/ubuntu/alpha-signal/run_pipeline.sh`** (outside the repo): the credentials. See §4.

---

## 6. The data model in one screen

- **Universe and tiers:** `stocks.cap_tier`. LARGE = top 100 by market cap, MID = ranks 101–250, SMALL = the rest, and MICRO = illiquid names carved out of SMALL by `tools/classify_micro_tier.py`. MICRO is classified but never picked (ADR 0026). The screener has no ADTV floor; the ₹1 Cr/day liquidity floor is applied at portfolio construction (`config.PORTFOLIO["min_adtv_inr"]`), and MICRO uses its own ₹1 Cr ADTV gate in `classify_micro_tier.py`. Ranking is always within one tier (ADR 0005).
- **Financials** rank through the generic screener. `financial_signal_scores` is display-only (ADR 0048).
- **Factors:** each `signals/*` module writes its own `*_scores` table. Every factor is registered in `db.BACKTEST_SIGNALS` and PIT-backtested. Only validated ones carry weight ([signal-weights.md](docs/reference/signal-weights.md), ADRs 0017/0043/0049).
- **PIT:** backtests read `daily_snapshots_pit` / `daily_snapshots_pit_v1`, never live tables. Corporate actions are composed at compute time (ADR 0010).
- **Cache files:** `data/.cockpit_cache/*.pkl` survives restarts. **After any weight or screener change, delete them before restarting**, or stale picks keep serving. `data/health_cache.json` and `data/factor_correlation_*.json` can be regenerated (`python -m tools.factor_correlation`).

---

## 7. Recovery runbook

**No email by 09:30 IST.** Check `tail -100 output/pipeline.log`, then rerun with `/home/ubuntu/alpha-signal-v2/run.sh morning >> output/pipeline.log 2>&1` (it exits quietly if another harvester holds the lock).

**One step failed.** Run `python pipeline.py --step <name>` from the repo with the venv and credentials loaded (CLAUDE.md). The ops cockpit `/flow` page also has a Rerun button.

**Health report shows CRITICAL.** Run `python -m tools.health_report` (terminal view), then open the Health Center at `http://<vm-ip>:3001/system` (ADR 0023).

**Cockpit 502.** Check `sudo systemctl status alpha-cockpit`, read `journalctl`, then `restart`.

**Weights changed but cockpit shows old picks.** `rm data/.cockpit_cache/*.pkl && sudo systemctl restart alpha-cockpit`.

**NSE returns 403.** Stop and don't retry: the WAF locks the IP for 30–60 minutes. Nothing is persisted; each run warms a fresh cookie session (nselib does this internally).

**Screener cookie dead (ntfy "Screener cookie DEAD").** Paste a fresh `sessionid` from a browser into `~/.cache/screener_cookie.json` (docstring of `sources/screener_pull.py`, path B).

**DB corrupt or locked.** Stop both cockpit services. Check for `data/alpha_signal.db-{wal,shm}` and run `sqlite3 data/alpha_signal.db "PRAGMA integrity_check;"`. If it doesn't report `ok`, restore from Drive (§0).

---

## 8. Operator-specific don'ts (on top of CLAUDE.md)

- **Don't bypass the pre-push hook** (`ops/hooks/pre-push`, versioned; enabled by `git config core.hooksPath ops/hooks`). It runs the `tests/` suite (pytest lives in `.devlib/`, outside the shared venv: `pip install --target .devlib -r requirements-dev.txt`), the regression fixtures, and `tools/pit_replay.py` when `scoring/`, `signals/`, `sources/` or `eligibility/` change (ADR 0025). A PIT-replay FAIL after an intended pick change is cleared with `python -m tools.pit_replay freeze`.
- **Don't run `graphify --update`.** The graph is still frozen on the 2026-05-23 snapshot. The post-commit hook that rebuilt it is disabled (`.git/hooks/post-commit.disabled`).
- **Don't `pip install`/upgrade** into the shared venv without remembering that v1 uses it too.

---

## 9. Where the rest of the truth lives

| Question | File |
|---|---|
| What was being worked on | `HANDOFF.md`, `docs/plans/0000-checklist.md` |
| What's being built | [docs/plans/README.md](docs/plans/README.md) (active: 0011, 0014) |
| Why we chose X | [docs/decisions/README.md](docs/decisions/README.md). Part (a) gives the current decision per topic across 51 ADRs |
| How data sources behave | [docs/reference/data-playbook.md](docs/reference/data-playbook.md) |
| Rules + landmines | `CLAUDE.md` |
| Doc map | [docs/README.md](docs/README.md) |
| What changed recently | `git log --oneline -30` |

---

## 10. First week: what I would fix

1. **Schedule `backup_secrets.sh`** and store its passphrase off-host (§0). The DB backup already runs.
2. **Move secrets out of the plaintext shell file** (§4).
3. **Retire v1 formally.** Its crontab lines are all commented out; it survives only as the venv and credentials host.
4. **Read [docs/decisions/README.md](docs/decisions/README.md) part (a)**, then the ADRs it names.
5. **Run `/catchup` in a Claude Code session.** It reads `HANDOFF.md`, runs the health report and tells you where the last session stopped.

## Glossary

**Factor/signal:** one predictive number per stock. **Tier/cap_tier:** market-cap bucket; ranking is always within a tier. **PIT:** point-in-time, meaning only data knowable on the date. **IC/ICIR:** rank correlation of a factor with the forward return, and its mean/σ. **ADTV:** average daily traded value (₹ Cr). **SID:** Tickertape stock ID (≠ NSE ticker). **Dossier:** AI-written one-page thesis per top pick, with no raw numbers in its prose. **UHS:** Unified Health Score (ADR 0033). **SEBI RIA:** the registration required to sell stock advice in India.

*Last updated 2026-09-26 (facts re-verified against `crontab -l`, `systemctl`, the live DB and `config.py`). Update this file whenever the cron, services, credentials or backup change.*
