# Plan 0013 — Sonnet Task List: Event-Study Infrastructure + In-House Event Factors

**Status:** ready · **Written:** 2026-07-11 by Opus for a Sonnet executor · **Parent:** [Plan 0011](0011-roadmap-to-90.md) (WS4 + shared infra), sourced from [research 0003](../research/0003-special-situations-event-sleeve.md) + [0001](../research/0001-india-structural-event-factors.md); decisions [ADR 0051](../decisions/0051-roadmap-to-90-decisions-d1-d12.md) D7/D12.

Over-specified on purpose. Every judgment call is a `DECIDED:` line — do not re-litigate. Do
not invent scope. On a `STOP-IF`, write `BLOCKED: <reason>` under the task, commit done work
with the message + ` [partial]`, move on. Never guess.

**Why this plan is the safe subset of Wave A+B.** Research 0003 chose demergers and buybacks
precisely because their tradeable leg SURVIVES the event (demerger → parent stays listed;
buyback → record-date name stays listed), so they carry **no survivorship hole** and can be
backtested on the existing (survivors-only) panel WITHOUT the risky WS2.8 panel rewrite. The
scrape-dependent and panel-rewriting items are explicitly OUT OF SCOPE (see §OUT below) — they
need supervised, single-threaded sessions.

---

## GLOBAL RULES (read twice — they override your instincts)

1. `source ~/alpha-signal/venv/bin/activate` before ANY python. New shell = re-activate.
2. All work in `~/alpha-signal-v2/`. NEVER touch `~/alpha-signal/` (v1 LIVE on cron).
3. **NEVER edit `config.SIGNAL_WEIGHTS` (or variants).** Nothing here wires a weight. Event
   studies produce EVIDENCE (drift curves + t-stats + a study doc), not production changes.
4. **NO external APIs / harvesters / scrapes. In-house data only.** Every table this plan reads
   is already in `data/alpha_signal.db`. If a task seems to need a fetch, it's OUT of scope — STOP-IF.
5. **DB writes allowed ONLY to the ONE new table `event_calendar`** (A3), and ONLY
   `CREATE TABLE IF NOT EXISTS` + `INSERT OR IGNORE`. NEVER `UPDATE`/`DELETE`/`DROP` any table.
   NEVER write to any existing table (bse_announcements, corporate_actions, stock_prices,
   daily_snapshots_pit, pit_ic_by_tier_v2, …). Reads elsewhere are fine.
6. NEVER `git add .`/`-A`/`--amend`. Explicit paths only. One commit per task, exact message,
   end every message with `Co-Authored-By: Claude <noreply@anthropic.com>`.
