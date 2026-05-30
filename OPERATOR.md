# OPERATOR.md

**If you are reading this and Amit Bhagat is not reachable, this is the system you have inherited. Read all of it before touching anything.**

Alpha Signal v2 is an AI-native daily stock-picking system for the Indian equity market (NSE/BSE, 2,448 stocks). It runs on cron, writes top picks to a SQLite DB, generates LLM-narrated dossiers, and emails a health report each morning. One human built it. There is no team.

This document is the bus factor. It is intentionally short on theory and long on "where is X" / "how do I not break Y" / "what do I do when Z breaks."

---

## 0. THE SINGLE BIGGEST RISK — FIX FIRST

**The 2.0 GB SQLite database at `data/alpha_signal.db` has no off-host backup.** It contains:
- 4 years of NSE stock prices (~2,400 stocks × 963 trading days)
- 36 months of point-in-time factor snapshots (the entire backtest record)
- 24,000 regulatory events, 25,000 sentiment scores, 29,000 insider trades
- Every daily pick + dossier written since 2026-04-09

If the VM dies, all of it is gone. Some of it (PIT snapshots, sentiment) cannot be reconstructed — those depend on accumulating live data over time.

**Day-1 action**: set up a daily off-host backup. Smallest acceptable shape:
```bash
sqlite3 data/alpha_signal.db ".backup /tmp/alpha.bak" \
  && gzip -c /tmp/alpha.bak | <ship to S3 / second VM / wherever>
```
Cron at 06:00 UTC, AFTER pipeline + health report finish. 2 GB → ~400 MB compressed.

Until this is done, the system is one disk failure from non-recoverable.

---

## 1. THE MACHINE

- **Host**: `instance-20260320-1928` (Oracle Cloud, Ubuntu 24.04 ARM64, Python 3.12.3)
- **User**: `ubuntu`
- **Two directories, one is sacred**:
  - `/home/ubuntu/alpha-signal/`   — v1, still on disk for credentials + venv. **Do not touch.**
  - `/home/ubuntu/alpha-signal-v2/` — current development. This repo.
- **Shared venv**: `/home/ubuntu/alpha-signal/venv/` (used by both v1 and v2). If you `pip install/upgrade`, you're modifying v1's runtime too.
- **DB**: `/home/ubuntu/alpha-signal-v2/data/alpha_signal.db` (SQLite, ~2 GB)

To activate the env in any shell: `source /home/ubuntu/alpha-signal/venv/bin/activate`

---

## 2. THE CRON (all UTC; IST = UTC + 5:30)

Live on the VM, **not in git**. Inspect with `crontab -l`. To edit, `crontab -e`. To reinstall after wipe, save current with `crontab -l > ~/crontab.bak` and `crontab ~/crontab.bak`.

| When (UTC) | What | Log file |
|---|---|---|
| 03:30 daily | Main pipeline — sources, signals, screener, dossier, email | `output/pipeline.log` |
| 04:00 daily | Health report — email + ntfy.sh push on CRITICAL | `output/health.log` |
| 14:00 daily | Forward-only — NSE FII/DII flow, F&O OI, ASM/GSM, ban list (post-EOD) | `output/daily_forward.log` |
| 15:00 daily | Freshness watchdog — re-heal stale tables, log coverage gaps | `output/watchdog.log` |
| 04:30 (1st of month) | yfinance analyst monthly snapshot | `output/yf_snapshot.log` |
| 19:07 (1st of month) | Tickertape monthly refresh | `output/tickertape_cron.log` |

Each cron job sources credentials inline via `eval "$(grep '^export ' /home/ubuntu/alpha-signal/run_pipeline.sh)"`. If that file is missing, every cron silently runs with no auth and produces zero rows.

---

## 3. THE SERVICES (always-on)

| Service | Port | What |
|---|---|---|
| `alpha-cockpit.service` | 3000 | Main cockpit (trading, factor model, MF research) |
| `alpha-cockpit-ops.service` | 3001 | Ops cockpit (`/system`, `/sql`, `/flow`, `/command`) |

