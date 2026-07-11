# New factors — reports (plan 0012 Phase C)

Shared report for C1–C4. Registration + backtest + report for each factor;
**zero `SIGNAL_WEIGHTS` changes** — a human wires anything from here (ADR 0043
stance, GLOBAL RULE 3).

## C1 — `eps_revision_yoy` live producer (WS2.1a)

Producer: [signals/eps_revision.py](../../signals/eps_revision.py), wired into
`scoring/screener.py::_load_signals` + `SIGNAL_COLS` as computed/ZERO weight.

Clean-panel backtest (`pit_ic_by_tier_v2`, `source LIKE 'v2_recompute%'`):

| cap_tier | n_periods | mean_ic | t_stat | verdict |
| --- | --- | --- | --- | --- |
| LARGE | 38 | 0.0274 | 1.49 | DROP |
| MID | 38 | 0.0006 | 0.04 | DROP |
| SMALL | 38 | 0.0271 | 2.78 | KEEP |

Multiple-testing (`tools/multiple_testing`): SMALL p_BY = 1.0000 (fails BY-FDR
outright — the naive KEEP does not survive correction).

**Honest read:** SMALL-only, and the naive |t|=2.78 KEEP evaporates completely
under the BY-FDR correction (p_BY=1.0) — this is very likely a false discovery
from the ~280-hypothesis factor zoo, not a robust edge. The live producer is
correctly built and matches its validated PIT recipe (hand-verified on 3 sids),
but the "validation" behind it is thin. **Not a promotion-review candidate on
this evidence alone** — a human should treat this as "computed and available
for inspection," not "ready to wire."

## C2 — `value_composite` live producer + swap-vs-stack evidence (WS2.1b)

Producer: [signals/value_composite.py](../../signals/value_composite.py), wired
into `_load_signals` + `SIGNAL_COLS` as computed/ZERO weight. Reuses the
already-computed live `earnings_yield`/`book_to_price` frames (no
recomputation) + an inline 252-trading-day `position_52w`. Mirrors
`tools.reconstruct_pit.pit_value_composite`'s NaN-tolerant within-tier rank
composite exactly (40/35/25 weights) — this intentionally diverges from the
plan's STEPS gloss ("NULL if any component missing"): the point of this task
is comparability against the *already-validated* PIT composite, so fidelity to
that recipe wins over the STEPS' looser paraphrase. Full coverage: 1,856/1,856
screener-universe rows.

Clean-panel backtest:

| cap_tier | n_periods | mean_ic | t_stat | verdict |
| --- | --- | --- | --- | --- |
| LARGE | 43 | 0.0074 | 0.26 | DROP |
| MID | 43 | 0.0424 | 1.87 | WEAK |
| SMALL | 43 | 0.0308 | 3.32 | KEEP |

Multiple-testing: SMALL p_BY = 0.3612 (fails BY-FDR, but far less badly than
C1 — this is the "borderline, diversification-supported" tier ADR 0043 talks
about, not an outright false discovery).

**Swap-vs-stack evidence** (Spearman ρ on the live frame, today):

| cap_tier | ρ(value_composite, book_to_price) | ρ(value_composite, earnings_yield) | n |
| --- | --- | --- | --- |
| LARGE | 0.8696 | 0.8610 | 100 |
| MID | 0.8292 | 0.8232 | 149 |
| SMALL | 0.7114 | 0.8150 | 1,607 |

STOP-IF check: ρ(composite, book_to_price) > 0.95 in every tier → NOT
triggered (max is 0.87, LARGE) — the composite is not simply a repackaged
`book_to_price`.

Clean-panel t-stats for the SMALL-tier swap decision: **value_composite
t=3.32 (KEEP) vs book_to_price t=1.88 (WEAK)** — the composite is the
substantially stronger SMALL-tier value read, and SMALL ρ(composite, b2p)=0.71
is the lowest of the three tiers (least redundant where it matters most).

**Framed decision for the human (ADR 0049 rule 4, one value representative
per orthogonal group) — left EXPLICITLY open, not made here:**
**"swap `book_to_price` → `value_composite` in SMALL: yes/no?"**
- *For yes:* composite t=3.32 > b2p t=1.88, ρ=0.71 (meaningfully different
  ranking, not a relabel), and it additionally incorporates `earnings_yield`
  and `position_52w` — arguably capturing "cheap AND been-beaten-down" rather
  than book value alone.
- *For no:* composite still fails BY-FDR (p_BY=0.36) same as b2p would; MID is
  only WEAK (1.87) and LARGE outright DROPs (0.26) — swapping in SMALL only
  while `book_to_price` stays the value factor in LARGE/MID creates a
  tier-inconsistent factor definition that a future reviewer may find
  confusing without this note.

**Honest read:** value_composite is a real improvement over book_to_price
specifically in SMALL (higher clean t, lower redundancy), but it's still a
BY-FDR failure, not a robust factor — "better than a WEAK factor" is not the
same as "KEEP-grade." A human should weigh the swap against portfolio-construction
tidiness, not treat this as a slam-dunk promotion.

## C3 — `residual_momentum_12_1` (WS2.6, hypothesis 1 of 2)

Full unit shipped: [signals/residual_momentum.py](../../signals/residual_momentum.py)
+ `pit_residual_momentum_12_1` in `tools/reconstruct_pit.py` + registered in
`db.BACKTEST_SIGNALS`/`FACTOR_LIBRARY`/`lineage.py` + `backtest_pit.py`
`SIGNAL_COLUMN_MAP`. **NOT wired** (`SIGNAL_WEIGHTS` untouched). 12-1 momentum
(skip most recent ~21 trading days), residualized against NIFTY-50 market beta
(OLS over the same window, min 150 paired daily-return obs) — the designed
retest of plain momentum (Jegadeesh-Titman 1993 window; Blitz-Huij-Martens
2011 residualization).

Backtest: 66 monthly anchors, 2020-02→2026-07 (`--months 80` full history).

| cap_tier | n_periods | mean_ic | t_stat | verdict |
| --- | --- | --- | --- | --- |
| LARGE | 66 | 0.0293 | 1.33 | DROP |
| MID | 66 | 0.0210 | 1.11 | DROP |
| SMALL | 66 | 0.0319 | 2.84 | KEEP |

Multiple-testing: SMALL p_BY = 0.8832 (fails BY-FDR outright).

**Honest read:** SMALL clears the naive |t|≥2.5 KEEP bar with the correct
hypothesised sign (positive — momentum persists after removing market beta),
and all three tiers show the same POSITIVE sign (LARGE/MID just weaker) —
internally consistent, not a sign flip. But p_BY=0.88 means this does not
survive multiple-testing correction; per ADR 0043, |t|≥2.5 is necessary, not
sufficient. **Promotion-review candidate on sign/theory grounds, not on
robustness** — a human should weigh the clean theoretical story (this is
exactly the retest WS2.6 was designed to run, and it beat plain momentum)
against the BY-FDR failure before considering it further. Stays in
FACTOR_LIBRARY per RULE 3.
