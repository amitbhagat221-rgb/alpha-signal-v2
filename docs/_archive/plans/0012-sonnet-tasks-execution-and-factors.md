# Plan 0012 — Sonnet Task List: Execution Layer + Shovel-Ready Factors

**Status:** done (2026-07-11, 10/10 tasks; archived 2026-09-26) · **Written:** 2026-07-06 by Fable for a Sonnet executor · **Parent:** [Plan 0011](../../plans/0011-roadmap-to-90.md) (WS1 + WS2 shovel-ready subset)

This plan is deliberately over-specified. Every judgment call is pre-answered in a `DECIDED:`
line. Do not re-litigate DECIDED items. Do not invent scope. If a task hits a `STOP-IF`
condition, write `BLOCKED: <reason>` under that task in THIS file, commit what's done with the
task's commit message + suffix ` [partial]`, and move to the next task. Never guess.

---

## GLOBAL RULES (read twice — they override your instincts)

1. `source ~/alpha-signal/venv/bin/activate` before ANY python. Every time. New shell = re-activate.
2. All work in `~/alpha-signal-v2/`. NEVER touch `~/alpha-signal/` (v1 is LIVE on cron).
3. **NEVER edit `config.SIGNAL_WEIGHTS` (or `_RETURN`/`_SHARPE` variants).** Weight changes are
   human decisions (ADR 0043 stance). Nothing in this plan wires a weight. A factor you build
   gets registered + backtested + reported — that is ALL.
4. NEVER `git add .`, `git add -A`, `git commit --amend`. Add files by explicit path. One commit
   per task with the exact message given. End every commit message with:
   `Co-Authored-By: Claude <noreply@anthropic.com>`
5. NEVER run the full pipeline (`python -m pipeline`), any harvester/fetcher, or anything that
   calls an external API. **Every task here uses in-house data only.**
6. NEVER `pkill -f "uvicorn cockpit.app"` (matches the prod systemd service).
7. Line numbers in this plan are hints — locate code by the quoted content. Quoted content
   missing entirely → STOP-IF applies.
8. New factor tasks (C3, C4) consume the plan-0011 hypothesis budget (≤10/month): this plan
   spends **2**. Do not add more factors than specified.
9. Read-only DB access unless a step explicitly says otherwise. The ONLY DB writes in this
   plan are the ones `reconstruct_pit.py --signal <x>` and `backtest_pit.py` make by design
   (safe-by-construction per CLAUDE.md), and the prediction JSONL file (not a DB table).
10. `daily_snapshots_pit` / `pit_ic_by_tier_v2`: clean rows are `source LIKE 'v2_recompute%'`.
    Never pad missing PIT_COLUMNS with NaN before a write (wipes untouched columns on UPDATE).

## HUMAN GATES (do these tasks' work, then STOP and flag — do not "finish the job")

- **G1:** B2 produces a *recommendation* for production cadence parameters. Changing the
  production default is Amit's call. Do NOT edit the production banded builder's defaults.
- **G2:** C1/C2 add computed, **zero-weight** signals to the screener. Do NOT re-run the
  production screener or rebuild the book; the daily cron exercises it. Your verification is
  the read-only `_load_signals()` end-to-end check specified in the task.
- **G3:** If any VERIFY step shows a wired factor's behavior changed (row counts, coverage),
  STOP the task and mark BLOCKED — do not "fix" production behavior.

---

## Phase A — Read-only studies (no production risk)

### A1 — Rank-IC localization mini-study (plan-0011 WS1.4 prerequisite)

**OBJECTIVE:** Does the edge concentrate at the top of the rank? Decides whether conviction
sizing is worth building. Output: `docs/studies/rank-localization-2026-07.md` + a small
read-only script `tools/rank_localization.py`.

**CONTEXT:** `pick_outcomes` columns: `sid, pick_date, window_days, cap_tier, rank_at_pick,
final_score, entry_price, exit_date, exit_price, fwd_return_pct, bench_index,
bench_return_pct, excess_return_pct, computed_at`. Use `window_days = 20` rows only.

