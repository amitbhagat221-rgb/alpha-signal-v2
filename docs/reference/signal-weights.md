# Validated Signal Map

From v1 C13b — 36 monthly periods, reproduced by `tools/backtest_pit.py` in v2.

| Signal | LARGE | MID | SMALL |
|--------|-------|-----|-------|
| Consensus | t=3.52 | t=2.20 | t=2.44 |
| CF Accruals | t=0.20 | t=3.20 | t=2.10 |
| Promoter QoQ | t=0.04 | t=0.83 | t=3.20 |
| Earnings Yield | t=1.57 | t=1.01 | t=3.13 |
| Piotroski | t=0.51 | t=2.23 | t=2.81 |
| Book-to-Price | t=0.79 | t=2.33 | t=2.54 |

## Weight tiers

| t-stat | Weight |
|---|---|
| ≥ 2.5 | 1.0× |
| 1.5 – 2.5 | 0.5× |
| 0.5 – 1.5 | 0.2× |
| < 0.5 | 0× |

## `pt_upside` + `smart_money` PULLED (2026-07-05, [ADR 0045](../decisions/0045-pull-pt-upside-lookahead.md))

`docs/audit-2026-07-04-report.md` (Factor-F1, CRITICAL) found that `pt_upside`'s entire
t=7–9 edge across all three tiers was built from `forecast_history` (metric='price') rows —
these "year-end Tickertape snapshots" actually embed the **year-ahead REALIZED CLOSE**, not
a real analyst price target (worse than the already-documented 2026-05-22 HALC contamination:
that fix stopped *daily* price masquerading as PT; this one is the *annual* series itself).
Every pre-2026-05 `pt_upside` value in `daily_snapshots_pit` was look-ahead. Purged
(`UPDATE ... SET pt_upside = NULL WHERE snapshot_date < '2026-05-01'`) and rebuilt from
`analyst_consensus_snapshots` ONLY (2026-05+, real monthly PT snapshots — see
`tools/reconstruct_pit.py::pit_pt_upside`). Clean re-backtest: **n=1 period, INSUFFICIENT**
in all three tiers — the real edge cannot yet be measured, let alone wired.

`smart_money` pulled in the same pass: best-ever backtest was SMALL t=1.06 on n=6 monthly
anchors, violating the documented `|t|≥1.5` promotion bar (audit Factor-F3) — it should
never have carried production weight.

Both removed from `SIGNAL_WEIGHTS`; remaining weights in each tier renormalized
proportionally (Σ|w|=1.0, signs preserved). New weights:

| Tier | Weights (was → now) |
|------|----------------------|
| LARGE | consensus 0.35→**0.47**, earnings_yield 0.12→**0.16**, book_to_price 0.10→**0.13**, accruals 0.09→**0.12**, piotroski 0.09→**0.12** (pt_upside 0.25 removed) |
| MID | accruals 0.20→**0.27**, iv_skew_25d 0.13→**0.17**, piotroski 0.11→**0.14**, book_to_price 0.11→**0.14**, consensus 0.06→**0.08**, governance_resignation −0.08→**−0.11**, earnings_yield 0.04→**0.05**, promoter 0.03→**0.04** (pt_upside 0.24 removed) |
| SMALL | promoter 0.14→**0.19**, earnings_yield 0.11→**0.14**, book_to_price 0.11→**0.14**, delivery_anomaly_z 0.10→**0.12**, sector_tilt 0.10→**0.12**, pledge_quality 0.09→**0.11**, piotroski 0.08→**0.10**, accruals 0.05→**0.06**, momentum 0.02 unchanged (pt_upside 0.15 + smart_money 0.05 removed) |

`SIGNAL_WEIGHTS_RETURN` / `SIGNAL_WEIGHTS_SHARPE` (non-production, `--variant` dry-run
diagnostics only): `pt_upside` set to 0 in place, not renormalized.

**Re-entry condition:** ≥12 clean monthly `analyst_consensus_snapshots`-only anchors
AND |t|≥1.5 in a tier → revisit (calendar: ~2027-05). Until then `pt_upside` stays
computed (visible in the cockpit/backtest) but carries zero production weight.

## In PRODUCTION `SIGNAL_WEIGHTS` beyond the v1 C13b set