Both are systemd units, auto-start on reboot. Standard ops:
```bash
sudo systemctl restart alpha-cockpit         # main
sudo systemctl restart alpha-cockpit-ops     # ops
sudo journalctl -u alpha-cockpit -n 100      # logs
```

**DO NOT** `pkill -f "uvicorn cockpit.app"` — the pattern matches the live systemd process. Kill by PID or include `--port 3000` in the pattern.

---

## 4. THE CREDENTIALS

Every external secret lives in **one shell file**: `/home/ubuntu/alpha-signal/run_pipeline.sh` (2.6 KB, mode 775, owner `ubuntu:ubuntu`). It is read by v1's old cron and **sourced by v2 at runtime** via a one-line `eval` grep.

If you lose this file, every external integration dies the next cron tick. The keys present (values intentionally not here):

| Key | Service | Reissue at |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API (dossier LLM, news enrichment) | console.anthropic.com |
| `ALPHA_SIGNAL_EMAIL` + `ALPHA_SIGNAL_PASSWORD` | Gmail SMTP (health report out) | myaccount.google.com → App Passwords |
| `SCREENER_USERNAME` + `SCREENER_PASSWORD` | screener.in Premium scrape (fundamentals) | screener.in |
| `DATAGOV_API_KEY` | data.gov.in (macro + RBI fetcher) | data.gov.in/user/me |
| `FINNHUB_API_KEY` | Finnhub (held warm; current code paths dead-end) | finnhub.io |
| `NTFY_TOPIC` *(optional)* | ntfy.sh phone push on CRITICAL health issues | per-operator; just a string |

**Day-1 action (after backup)**: move these out of a plaintext shell file into 1Password CLI, AWS Secrets Manager, or at minimum an `age`/`gpg`-encrypted file. One unprotected shell script holding everything is fragile.

---

## 5. THE 3 (4) FILES THAT BREAK THE PIPELINE

Touch with care. If you don't understand them, ask first.

1. **`config.py`** — the system's configuration in one file.
   - `PIPELINE_STEPS` list (order matters; `critical=True` steps abort the pipeline on failure)
   - `SCREEN` constants (eligibility gates, weight thresholds — see ADR 0021)
   - `SIGNAL_WEIGHTS`, `SIGNAL_WEIGHTS_RETURN`, `SIGNAL_WEIGHTS_SHARPE` (factor weights)
   - `EXCLUDED_FROM_PICKS = ("MICRO",)` — DO NOT remove without reading ADR 0026

2. **`scoring/screener.py`** — the `critical=True` pipeline step. Writes `daily_picks`. If it raises, the rest of the pipeline aborts and no dossiers or emails go out.

3. **`db.py`** — runs `_ensure_columns()` + `_ensure_pipeline_log_status_check()` on every `init_db()`. New columns get added via `_COLUMN_MIGRATIONS`. CHECK constraint changes need the table-recreate dance (pattern in `_ensure_pipeline_log_status_check`, added 2026-05-29).

Plus one file that lives outside the repo:

4. **`/home/ubuntu/alpha-signal/run_pipeline.sh`** — credentials. Loss = total auth death. See section 4.

---

## 6. THE DATA

- **`data/alpha_signal.db`** — load-bearing, no backup. See section 0.
- **`data/.cockpit_cache/*.pkl`** — persisted disk cache (Stage 2 cockpit split, 140× cold-restart improvement). Survives `systemctl restart`. **After any weight/screener change, `rm data/.cockpit_cache/*.pkl` BEFORE restart** or stale picks keep serving.
- **`data/health_cache.json`** — health-report cache; safe to delete.
- **`data/factor_correlation_*.json`** — factor correlation diagnostic output; regenerable via `python -m tools.factor_correlation`.

---

## 7. RECOVERY RUNBOOK

**Pipeline didn't run / no email at 09:30 IST**
```bash
tail -100 /home/ubuntu/alpha-signal-v2/output/pipeline.log
# Manual rerun:
cd /home/ubuntu/alpha-signal-v2 && /home/ubuntu/alpha-signal-v2/run_pipeline.sh
```

**Cockpit returns 502 / connection refused**
```bash
sudo systemctl status alpha-cockpit
sudo journalctl -u alpha-cockpit -n 100
sudo systemctl restart alpha-cockpit
```