**STEPS:**
1. Write `tools/rank_localization.py` (read-only; mirror the docstring/style of
   `tools/factor_decay.py`). For each `cap_tier` in (LARGE, MID, SMALL): bucket
   `rank_at_pick` into 1–5, 6–10, 11–20, 21–50; report per bucket: n, mean and median
   `excess_return_pct`, hit rate (>0), and a two-sample t-stat of bucket 1–5 vs 6–10
   (use `scipy.stats.ttest_ind`, `equal_var=False`).
2. Repeat the same from the PIT panel as a second lens: for the latest 24 clean anchors in
   `daily_snapshots_pit` (`source`-agnostic — the panel itself), within-tier
   quintile-1 vs quintile-2 mean `fwd_return_20d` using the composite proxy: rank by
   `delivery_anomaly_z` for SMALL only (the sole robust factor). Label this clearly as a
   single-factor proxy, not the model.
3. Write both tables + a 3-sentence verdict to `docs/studies/rank-localization-2026-07.md`.
   Verdict rule — DECIDED: "localizes" iff bucket-1–5 beats 6–10 with t ≥ 1.5 in ≥1 tier in
   the `pick_outcomes` lens. Otherwise conclude "flat weights are honest" and WS1.4 is CLOSED-NO.

**VERIFY:** `python -m tools.rank_localization` prints both tables, exits 0, file exists.
**STOP-IF:** `SELECT COUNT(*) FROM pick_outcomes WHERE window_days=20` < 500 → BLOCKED (not
enough outcomes; note the count).
**COMMIT:** `study(rank): rank-IC localization mini-study — WS1.4 gate (plan 0012 A1)`

### A2 — Registry limbo classification report (WS7.1 evidence)

**OBJECTIVE:** The audit found 38 signals registered but neither wired nor in FACTOR_LIBRARY.
Produce the evidence table a human needs to disposition them. NO config changes.