Promotion wave 2026-05-31 — idle-but-validated factors brought into production after
an **orthogonality sweep** (each new factor's max |ρ| vs already-wired factors shown).
`pt_upside` was **capped** below its t-implied share pending an artifact re-verify (2026-08)
— that re-verify happened early: see the PULLED section above (2026-07-05, ADR 0045). The
row below is kept for the historical record of why it was promoted in the first place.

| Signal | Tier(s) | t-stat | Weight | Max \|ρ\| vs wired | Notes |
|--------|---------|--------|--------|---------|-------|
| ~~**pt_upside**~~ | LARGE/MID/SMALL | 7.15/8.40/9.14 | ~~0.25/0.25/0.16~~ **PULLED** | 0.27 (vs book/EY) | analyst PT upside; n=35. This t-stat was `forecast_history` look-ahead contamination — PULLED 2026-07-05 (ADR 0045), not capped. |
| **pledge_quality** | SMALL | 5.90 | 0.13 | 0.08 | promoter-pledge stress; orthogonal to promoter (ρ=0.04) |
| **delivery_anomaly_z** | SMALL | 4.76 (n=103) | 0.11 | 0.08 | delivery z-spike; orthogonal to avg_delivery (ρ=0.08) |
| **iv_skew_25d** | MID | +3.16 (48wk) | 0.14 | 0.19 | in-house IV skew (ADR 0035); F&O-only; LARGE/SMALL DROP |
| **sector_tilt** | SMALL | +3.18 (34mo) | 0.10 | orthogonal (new sector dim) | 6m basket-mom + macro ensemble (ADR 0041); LARGE +0.92 / MID +0.64 DROP |
| **governance_resignation** | MID | −3.82 (46mo) | **−0.08** | ≈0.09 (vs forensic cluster) | BSE senior/auditor-resignation density (ADR 0042); **first negative weight** — penalty via `1−pctile`; LARGE −1.61 / SMALL −1.65 WEAK |

(pt_upside/pledge/delivery were already in `scoring/screener.py` `SIGNAL_COLS` + the
MaxReturn/MaxSharpe variants since 2026-05-28/29, but carried **zero production weight**
until this wave — they were computed daily and ranked but unused.)

## Horizon-gate weight review (2026-06-02, [ADR 0038](../decisions/0038-horizon-resolved-promotion-gate.md))

Deliberate, non-mechanical review off the net-of-cost gate (`tools/promotion_gate.py`
→ `factor_horizon_gate`), cross-checked against v1 C13b. **Rule applied: move weight
only where BOTH lenses agree; hold every gate↔history conflict.** (Also fixed the gate's
`_live_keys()` alias bug — the live re-eval had been scoring only 6 of the 12 wired
factors.) Changes:

| Tier | Factor | Was → Now | Why |
|------|--------|-----------|-----|
| LARGE | momentum | 0.04 → **0 (dropped)** | t=0.00 broke the t<0.5→0× rule + gate REJECT |
| LARGE | earnings_yield | 0.15 → **0.12** | over-weighted 0.5×-secondary; gate REJECT in LARGE (strong in SMALL, weak here) |
| LARGE | accruals / piotroski | 0.11/0.07 → **0.09/0.09** | equalised diversification ballast (both gate-REJECT — kept only to avoid over-concentrating consensus) |
| LARGE | consensus | 0.30 → **0.35** | doubly-validated anchor; absorbs freed weight |
| LARGE | book_to_price | 0.08 → **0.10** | gate's only LARGE LIBRARY survivor |
| SMALL | pledge_quality | 0.13 → **0.10** | gate demotes to LIBRARY (1.96), single-horizon-fragile + sign-unstable; kept for orthogonal pledge-stress info |
| SMALL | book_to_price | 0.09 → **0.12** | gate's single strongest factor in the model (net_t 13.58 @252d) |

**MID: unchanged.** Its 3 flags are gate↔history *conflicts* — accruals (v1 t=3.20 vs
gate REJECT), consensus (v1 t=2.20 vs gate REJECT), promoter (gate PROMOTE 4.99 but n=11
thin) — not acted on. Watch-list for the next monthly anchor.

**MID accruals/consensus conflict — RESOLVED 2026-06-14** (Next-3 #3) via the horizon-aware
marginal diagnostic + gate + multiple-testing (3 v2-era lenses vs 1 v1 panel, no one-read
override): **`accruals` 0.18→0.20 KEEP** — the gate REJECT was a fast-horizon artifact; accruals
MID is genuine SLOW alpha (incr_t −5.4 @252d, correct sign, v1 3.20), vindicated. **`consensus`
0.08→0.06 trimmed** — its MID edge DECAYED post-2022 (weak/negative at every v2 horizon, gate
REJECT, MT-fail; only v1 2019-22 supported it; redundant with pt_upside's analyst dimension).
Σ|w|=1.0; screener re-run, 0 CRITICAL.

### `smart_money` validated (2026-06-02, closes the never-backtested gap)

`smart_money_score` (SMALL 0.06, the bulk+delivery composite) was wired with **zero
backtest** — and its config label `t=2.49` was wrong (that was `avg_delivery_pct_30d`'s
number, borrowed via a mis-alias in `_WEIGHT_KEY_TO_SIGNAL` / health_score / promotion_gate).
Registered it properly (`SIGNAL_COLUMN_MAP`, `BACKTEST_SIGNALS`, `BACKTEST_CADENCE`=monthly,
`FACTOR_LINEAGE`) and fixed all three alias maps to point at `smart_money_score`. Verdict:

| Lens | LARGE | MID | SMALL |
|------|-------|-----|-------|
| 20d backtest (`backtest_pit`) | t=−0.10 | t=0.54 | **t=1.06** (n=6, DROP) |
| Net-of-cost gate (natural h) | REJECT 63d | REJECT 63d | **PROMOTE 126d** (net_t 5.03, n=6) |

The two lenses conflict in SMALL (20d weak; a slow-126d edge in the gate), and **n=6 is
thin with a bulk component that has no historical depth** (reconstructed anchors collapse
toward delivery — redundant with `avg_delivery_pct_30d`). **Verdict: PRELIMINARY — held at
0.06, no change.** Now visible to the backtest/gate; re-judge as monthly anchors accrue and
`bulk_deals` depth grows (then it can move to weekly cadence).

### `sector_tilt` — backtest-gated, SMALL-only (2026-06-05, [ADR 0041](../decisions/0041-sector-tilt-backtest-gated-small-only.md))

The daily sector tilt (`mean( z(6m basket momentum), z(macro_score) )` mapped per
stock) was validated **pooled** via Fama-MacBeth (t+3.34 at 3-month horizon, additive
to stock momentum). It was **not** wired on that alone — its close cousin
`sector_momentum` (63d RS) had already backtested WEAK/DROP **within-tier**, and the FM
horizon ≠ the within-tier lens `daily_picks` ranks on. So it was registered as a proper
factor and run through `backtest_pit`:

| Tier | `sector_momentum` (cousin) | `sector_tilt` (this) | Action |
|------|----------------------------|----------------------|--------|
| LARGE | t=−0.60 DROP | t=+0.92 DROP | not wired |
| MID | t=+0.33 DROP | t=+0.64 DROP | not wired |
| SMALL | t=+1.88 WEAK | **t=+3.18 KEEP** (IC +0.023, ICIR 0.545) | **wired 0.10** |

The ensemble beats the cousin in every tier but clears only SMALL → wired SMALL-only at
**0.10** (even −0.01 haircut across the existing ten; orthogonal new sector/macro
dimension, so weighted alongside `delivery_anomaly_z`). Sector-constant by design (a
tilt, not a stock-selector). Re-judge LARGE/MID as the monthly panel deepens.

### `governance_resignation` — first negative weight, MID-only (2026-06-14, [ADR 0042](../decisions/0042-data-acquisition-build-not-buy.md))

Weighted trailing-365d density of senior-officer + auditor resignations off the
(kept-current) BSE announcement stream — the subcategory IS the signal, no PDF
([signals/governance_events.py](../../signals/governance_events.py)). Backtest 46
monthly anchors / 8yr: **MID t=−3.82 KEEP** (IC −0.051, ICIR −0.56, CI [−6.57,−1.71]),
**sign-stable NEGATIVE in all three tiers** (LARGE −1.61 / SMALL −1.65 WEAK). The
deepest-history of any recent candidate. Deliberate review (not the mechanical
|t|≥2.5→primary):

- **Orthogonality** — within-MID Spearman ρ vs the forensic/quality cluster (the natural
  redundancy risk) is tiny: piotroski_f −0.04, m_score (Beneish) +0.06, pledge_quality
  +0.01, forensic_penalty +0.05 → **max |ρ| ≈ 0.09**, well under the 0.27 promotion-wave
  bar. An event-stream governance dimension is structurally independent of
  statement-derived forensics — exactly the REXP-lesson complement (Beneish/Altman/Sloan
  are YoY/distress detectors; "who resigned" is orthogonal information).
- **Sizing — 0.08, below iv_skew's 0.14 despite a stronger |t|.** It's a tail-penalty
  (~41% of MID flagged, the rest tied at 0 → the percentile compresses to a ~0.71 max
  spread, so effective influence ≈ 0.056), it's brand-new with no horizon-gate
  corroboration yet, and it's the **first genuine negative weight** in the live scheme —
  all argue for restraint over the t-implied "primary" share.
- **Negative weight mechanics** — `config.SIGNAL_WEIGHTS["MID"]["governance_resignation"]
  = −0.08`; [scoring/screener.py](../../scoring/screener.py):296 flips a negative weight
  to `|w|·(1−pctile)`, so a resignation-heavy name gets a low contribution (a penalty)
  and a clean name the favourable end. The denominator uses `Σ|w|`, so Σ|w|=1.0 holds.
- **MID-only** — LARGE/SMALL are WEAK (same sign), not wired (mirrors the sector_tilt
  SMALL-only call). Funded by an **even −0.01 haircut across the existing eight** MID
  factors (ordering preserved; deliberately does NOT re-cut the held accruals/consensus/
  promoter gate↔history conflicts beyond the shared 0.01).
- **Verified** — production rerun: flagged names demoted (JBCHEPHARM g=5.0 rank 3→32,
  BOSCHLTD g=3.5 −19, CENTRALBK g=3 −13), top-20 MID picks mean g=0.825 vs universe 1.013
  (picks lean governance-clean), rank ρ with/without = 0.98 (a tilt, not an upheaval).
  data_sanity 0 CRITICAL, health green, daily_picks 1697 rows.

Follow-ons: run the horizon-gate (`tools/promotion_gate.py`) on it for net-of-cost
corroboration as anchors accrue; surface the raw intensity as a cockpit forensic
red-flag (dual-use, à la REXP) — separate from the cross-sectional weight.

## Multiple-testing reality check (2026-06-14, [ADR 0043](../decisions/0043-multiple-testing-aware-factor-significance.md))

`|t|≥2.5` is **necessary, not sufficient**. Across **269 backtested (signal,tier) hypotheses**,
naive α=0.05 expects ~13.5 false discoveries; [tools/multiple_testing.py](../../tools/multiple_testing.py)
(Harvey-Liu-Zhu haircut) puts the Bonferroni bar at **|t|≈4.2** and passes only **8 of 269** under
Benjamini-Yekutieli FDR (dependence-robust). Read each weight through this lens:

| Robustness (BY-FDR) | Wired factors |
|---|---|
| ✓ **survive** (bulletproof) | ~~`pt_upside` (L/M/S)~~ **PULLED 2026-07-05 — this "bulletproof" t-stat was look-ahead contamination (ADR 0045); no longer wired**, `pledge_quality` (S), `delivery_anomaly_z` (S) |
| ~ borderline (pass BH, fail BY) | `governance_resignation` (M, p_BY 0.075), `iv_skew_25d` (M), `sector_tilt` (S) |
| ✗ fail the haircut | `consensus`, `book_to_price`, `piotroski`, `accruals`, `earnings_yield`, `promoter`, ~~`smart_money`~~ **PULLED 2026-07-05 (n=6, sub-bar; ADR 0045)**, `momentum` |

The ✗-tier is **not** a delisting order — those are kept on the deliberate **diversification-ballast**
rationale (horizon-gate review) or **doubly-validated v1×v2** history (consensus, book_to_price). The
rule (ADR 0043): a haircut-failing factor gets **no *added* weight**, and a **new** factor's KEEP must
clear this lens before wiring. Run it in every promotion review alongside the horizon gate.

## Marginal contribution, HORIZON-AWARE (2026-06-14, Track 3.3b — [tools/factor_marginal.py](../../tools/factor_marginal.py))

Sequential rank-IC Fama-MacBeth (collinearity-robust partial corr) on the WIRED factors, at a
GRID of horizons {20,63,126,252}d (Newey-West-corrected for forward-window overlap), 46 monthly
anchors. **Key lesson: marginal contribution is horizon-dependent — judging at 20d alone
systematically under-credits slow value factors.** A first 20d-only pass flagged
`book_to_price`/`accruals` as redundant; the horizon sweep shows that was a **horizon artifact**:

| Factor (tier) | incr_t 20d → 252d | Read |
|---|---|---|
| `book_to_price` SMALL | −3.9 → −2.5 → +7.2 → **+13.3** | slow value — strong at 6-12mo (gate: 252d PROMOTE 13.58); NOT redundant |
| `book_to_price` MID | +0.1 → +0.7 → +1.0 → **+2.0** | slow value — earns weight at the value horizon |
| `accruals` MID | −1.5 → −2.0 → −3.4 → **−5.4** | slow accruals effect (correct sign), grows with horizon |
| `pt_upside` LARGE/MID | +8→+22 / +9.6→+23 | compounds — even stronger long |
| `governance_resignation` MID | **−3.4** → −0.1 → −0.4 → −0.6 | FAST forensic — near-term red flag, fades by 1y (natural 20d) |
| `delivery_anomaly_z` SMALL | **+4.0** → +0.8 → −2.0 | FAST microstructure (natural 20d) |
| `sector_tilt` SMALL | +3.1 → **+4.1** → +1.9 | 1-3mo sector momentum (natural 63d) |

**Conclusion — no trims.** The model diversifies across HORIZONS (fast forensic/microstructure +
slow value/analyst); each factor's weight is broadly matched to where its IC peaks. The apparent
20d redundancies were slow factors mis-judged at a fast horizon — trimming them would delete real
alpha. **One genuine flag:** `consensus` MID is weak/negative at EVERY horizon (−0.5/−2.4/−1.7/−1.5)
— the known MID conflict; held only on v1 history → revisit in the MID re-judge (Next-3 #3), don't
add weight. (Low-cov factors ⚠ are 0.5-imputation-distorted — lean on the backtest; iv_skew weekly.)

## On the bench (validated, deliberately NOT wired)

- **eps_growth** (LARGE t=5.31 / SMALL t=3.23) — **redundant**: ρ=0.63 with consensus in LARGE, ρ≈0.3–0.4 with the value/quality cluster in SMALL. Analyst/growth dimension already carried by consensus + pt_upside. Stays in the variants only.
- **kyle_lambda** (LARGE t=+4.24 / MID t=+4.14, 39mo) — Amihud illiquidity premium, but ρ(kyle, ln_ADTV)=−0.73: a cost-coupled liquidity tilt (you'd pay the spread you're paid for), MID IC decaying. Held as diagnostic.
- **Contrarian/unverified-sign + tiny-n**: interest_coverage (MID t=−3.69, sign-flip vs SMALL), roic/fcf_margin (negative, counterintuitive), iv_term_structure (n=7), sentiment_7d (n=4), eps_growth_yoy LARGE (n=8) — parked pending sign/regime verification or more periods.
- **§3.2.4 earnings-call NLP factors** (46 monthly anchors, look-ahead-safe on the real BSE filing date — Next-3 #1c). **`uncertainty_word_density`** LARGE **t=+2.90 KEEP** (IC +0.049, CI [1.00,5.24]) — but the sign is **CONTRARIAN** (more hedging/uncertainty → *higher* returns, backwards from the Loughran-McDonald-uncertainty hypothesis) and it's **LARGE-only** (the tier the walk-forward flags as ~zero OOS skill) over a single 2022-26 regime → **NOT wired, parked for sign/regime verification** (same discipline as `ccc`/`nwc_to_revenue`/`corporate_action_density`). `forward_looking_intensity` LARGE +1.67 / SMALL +1.94 WEAK (sensible positive sign, sub-2.5). `earnings_call_tone_qoq` DROP all (tone-momentum didn't replicate). The lasting win is the look-ahead-safe NLP infra; the factors join `FACTOR_LIBRARY`.
- F&O OI four + iv_realised_spread / iv_term_structure / iv_percentile_1y — see `FACTOR_LIBRARY`.
- **gross_profitability** (audit gap #5, first backtest 2026-07-05) — registered 2026-05 as the multibagger funnel's Novy-Marx quality anchor, never run through `backtest_pit` until now. Full 48-anchor PIT reconstruction (2022-08→2026-07, matching `roic`'s fundamentals_screener-covered range): **SMALL t=−3.91 KEEP, MID t=−2.18 WEAK, LARGE t=−1.32 DROP** — all three tiers **NEGATIVE** sign, the opposite of the textbook Novy-Marx positive quality premium. Contrarian-sign KEEP is not auto-promotion-eligible (same discipline as `uncertainty_word_density`) — **NOT wired**, parked in `FACTOR_LIBRARY` for sign/regime verification. The multibagger funnel's own use of gross_profitability (a holding-screen input, not a cross-sectional rank factor) is a different mechanism and is unaffected.

## Pending backtesting

- Insider (2yr reconstructed)
- Regulatory (3yr events)
- Macro sector (3yr indicators)
- Track 3 Phase 3.2 factors (plan 0002)