**Health report shows CRITICAL**
```bash
cd /home/ubuntu/alpha-signal-v2 \
  && eval "$(grep '^export ' /home/ubuntu/alpha-signal/run_pipeline.sh)" \
  && /home/ubuntu/alpha-signal/venv/bin/python -m tools.health_report
```
Then open the cockpit Health Center at `http://<vm-ip>:3001/system` for the Live Issues Inbox (ADR 0023).

**One pipeline step failed; want to rerun that step only**
```bash
cd /home/ubuntu/alpha-signal-v2 \
  && eval "$(grep '^export ' /home/ubuntu/alpha-signal/run_pipeline.sh)" \
  && /home/ubuntu/alpha-signal/venv/bin/python -m <module>  # e.g. scoring.screener
```

**Weights changed but cockpit serves old picks**
```bash
rm /home/ubuntu/alpha-signal-v2/data/.cockpit_cache/*.pkl
sudo systemctl restart alpha-cockpit
```

**NSE harvester returning 403**
- Stop. Don't retry. The WAF locks IPs for 30–60 min on repeated hits.
- Cookie session lives in `data/.nse_cookie_jar` (or similar) — refresh via `sources/nse.py` only after cooldown.

**The DB is corrupt / locked**
- Check for the SQLite WAL: `ls -la data/alpha_signal.db-{shm,wal}`. Stop both cockpit services first (`sudo systemctl stop alpha-cockpit alpha-cockpit-ops`) before doing anything destructive.
- `sqlite3 data/alpha_signal.db "PRAGMA integrity_check;"` — if not "ok", restore from backup. (Once you have one.)

---

## 8. THINGS YOU MUST NOT DO

- **`pkill -f "uvicorn cockpit.app"`** — kills live systemd service. Use the unit.
- **Run two harvesters in parallel** — doubles request rate, risks IP block.
- **Run `graphify --update`** — graph is frozen on the 2026-05-23 snapshot during a trial period. Revisit cadence ~2026-05-31. The post-commit hook currently violates this — disable if it becomes a problem.
- **`git commit --amend`, `git add -A`, `git add .`** — per CLAUDE.md project rules.
- **Modify `/home/ubuntu/alpha-signal/`** — it's v1, still wired to some legacy crons. v2 reads it for credentials only.
- **Push to main without running `tools/pit_replay.py`** — pre-push hook enforces this for `scoring/`, `signals/`, `sources/`, `eligibility/` changes (ADR 0025). Don't bypass.

---

## 9. WHERE THE REST OF THE TRUTH LIVES

| Question | File |
|---|---|
| What was Amit working on when he left | `HANDOFF.md` |
| Where am I in the plan | `docs/plans/0000-checklist.md` |
| Why did we choose X over Y | `docs/decisions/00NN-*.md` (29 ADRs, ≤30 lines each — read them) |
| Detailed design for the active work | `docs/plans/0001-*.md` … `0005-*.md` |
| Project-level rules + landmines | `CLAUDE.md` (this is Claude Code config, but also human-readable) |
| What changed recently | `git log --oneline -30` |
| Doc map | `docs/README.md` |

---

## 10. FIRST WEEK — WHAT I WOULD FIX

If you're a competent operator inheriting this cold, here's the priority order:

1. **Off-host backup of `data/alpha_signal.db`.** Section 0. Do this on day 1.
2. **Move secrets out of `run_pipeline.sh`** into a real secret manager. Section 4.
3. **Audit v1's role.** `/home/ubuntu/alpha-signal/` still has crons in some form. Decide: retire v1, or document why it stays.
4. **Read `CLAUDE.md` and all 29 ADRs in `docs/decisions/`.** They're each ≤30 lines and they encode every decision someone might argue about. Two hours total.
5. **Run `/catchup` in a Claude Code session.** It reads `HANDOFF.md`, runs the health report, and tells you where the prior session left off. The skill is in `~/.claude/skills/` if you don't have it.

If you don't fix #1 and #2, the system will appear to work right up until the day it doesn't.

---

*Last updated 2026-05-29. Update when the cron, services, credentials, or sacred-file list changes.*