**STEPS:**
1. Run `python -m tools.verify_factor_library` — capture its limbo list. (Tool exists;
   built 2026-07-05 per audit fastest-win #8.)
2. For each limbo signal: query `pit_ic_by_tier_v2` clean rows (`source LIKE 'v2_recompute%'`),
   take best-|t| tier, n, verdict; if no clean row, note "never backtested on clean panel".
3. Write `docs/studies/registry-limbo-2026-07.md`: one table, columns
   signal / best tier / t / n / verdict / recommended bucket. Bucket rule — DECIDED:
   |t|≥1.5 & n≥20 → "promotion-review candidate"; has any backtest → "FACTOR_LIBRARY";
   never backtested → "backtest or retire". Recommendations only — a human moves them.

**VERIFY:** report exists; row count in report == limbo count from the tool.
**STOP-IF:** `tools/verify_factor_library.py` missing or errors → BLOCKED (it was promised
by ADR 0017 / audit fastest-wins; if absent, note that and stop A2).
**COMMIT:** `study(registry): limbo-signal classification report (plan 0012 A2)`

### A3 — Survivorship-exposure diagnostic (WS2.8 evidence, read-only half)

**OBJECTIVE:** Quantify what the survivors-only backtest panel is missing BEFORE anyone
changes `reconstruct_pit.py`. Read-only.

**CONTEXT:** `historical_universe` = reconstructed true universe incl. delisted (built for the
multibagger study, never referenced by `reconstruct_pit.py` — audit Data-F1).
`stocks` = current (survivors). Dead names = in `historical_universe`, not in `stocks`.

**STEPS:**
1. Inspect `PRAGMA table_info(historical_universe)` to get its symbol/date columns (do not
   assume names; adapt the queries to what exists).
2. Report: (a) count of dead names; (b) per anchor-year 2023–2026, how many dead names have a
   `stock_prices` row within 7 calendar days of at least 6 monthly anchors that year (i.e.
   would have entered the panel under the ADR-0047 guard); (c) for those, mean 20d forward
   return in their final 6 months of life vs the panel's survivor mean (the amputated tail).
3. Write `docs/studies/survivorship-exposure-2026-07.md` with the three tables + a one-line
   per-factor risk note: distress-loading factors (pledge_quality, governance) are most inflated.

**VERIFY:** report exists with all three sections and no empty tables.
**STOP-IF:** `historical_universe` table missing or has 0 non-current symbols → BLOCKED.
**COMMIT:** `study(survivorship): dead-name panel-exposure diagnostic (plan 0012 A3)`

---

## Phase B — Execution layer (WS1)

### B1 — Tax line in the expected-return decomposition (WS1.3)

**OBJECTIVE:** Add Indian capital-gains tax to `tools/expected_return.py`'s decomposition.

**CONTEXT:** Tool exists (2026-07-05); read it fully first. It already prints an
as-operated vs monthly-cadence cost split and appends predictions to
`data/expected_return_predictions.jsonl`.

**DECIDED (statutory, no research):** STCG 20% (holding <365d), LTCG 12.5% (≥365d; ignore
the ₹1.25L exemption — advisory book, assume it's consumed). STT already inside
`TRANSACTION_COSTS_BPS` — do NOT double count. Implied holding period = 1 / (one-way daily
turnover × 252) years; <1yr ⇒ STCG applies to the gross positive return, else LTCG. Tax drag
= applicable rate × max(pre-tax E[return], 0), reported as its own line and stored in the
JSONL as `tax_drag`. Yes, this is a simplification (taxes realized gains, not E[return]) —
state that in a comment; precision here is false precision.

**STEPS:** add `TAX = {"stcg": 0.20, "ltcg": 0.125}`; compute per operating mode (as-operated
6.2%/day ⇒ ~16-day implied hold ⇒ STCG; monthly-cadence 20%/mo ⇒ ~1.05yr ⇒ LTCG); add the
printed line + JSONL field; keep `--no-log` behavior.

**VERIFY:** `python -m tools.expected_return --no-log` runs clean; tax line appears in both
modes; as-operated tax > monthly-cadence tax; JSONL not appended (--no-log).
**COMMIT:** `feat(expected_return): STCG/LTCG tax drag in the 1Y decomposition (plan 0012 B1)`

### B2 — Cadence parameter sweep, sim-only (WS1.1 evidence; HUMAN GATE G1)

**OBJECTIVE:** Find the banded-book parameters that hit plan-0011's acceptance bar, WITHOUT
touching production. All work inside `tools/rebalance_sim.py`'s replay machinery.

**CONTEXT:** `tools/rebalance_sim.py` replays the production `_build_banded` in memory
("nothing written"). Current banded: top-8 exit / 2.0pp band → 6.2%/day one-way, net ann
+2.0% vs gross +30.3%. Acceptance bar (plan 0011 WS1.1): ≤1.5%/day AND net_ann within 4pp of
gross_ann AND daily-return corr vs the current banded book ≥0.90.

**DECIDED sweep grid:** exit-rank {8, 10, 12} × drift band {2, 3, 4 pp} × score-EMA halflife
{None, 3, 5, 10 trading days}. EMA is applied to each sid's `final_score` history BEFORE the
banded builder ranks (implement inside the sim as a pre-processing option — pandas
`ewm(halflife=h)` per sid over the pick-date series; sids missing from a date carry no value,
do not fill).

**STEPS:**
1. Add a `--sweep` mode to `rebalance_sim.py` (keep default behavior byte-identical when the
   flag is absent) that runs the 36-cell grid and prints one row per cell: params, turnover
   %/day, gross/net ann, net Sharpe, corr vs current banded.
2. Mark cells passing ALL THREE acceptance criteria. Pick the winner: max net_ann among
   passers; tiebreak lower turnover. If NO cell passes, report the 3 nearest misses.
3. Write results + recommendation to `docs/studies/cadence-sweep-2026-07.md`. **STOP — G1:**
   do not change any production default or config value.

**VERIFY:** `python -m tools.rebalance_sim` (no flag) output unchanged vs pre-task run (save
both to files, diff — the sim prints deterministic replay stats); `--sweep` completes and the
study doc exists.
**STOP-IF:** sweep wall-clock > 60 min → reduce grid to {8,12}×{2,4}×{None,5} and note it.
**COMMIT:** `feat(rebalance_sim): cadence/EMA parameter sweep — WS1.1 evidence, prod untouched (plan 0012 B2)`

### B3 — Monthly prediction cron (WS1.5)

**OBJECTIVE:** `tools/expected_return.py` runs itself monthly so the prediction log becomes a
track record without anyone remembering.

**DECIDED:** cron line (1st of month 05:00 UTC — after the 04:00 health email and 04:30
snapshots cron; mirrors the mandatory `cd` + env pattern from CLAUDE.md):
`0 5 1 * * cd /home/ubuntu/alpha-signal-v2 && eval "$(grep '^export ' /home/ubuntu/alpha-signal/run_pipeline.sh)" && /home/ubuntu/alpha-signal/venv/bin/python -m tools.expected_return >> logs/expected_return_cron.log 2>&1`

**STEPS:** 1. `crontab -l` → save a backup copy to `docs/studies/crontab-backup-2026-07-06.txt`.
2. Append the line via `(crontab -l; echo '<line>') | crontab -`. 3. Document the cron in
`docs/reference/commands.md` (it's crontab-only, invisible to git — the standing gotcha).
**VERIFY:** `crontab -l | grep expected_return` shows exactly one entry; backup file exists;
run the command body once by hand (it must exit 0 and append one JSONL line).
**STOP-IF:** `crontab -l` errors or shows an empty crontab (would mean the prod crons live
elsewhere — do not create a parallel crontab) → BLOCKED.
**COMMIT:** `ops(cron): monthly expected_return prediction snapshot (plan 0012 B3)`

---

## Phase C — Factor work (registration + backtest + report; ZERO weight changes)

**Shared context for C1–C4.** The registration touchpoints for a new backtestable factor are
exactly the files where the template factor appears. Template — DECIDED: `st_reversal_21d`
(built 2026-07-05, price-based, same shape as C3/C4). Discovery command:
`grep -rn "st_reversal_21d" --include="*.py" .` → you will find, at minimum: the PIT column +
`pit_` function + emit-filter in `tools/reconstruct_pit.py`, `SIGNAL_COLUMN_MAP` in
`tools/backtest_pit.py`, and `BACKTEST_SIGNALS` / `BACKTEST_CADENCE` / `FACTOR_LINEAGE` /
`FACTOR_LIBRARY` entries in `db.py`. Mirror EVERY occurrence for the new factor. The PIT
emit-filter gotcha: `reconstruct_pit.py` writes only the columns the requested signals
produced — never NaN-pad others (GLOBAL RULE 10). Backtest sequence for a new factor F:
```
python -m tools.reconstruct_pit --signal F            # builds F's PIT column, all anchors
python -m tools.backtest_pit --signal F               # writes pit_ic_by_tier_v2 rows
python -m tools.multiple_testing                      # haircut lens (read-only report)
```
Smoke-test discipline: compute the live signal for 3 sids and eyeball before any full run.
Report format for each factor: append a section to `docs/studies/new-factors-2026-07.md`
with per-tier IC/t/n/verdict + the multiple-testing p_BY + a 2-line honest read.
**Never touch `SIGNAL_WEIGHTS`. If a result screams KEEP, the report says so and a human wires it.**

### C1 — `eps_revision_yoy` live producer (WS2.1a; validated SMALL t=2.78, n=38)

**OBJECTIVE:** The factor is validated on the clean panel but has no live producer — the
screener can't see it. Build the producer as a computed, zero-weight signal (G2).

**CONTEXT:** PIT recipe lives in `tools/reconstruct_pit.py::pit_consensus` (line ~1010): YoY %
change between the latest and ~12-months-prior (9–18mo window) `forecast_history` snapshots of
**metric='eps'** per sid. `forecast_history` metric='price' is CONTAMINATED look-ahead
(ADR 0045) — **eps rows are genuine forward estimates** (the file says so explicitly ~line
2943); touching metric='price' anywhere in this task is forbidden.
Producer pattern to mirror: `signals/announcement_car.py` + its import/merge block in
`scoring/screener.py::_load_signals` (~line 180) and the `SIGNAL_COLS` dict (~line 267).

**STEPS:**
1. `signals/eps_revision.py::compute_eps_revision_yoy()` — as-of today, mirror `pit_consensus`'s
   `_yoy` helper logic against `forecast_history` (`WHERE metric='eps' AND date <= today`);
   return DataFrame `[sid, eps_revision_yoy]`, NULL (absent row) when <2 usable snapshots.
   Clip to ±500 (the PIT range guard uses the same bounds).
2. Smoke test 3 sids with known coverage; then coverage count over the universe (expect
   LARGE-heavy coverage; SMALL sparse is normal).
3. Wire into `_load_signals` (import + merge, exactly like announcement_car) and add
   `"eps_revision_yoy": "eps_revision_yoy"` to `SIGNAL_COLS` with a comment
   `# computed, ZERO weight — pending human promotion review (plan 0012 C1)`.
4. In `config.py`, the `"eps_revision_yoy": "PROPOSED"` status entry (~line 984): update to
   the status value the codebase uses for computed-but-unweighted signals — find the value by
   looking at what `announcement_car` had before ADR 0050 wired it (git log / the dict's other
   entries); if unclear, leave untouched and note it.
5. **VERIFY (the G2-safe end-to-end):**
   `python -c "from scoring.screener import _load_signals; df=_load_signals(); print(len(df), df['eps_revision_yoy'].notna().sum())"`
   — must return the full universe row count (~2448) and a nonzero coverage; every
   pre-existing column count unchanged vs a baseline captured BEFORE the edit (capture:
   same one-liner without the new column, run before step 3).
**STOP-IF:** `forecast_history` metric='eps' has <500 sids with ≥2 snapshots → producer would
be hollow; BLOCKED with the count.
**COMMIT:** `feat(signal): eps_revision_yoy live producer — computed, zero weight (plan 0012 C1)`

### C2 — `value_composite` live producer + swap-vs-stack evidence (WS2.1b; validated SMALL t=3.32)

**OBJECTIVE:** Same as C1 for `value_composite`, PLUS the redundancy evidence a human needs
for the ADR-0049 rule-4 decision (one value representative: swap vs book_to_price, or skip).

**CONTEXT:** PIT recipe `tools/reconstruct_pit.py::pit_value_composite` (line ~1089): within-
tier rank composite of `earnings_yield` 0.40 + `book_to_price` 0.35 + `position_52w` 0.25.
The screener already computes live `earnings_yield` and `book_to_price` (see `_load_signals`);
`position_52w` = (close − 52w low) / (52w high − 52w low) from `stock_prices` (it's a
FACTOR_LIBRARY member — check `db.py` for its exact definition and mirror it).

**STEPS:**
1. `signals/value_composite.py::compute_value_composite()` — reuse the live earnings_yield /
   book_to_price frames (refactor `_load_signals` minimally to avoid recomputation — pass
   them in as arguments) + inline 252-trading-day position_52w; within-`cap_tier` percentile
   ranks, weighted 40/35/25; NULL if any component missing.
2. Wire into `_load_signals` + `SIGNAL_COLS` as computed/zero-weight (same comment pattern as C1).
3. Evidence: on the live frame, per tier, Spearman ρ(value_composite, book_to_price) and
   ρ(value_composite, earnings_yield). Append to `docs/studies/new-factors-2026-07.md`:
   the ρ table + clean-panel t's (composite 3.32 vs b2p 1.88 in SMALL) + the framed decision
   "swap b2p→composite in SMALL: yes/no" left EXPLICITLY for the human (G2/RULE 3).
**VERIFY:** same `_load_signals` end-to-end check as C1 (universe rows, new column coverage,
pre-existing columns untouched).
**STOP-IF:** live ρ(composite, b2p) > 0.95 in every tier → it IS b2p; report and skip the wire
recommendation (still commit the producer — the composite may diverge as inputs refresh).
**COMMIT:** `feat(signal): value_composite live producer + swap-vs-stack evidence (plan 0012 C2)`

### C3 — Build + backtest `residual_momentum_12_1` (WS2.6; hypothesis 1 of 2)

**OBJECTIVE:** 12-1 momentum residualized against NIFTY — the designed retest of plain
momentum (which failed the clean bar at SMALL t=1.34). Full unit: signal + PIT helper +
registration + backtest + report. NOT wired.

**CONTEXT:** Prices: `stock_prices` (`sid, date, close, ...`; adjusted closes; min 200 obs
convention per `low_vol_252d`). Market series: `macro_history` indicator `nifty50` — the same
source `signals/announcement_car.py` uses (`NIFTY_ID = "nifty50"`, see its `_nifty_asof`
helper). Template for every registration touchpoint: `st_reversal_21d` (grep per shared context).

**DECIDED spec:** for each sid at eval date D: window = trading days [D−252, D−21] (skip the
last month — reversal contamination). Daily log returns; OLS beta vs NIFTY daily log returns
over the same dates (min 150 paired obs, else NULL). Residual momentum = Σ(stock_ret) − beta ×
Σ(nifty_ret) over the window. No shrinkage, no sector residualization (v1 of this factor —
keep it simple). Expected sign: POSITIVE (winners persist). Cadence: monthly.

**STEPS:** 1. `pit_residual_momentum_12_1` in `reconstruct_pit.py` + PIT column + emit filter.
2. Register everywhere st_reversal_21d is registered (db.py lineage entry: cite Jegadeesh-
Titman 1993 / Blitz-Huij-Martens 2011, expected +, `FACTOR_LIBRARY` initially).
3. Smoke: 3 sids, one anchor, hand-check the window arithmetic (print window dates + beta).
4. Full run: `--signal residual_momentum_12_1` reconstruct → backtest → multiple_testing.
5. Report section per shared format. If |t|≥1.5 anywhere: flag "promotion-review candidate,
   correct sign required" — a human decides. It stays in FACTOR_LIBRARY regardless (RULE 3).
**VERIFY:** backtest writes 3 tier rows to `pit_ic_by_tier_v2`; n_periods ≥ 60 (price-based,
2020+ anchors); report section exists.
**STOP-IF:** `macro_history` nifty50 series starts after 2021-01-01 (insufficient overlap) →
BLOCKED with the MIN(date).
**COMMIT:** `feat(factor): residual_momentum_12_1 + PIT helper + backtest — library (plan 0012 C3)`

### C4 — Build + backtest `max_lottery_21d` (WS2.7; hypothesis 2 of 2)

**OBJECTIVE:** MAX/lottery factor (Bali-Cakici-Whitelaw 2011): retail lottery preference
overprices extreme-daily-return names. Same full unit as C3. NOT wired.

**DECIDED spec:** at eval date D: mean of the 5 highest daily simple returns over trading days
[D−21, D−1] (min 15 obs, else NULL). Expected sign: NEGATIVE (high MAX → low forward return).
Cadence: monthly. Template: `st_reversal_21d` (same window mechanics). Lineage cite: Bali,
Cakici & Whitelaw 2011; note "long-only use would be exclusion/penalty-shaped, like
governance_resignation" in the lineage description.

**STEPS/VERIFY/report:** identical shape to C3 (registration sweep, smoke 3 sids, reconstruct
→ backtest → multiple_testing, report section; FACTOR_LIBRARY).
**STOP-IF:** none beyond the shared rules.
**COMMIT:** `feat(factor): max_lottery_21d + PIT helper + backtest — library (plan 0012 C4)`

---

## Phase D — Close-out

### D1 — Plan/checklist sync + handoff

**STEPS:**
1. In [0011-roadmap-to-90.md](../../plans/0011-roadmap-to-90.md): tick WS1.3 (B1), WS1.5 (B3), WS2.6+2.7
   (C3, C4) if done; add one-line implementation notes for A1–A3/B2/C1/C2 outcomes under
   "Implementation notes" (they're evidence/gated tasks — the human decisions remain open).
2. In [0000-checklist.md](../../plans/0000-checklist.md): update the Plan-0011 NOW block: "Plan 0012
   Sonnet tranche executed: <n>/10 tasks, <k> BLOCKED — see plan 0012 for BLOCKED notes."
3. Overwrite `HANDOFF.md` (Left off / Pick up here / Watch out): Pick-up = the three human
   gates (B2 cadence recommendation → flip production?; C1/C2 promotion review; A1 verdict →
   WS1.4 go/no-go). Watch out = new cron line (crontab-only, invisible to git), zero-weight
   signals now computed in `_load_signals`.
4. Final verify: `python -m tools.multiple_testing` exits 0; `git status` shows no unstaged
   surprises; every task above has exactly one commit.
**COMMIT:** `docs(handoff): plan 0012 Sonnet tranche close-out`

---

## What Sonnet must NOT conclude from this plan

- A KEEP-grade t-stat on C3/C4 does not mean "wire it" (ADR 0043: |t|≥2.5 necessary-not-
  sufficient; sign must match the stated prior; BY-FDR context required).
- A passing B2 cell does not mean "change production" (G1).
- Zero-weight signals in SIGNAL_COLS are not "forgotten" — they are the deliberate
  pre-promotion state (the 2026-05-28 precedent).