7. NEVER `pkill -f "uvicorn cockpit.app"` (matches prod). NEVER run the full pipeline.
8. Line numbers are hints — locate by quoted content. Missing content → STOP-IF.
9. A parallel session may be running Plan 0012. Touch ONLY the files this plan names. If a file
   this plan needs to edit has uncommitted changes you didn't make, STOP-IF (`BLOCKED: file
   dirty from parallel session`) — do not merge or overwrite someone else's work.
10. Hypothesis budget: this plan spends **2** event hypotheses (demerger, buyback). Do not add more.

## HUMAN GATES (do the work, then STOP — do not "finish the job")

- **G1:** B1/B2 produce drift-curve STUDIES with verdicts. Whether demergers/buybacks become a
  live sleeve with capital is Amit's call (D7: paper first, ≥6mo). Do NOT build a live producer,
  do NOT wire anything, do NOT allocate.
- **G2:** If a study's edge fails to reproduce (demerger parent CAAR not clearly positive; buyback
  move not clearly positive), that is a VALID, valuable negative — report it honestly, do NOT
  tune windows/filters to manufacture a positive.

---

## §OUT — Explicitly OUT of scope (do NOT attempt; they need supervised sessions)

- **WS2.8 survivorship panel rewrite** — intersecting `historical_universe` into
  `reconstruct_pit.py` REWRITES `daily_snapshots_pit`, the panel every backtest reads. Supervised
  re-baseline only (like ADR 0047), coordinated so nothing reads a half-rewritten panel. NOT here.
  (It blocks the *compounder* cohort study, NOT the demerger/buyback studies below — those are
  survivorship-safe by construction.)
- **Index-rebalance + IPO/lock-up-expiry factors** — data is ABSENT (research 0001); needs
  external scrapes (NSE index circulars / chittorgarh). Single-threaded harvester, separate task.
- **Buyback acceptance-ratio arb leg** — needs PDF/Letter-of-Offer parsing (external + PDF).
  This plan does the IN-HOUSE price-move leg only; the arb-math leg is a later supervised build.

---

## Phase A — Event-study infrastructure (in-house, additive)

### A1 — `tools/event_study.py` (generalize the wired CAR machinery; WS4.2)

**OBJECTIVE:** A reusable event-time market-adjusted CAR framework. The wired
`signals/announcement_car.py` already computes a [−1,+1] CAR around one event via `_car_one`
(read it fully — lines ~85-160). Generalize it to arbitrary (pre, post) windows over an
arbitrary event set, plus a cross-sectional aggregator with a t-stat.

**DECIDED API** (`tools/event_study.py`):
- `event_car(events_df, prices, nifty, pre, post, as_of=None) -> DataFrame[sid, event_date, car]`
  — one market-adjusted CAR per (sid, event) over trading-day window [−pre, +post] around
  day0 = first price row with date ≥ event_date; NIFTY-adjusted (reuse the `_nifty_asof` +
  `_car_one` logic, do NOT re-derive it — import or mirror exactly). NaN when the window isn't
  fully closed by `as_of` (the same look-ahead guard). `nifty` = `macro_history` indicator
  `nifty50` (as announcement_car uses).
- `car_summary(car_df) -> dict` — n, mean CAR, std, t-stat (mean/(std/√n)), median, hit-rate(>0).
- `drift_curve(events_df, prices, nifty, windows, as_of=None) -> DataFrame` — one `car_summary`
  row per window in `windows`.
**DECIDED windows for all studies:** `[(1,1), (0,5), (0,20), (0,60)]` (event reaction + drift).

**VERIFY (the acceptance test — DECIDED):** `event_car` with events = the `category='Result'`
announcement set and window (1,1) must reproduce `compute_announcement_car()`'s values. Write a
check: for 20 sids with a non-NaN announcement_car today, `abs(event_car_value −
announcement_car_value) < 1e-6`. Print PASS/FAIL count; must be 20/20 (or explain each miss).
**STOP-IF:** `signals/announcement_car.py` has uncommitted changes (parallel session) → BLOCKED.
**COMMIT:** `feat(tools): event_study.py — generalized event-time CAR (WS4.2, plan 0013 A1)`

### A2 — sid-mapping crosswalk helper (additive; lifts event usable-n)

**OBJECTIVE:** Research 0003 found event sid-mapping ~53%, halving usable n. Build a READ-ONLY
helper that maps `bse_announcements.scrip_cd` → `sid` via the best available crosswalk, WITHOUT
mutating any table. Downstream (A3) consumes it.

**CONTEXT:** `bse_announcements` has both `scrip_cd` and `sid` (often NULL). `sources/scrip_master.py`
is the BSE scrip crosswalk source (2026-06-09). Inspect it + any `scrip_master`/crosswalk table
in the DB. `corporate_actions` keys on `sid`+`symbol` already.

**DECIDED:** `tools/sid_crosswalk.py::scrip_cd_to_sid() -> dict[int,str]` built from the
in-house crosswalk (scrip_master table if present, else the populated `bse_announcements`
(scrip_cd,sid) pairs as a fallback map). Read-only; returns a dict; writes nothing. Report the
coverage lift: how many distinct scrip_cd in `bse_announcements` are unmapped by the raw `sid`
column vs mappable via this helper.
**VERIFY:** `python -c "from tools.sid_crosswalk import scrip_cd_to_sid; m=scrip_cd_to_sid(); print(len(m))"`
prints a count > the count of distinct non-NULL `bse_announcements.sid`.
**STOP-IF:** no crosswalk source exists anywhere (no scrip_master table AND <100 populated
(scrip_cd,sid) pairs) → BLOCKED.
**COMMIT:** `feat(tools): sid_crosswalk helper — lifts event sid coverage (plan 0013 A2)`

### A3 — `event_calendar` table (WS4.1; the ONLY DB write in this plan)

**OBJECTIVE:** Normalize the two in-house event types into one append-only table the studies read.

**DECIDED schema** (`CREATE TABLE IF NOT EXISTS event_calendar`):
`sid TEXT, event_type TEXT, event_subtype TEXT, announce_date TEXT, record_date TEXT,
source TEXT, loaded_at TEXT` with `PRIMARY KEY (sid, event_type, announce_date)` → `INSERT OR IGNORE`.
**DECIDED population (in-house only):**
- **demerger:** `bse_announcements` rows with `subcategory IN ('Scheme of Arrangement',
  'Amalgamation / Merger / Demerger')` AND `headline` matching (case-insensitive) `demerger` OR
  `de-merger` OR `demerge`. `announce_date = date(dt_tm)`, `record_date = NULL`,
  `event_type='demerger'`, `event_subtype=subcategory`. Map `sid` via A2's helper when the raw
  `sid` is NULL. (Scheme-of-Arrangement is broader than demergers — the headline filter isolates
  demergers; amalgamation-only schemes without a demerger headline are excluded by design.)
- **buyback:** `corporate_actions` rows with `ind='BUYBACK'`. `announce_date = NULL`,
  `record_date = ex_date` (ex_date is the in-house record-date proxy — note in a comment that the
  true tender record date may differ; the study treats ex_date as day0), `event_type='buyback'`,
  `event_subtype = COALESCE(subject,'')`.
**VERIFY:** table exists; `SELECT event_type, COUNT(*) FROM event_calendar GROUP BY event_type`
shows both types with nonzero counts; re-running the populate step adds 0 rows (INSERT OR IGNORE
idempotent).
**STOP-IF:** demerger headline filter yields <30 sid-mapped events OR buyback <30 → note the
count; still create the table, but mark the under-30 study BLOCKED in its phase.
**COMMIT:** `feat(data): event_calendar table — demerger+buyback events, in-house (plan 0013 A3)`

## Phase B — Event studies (built on Phase A; produce verdicts, not products)

### B1 — Demerger parent-drift study (WS4.3; hypothesis 1 of 2)

**OBJECTIVE:** Does buying the PARENT at a demerger announcement beat NIFTY over the drift
window? Research 0003 cites 221 BSE spin-offs 2003-2020 → parent CAAR +2.64% at [+1,+5]. Test
whether our in-house 2020+ event set reproduces a positive parent drift.

**DECIDED:** events = `event_calendar` where `event_type='demerger'`, day0 = `announce_date`.
Run `event_study.drift_curve` over the 4 DECIDED windows. The tradeable leg is the PARENT (the
listed announcer) — that name survives, so no survivorship adjustment needed. Report per window:
n, mean CAR, t, median, hit-rate. Verdict rule — DECIDED: "edge reproduced" iff mean CAR > 0
with t ≥ 1.5 in ≥1 drift window (0,5)/(0,20)/(0,60). Honor G2 — a null is a valid result.

**STEPS:** 1. compute the drift curve. 2. write `docs/studies/demerger-drift-2026-07.md`:
the 4-window table + verdict + honest caveats (n, 2020+ only, announce-date-not-effective-date,
sid-mapping coverage). 3. If edge reproduced, note "Engine-3 sleeve candidate — proceed to paper
per D7" (a human decides; do NOT build it).
**VERIFY:** study doc exists with the 4-window table; the run is reproducible (read-only).
**STOP-IF:** demerger events <30 (from A3) → BLOCKED (thin sample; note n).
**COMMIT:** `study(event): demerger parent-drift across windows (plan 0013 B1)`

### B2 — Buyback record-date price-move study (WS4.3; hypothesis 2 of 2, in-house leg)

**OBJECTIVE:** Does the stock move favorably into/around the buyback record date? This is the
IN-HOUSE price leg only — the acceptance-ratio arbitrage math needs the PDF/LoF layer (§OUT).

**DECIDED:** events = `event_calendar` where `event_type='buyback'`, day0 = `record_date`
(=ex_date proxy). Run the same drift curve, PLUS a pre-event window `(5,0)` (does the run-up
precede the record date?) — add `(5,0)` to this study's window list only. Report the same stats.
Verdict rule — DECIDED: same as B1 (>0, t≥1.5 in ≥1 window). Explicitly state in the doc that
the arb edge (retail 15%-reservation, 60-100% acceptance) is UNMEASURED here and needs the PDF
layer — this study only answers "is there a price move," not "is the tender arb profitable."

**STEPS:** 1. drift curve incl. `(5,0)`. 2. `docs/studies/buyback-move-2026-07.md`: table +
verdict + the explicit arb-leg caveat + capacity note (research 0003: ~₹2L/name retail cap →
enhancer, not book-mover). 3. do NOT build the PDF layer.
**VERIFY:** study doc exists; run reproducible.
**STOP-IF:** buyback events <30 → BLOCKED (note n).
**COMMIT:** `study(event): buyback record-date price-move, in-house leg (plan 0013 B2)`

## Phase C — Close-out

### C1 — Plan/checklist/handoff sync

**STEPS:** 1. In [0011-roadmap-to-90.md](0011-roadmap-to-90.md): tick WS4.1 (A3) + WS4.2 (A1);
add implementation notes under the 2026-07-11 block summarizing A1/A2/A3 outcomes + B1/B2
verdicts (reproduced / null / blocked, with n's). 2. In [0000-checklist.md](0000-checklist.md):
update the Plan-0013 line with `<n>/6 done, <k> BLOCKED`. 3. Overwrite `HANDOFF.md`: Pick-up =
the human gates (B1/B2 verdicts → paper-sleeve decision per D7; the §OUT supervised items:
survivorship rewrite, index/lockup scrapes, buyback PDF layer). Watch out = new `event_calendar`
table (append-only), event_study.py now available for the next event factors.
4. Final: `git status` clean of surprises; every task above = exactly one commit.
**COMMIT:** `docs(handoff): plan 0013 event-infra tranche close-out`

---

## What Sonnet must NOT conclude

- A reproduced demerger/buyback edge does NOT mean "launch a sleeve" (D7: paper ≥6mo, human call).
- A null result is a WIN (honest evidence), not a failure to fix by tuning (G2).
- `event_study.py` existing does NOT authorize building the index/lockup/PDF items in §OUT —
  those need external data and a supervised harvester session.
- The survivorship panel rewrite is NOT in scope and must not be attempted (it would corrupt a
  panel a parallel session may be reading).
