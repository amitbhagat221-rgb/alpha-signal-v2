# 0019 — Observability layer: sensor + sanity + surface + alert
**2026-05-23 · Accepted**

**Decision.** A system that catches silent failures needs four layers, and we were missing two of them:

| Layer | What it checks | Implementation |
|---|---|---|
| **Sensor** (already had) | Did the producer run? Did it raise? | `pipeline_log` rows, CHECK constraints, freshness windows in `data_health()` |
| **Aggregator** (now extended) | Combine signals across producers + file outputs | `data_health()` now includes virtual rows for `config.FILE_OUTPUTS`; `tools/freshness_watchdog.py` heals files + DB tables |
| **Sanity** (new) | Did the producer write *correct* rows? | `tools/data_sanity.py` — 21 assertions (bounds, identity, distribution, cardinality, cross-table consistency) |
| **Surface** (new) | Push the signal to where the user already looks | `tools/health_report.py` — terminal output (consumed by `/catchup`), HTML email (cron 04:00 UTC), URGENT-prefixed email + ntfy push on CRITICAL |

**Why.** Three nested silent failures lived in the gap between Sensor and Sanity for 20+ days:

1. v2 cron lacked `ANTHROPIC_API_KEY` and `GMAIL_USER`. Dossier producer wrote `{status: no_api_key}` placeholders. Email producer saved to disk but couldn't send. **Both "ran cleanly" by Sensor standards** (exit code 0, no exception). `pipeline_log` showed SUCCESS daily.
2. `freshness_watchdog` was scheduled in crontab as a *comment line*, never actually ran. The Sensor existed; nothing observed it.
3. Tickertape's `forecastsHistory.price[-1]` was `lastPrice`, not analyst PT. Daily cron wrote it as `analyst_consensus.price_target` → 95.6% of universe degenerate (PT ≈ close). The Sensor passed (rows written); the Sanity layer didn't exist to flag "rows are wrong."

A "data engineer AI agent" was the wrong answer (more state to drift). The right answer is the plumbing the system already half-had.

**Sanity assertions.** [tools/data_sanity.py:CHECKS](../../tools/data_sanity.py) is a Python list. Each entry is either SQL-form (returns `n_bad / n_total / sample`) or fn-form. The framework computes pct, picks severity (CRITICAL ≥ critical_pct, WARN ≥ warn_pct, else INFO), formats output. Adding a new invariant: append 8 lines to the list, no framework change needed.

Seeded assertions cover:
- **Data-feed integrity** — `PT_EQUALS_PRICE`, `FORECAST_HISTORY_IS_PRICE_HISTORY` (caught the 2026-05-22 corruption)
- **Bounds** — score columns within [0, 9] / [0, 1] / etc.
- **Distribution** — non-degenerate spread (PT_UPSIDE_DEGENERATE caught >80% near-zero)
- **Cardinality** — daily_picks rank uniqueness; tier ∈ {LARGE, MID, SMALL}
- **Cross-table** — `daily_picks.sid` references `stocks.sid`; `consensus_signals` and `daily_picks` agree on snapshot_date
- **Schema correctness** — `FORECAST_HISTORY_NON_YEAREND_PRICE` (no non-Dec entries post-2022)

Future invariants get added when a new silent-failure class is found. The discipline: **before fixing the bug, encode it as an assertion.** That's how the same class never bites twice.

**Health report.** `tools/health_report.py:gather()` is the single source of truth — assembles `pipeline_log` failures + `data_health()` freshness + `freshness_watchdog` last-run + dossier validation status + sanity violations. Three formatters (`format_terminal`, `format_email_html`, `format_push_text`) render the same state for different surfaces — they can't disagree by construction.

Severity rules (CRITICAL escalates to URGENT email + ntfy):
- Pipeline step failed in latest run AND step name contains "screener" | "snapshot" | "dossier" → CRITICAL
- Pipeline step failed ≥2 consecutive days (any step) → CRITICAL (PIPELINE_STREAK)
- Table in `CRITICAL_TABLE_OUTDATED` set is OUTDATED → CRITICAL
- Dossier validation rejected any thesis → CRITICAL (DOSSIER_HALLUCINATION)
- Watchdog hasn't run at all → CRITICAL (the meta-check)
- Any sanity assertion CRITICAL → CRITICAL

**Push channels.** ntfy.sh is opt-in via `NTFY_TOPIC` env var (set in `~/alpha-signal/run_pipeline.sh`). URGENT email always fires when CRITICAL count > 0. No paid services, no third-party signups.

**Catchup integration.** `/catchup` slash command now runs `python -m tools.health_report` first and inserts the output at the top of the situation report. Every session begins with system state visible — the cost of NOT seeing a CRITICAL issue is high; the cost of seeing one extra line is zero.

**Cron entries (live):**
```
0 4 * * *     health_report --email --push
0 15 * * *    freshness_watchdog
30 4 1 * *    yfinance_analyst --snapshot   (monthly)
```
All three source v1's `run_pipeline.sh` exports via `eval "$(grep '^export ' ...)"` for credentials.

**Rollback.** Remove `tools/data_sanity.py` + `tools/health_report.py`; comment out the cron entries; revert `data_health()` to DB-tables-only. The original Sensor layer (freshness watchdog) keeps running. No data risk.

**Related.**
- [HANDOFF 2026-05-22](../../HANDOFF.md) — the day the gaps surfaced
- CLAUDE.md "Health & observability" — the rule set this ADR implements
- [ADR 0018](0018-pt-data-model-episodic-cadence.md) — the silent-failure case study that drove this ADR
- [tools/data_sanity.py](../../tools/data_sanity.py) — the assertion catalogue (extend here when new silent-failure classes emerge)
