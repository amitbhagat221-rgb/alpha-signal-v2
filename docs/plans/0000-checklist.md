# Alpha Signal v2 — Progress Checklist

_The scannable status board. **Plans are truth, this is the view.** Full session history → `git log` + `HANDOFF.md`; the "why" → `docs/decisions/`; weights rationale → `docs/reference/signal-weights.md`. Update via `/handoff`._
_Glyphs: ✅ done · ⏳ in progress/next · 🚫 blocked · 💤 parked · ↔ cross-track link._
_Numbering: [ADR 0015](../decisions/0015-track-numbering-and-rename.md) (tracks) + [ADR 0016](../decisions/0016-plan-numbering-fresh-start.md) (plans). Last updated: 2026-06-14._

## Next 3 (active priorities)

**1. ✅ BSE event-stream factor families** ([ADR 0042](../decisions/0042-data-acquisition-build-not-buy.md), build-not-buy) — the keystone free unlock: corporate-announcement stream, survivorship-complete to 2018, 2.48M filings, sid-mapped via `scrip_master` (89.8% universe). Core families DONE (1a-1d); 1e/pledge deferred.
  - ✅ 1a PEAD date-swap — real `Result` `dt_tm` (85.5% match); re-backtest still all-DROP → constraint is the consensus-EPS *surprise*, not the date ([[pead-factors-need-earnings-announcement-dates-consensus-proxy-failed]]).
  - ✅ 1b keep-current wiring — `bse_announcements --days 7` daily into run_daily_forward.sh (FRESH).
  - ✅ 1c **`governance_resignation`** ([signals/governance_events.py](../../signals/governance_events.py)) — MID t=−3.82 KEEP, **WIRED MID −0.08** (2026-06-14; first negative weight in the live scheme); orthogonal (max|ρ|≈0.09 vs forensic cluster). LARGE/SMALL WEAK, unwired.
  - ✅ 1d **transcript look-ahead fix** (2026-06-14) — `doc_date` month-proxy → real BSE filing `dt_tm` via PDF-GUID join (79.7%); canonical `available_date` carried into `nlp_scores` (100%). Closes a median +14d look-ahead before any NLP factor is backtested.
  - 💤 1e **credit-rating directional factor — DEFERRED 2026-06-14** (feasibility probed, don't re-probe). Richest family (14.5K events / 1,480 sids) but direction mostly PDF-locked: classifying all events → 67% boilerplate · 23% neutral · only ~10% directional, and that slice is **upgrade-skewed 805:88** (downgrades buried in the PDF). Headline-only would capture upgrades (≈ momentum) and miss downgrades (the valuable half) → biased + likely redundant. A good factor needs a PDF/agency-data extraction layer (~9.8K PDFs, agency-specific parse) — defer to a dedicated session if pursued.
  - 💤 pledge events (buried in Insider/SAST).
  - _Free quick-wins backlog: SEC-EDGAR ADR PIT audit · jugaad-data `stock_prices`→2018 (un-benches `credit_beta`). (✅ Deflated-Sharpe/multiple-testing done — [tools/multiple_testing.py](../../tools/multiple_testing.py)/[ADR 0043](../decisions/0043-multiple-testing-aware-factor-significance.md).)_

**2. `pt_upside` artifact re-verify (due ~2026-08)** — capped 0.16–0.25 in `SIGNAL_WEIGHTS`; gate already self-corrected it to FAST 5d. Re-run `backtest_pit --signal pt_upside` once ≥3 fresh `analyst_consensus_snapshots` exist → un-cap or pull.

**3. MID weight conflicts — ✅ RESOLVED 2026-06-14** (horizon-aware marginal + gate + multiple-testing): **`accruals` 0.18→0.20 KEEP** (gate REJECT was a fast-horizon artifact; it's genuine SLOW alpha, incr_t −5.4 @252d + v1 3.20), **`consensus` 0.08→0.06 trim** (MID edge decayed post-2022 — weak/negative at every v2 horizon, only v1 supported it). 3 v2-lenses vs 1 v1 panel, not a one-read override; Σ|w|=1.0, screener re-run, 0 CRITICAL. _(`smart_money` n=6 / Kite + §3.2.3 intraday still queued.)_

**4. REXP-class forensic (steady-state revenue fraud)** — ✅ hard exclusion shipped (`turnover>8× AND |margin|<0.5%`, REXP rank 79→ABSENT). Deeper detectors 💤 TBD per user: Dechow F-score (needs headcount), standalone-vs-consolidated divergence (needs a standalone pull).

_(Crypto convex cockpit → **decoupled to its own repo `~/crypto-convex`** since 2026-06-09; Phase 0 Q1 passed there. No longer tracked here.)_

## Tracks

**Track 1 — Foundation** ✅ done 2026-05-01 — audit + tier infra + stratified backtest + 36mo PIT + cutover (ADRs 0009-0014).

**Track 2 — Portfolio** ([plan 0001](0001-mother-plan.md))
- ✅ 2.1 small-cap quality gate — _latent gap: wired into `daily_picks` NOWHERE (the screener never consumes `gate_status`)._
- ⏳ 2.2 Financial sub-model (158 Banks+NBFCs, Screener-sourced, [ADR 0030](../decisions/0030-banking-metrics-screener-first.md)) — split into `financial_quality`(SMALL) / `financial_recovery`(LARGE/MID) ([ADR 0032](../decisions/0032-tier-direction-flip-split-signal.md)); both WEAK (|t|<2) → benched, re-test ~Q1 FY27. NBFC GNPA gap parked (data-not-on-source).
- ⏳ 2.3 cyclical overlay · ⏳ 2.4 segment portfolio (↔3.3c) · 🚫 2.5 XGBoost overlay (needs ≥6mo PIT, ~2027, ↔3.3b).

**Track 3 — Factor model** ([plan 0002](0002-100-factors-and-model.md)) — **~47/50 PIT-shipped.** Production screener: **LARGE 6 / MID 9 / SMALL 11** factors, Σ|w|=1.0 each (see [signal-weights.md](../reference/signal-weights.md)).
- **3.1 data acquisition** — ✅ Screener Premium (2,119 stocks) · ✅ F&O OI+IV in-house (Black-76 inversion of `fno_bhav`, [ADR 0034](../decisions/0034-fno-oi-data-model.md)/[0035](../decisions/0035-fno-iv-derived-from-bhav.md)), backfilled 12mo · ⏳ 3.1c Kite scaffold (PENDING CREDS — blocks 3 intraday factors) · ✅ 3.1d transcripts+NLP (corpus 15,471 to 2016, look-ahead-safe).
- **3.2 factor build** (KEEPs wired; rest → `FACTOR_LIBRARY`):
   - ✅ §3.2.1 forensic/capital-allocation (11/15)
   - ✅ §3.2.2 options-implied (8/8) — `iv_skew_25d` MID KEEP → wired 0.13; OI four benched
   - ⏳ §3.2.3 microstructure (6/9) — `kyle_lambda` L/M KEEP (benched, cost-coupled); 3 intraday need Kite
   - ✅ **§3.2.4 NLP/sentiment — BUILT + BACKTESTED 2026-06-14, none wired** ([signals/nlp_factors.py](../../signals/nlp_factors.py) + `pit_nlp_factors`, fully registered, 46 monthly anchors, look-ahead-safe on `available_date`). Verdicts: **#37 `uncertainty_word_density` LARGE t=+2.90 KEEP but CONTRARIAN sign** (more hedging→higher returns, backwards from theory) + LARGE-only/one-regime → PARKED, not wired; **#36 `forward_looking_intensity` LARGE +1.67 / SMALL +1.94 WEAK** (sensible + sign, sub-2.5); **#34 `earnings_call_tone_qoq` DROP all** (tone-momentum didn't replicate). All 3 → `FACTOR_LIBRARY`. News sentiment daily-live (`sentiment_scores` 121K); `sentiment_7d` benched (thin n); `regulatory_sector_signal` #35 live.
   - ⏳ §3.2.5 PEAD (4/6) — core didn't replicate (needs consensus-EPS surprise); only `corporate_action_density` LARGE KEEP (benched, mechanism unclear)
   - ✅ §3.2.6 industry_id (control) · ✅ §3.2.7 macro betas (6, all benched; gate PROMOTEs gold/metals @126d, n thin)
   - ⏳ BSE event factors — `governance_resignation` wired (Next-3 #1c); credit-rating pending (#1e)
- **3.3 model upgrade** — **GATED on 3.2 completion** (the ~100-factor library + monthly-anchor depth needed for orthogonalization). Per the plan 0002 roadmap this is the **Week 13-24+ / Month 7+ phase — not started as a formal phase yet.** Current status:
   - ⏳ 3.3a IC-stability weighting — net-of-cost **promotion gate** shipped ([ADR 0038](../decisions/0038-horizon-resolved-promotion-gate.md), `factor_horizon_gate`); deliberate weight reviews run manually each session off the gate × v1-history. Full IC-weighted/orthogonalized model = future.
   - ✅ 3.3a' **multiple-testing correction (2026-06-14, [ADR 0043](../decisions/0043-multiple-testing-aware-factor-significance.md))** — [tools/multiple_testing.py](../../tools/multiple_testing.py) HLZ haircut over **269 (signal,tier) hypotheses**: Bonferroni bar **|t|≈4.2**, only **8 survive BY-FDR**. Robust core = `pt_upside`/`pledge_quality`/`delivery_anomaly_z`; borderline = governance/iv_skew/sector_tilt; the rest lean on diversification/v1-history (not unwired — evidence only). Retroactively confirms parking `uncertainty_word_density` + thin-n KEEPs. Run in every promotion review alongside the horizon gate.
   - ✅ 3.3b orthogonalization (↔2.5) — **marginal-contribution diagnostic, HORIZON-AWARE (2026-06-14)** [tools/factor_marginal.py](../../tools/factor_marginal.py), sequential rank-IC Fama-MacBeth on WIRED factors at {20,63,126,252}d (NW-corrected, 46 monthly anchors). **Step 1 (20d) flagged `book_to_price`/`accruals` redundant; step 2 (horizon sweep) showed that was a HORIZON ARTIFACT** — they're slow value factors that earn their weight at 63-252d (`book_to_price` SMALL incr_t −3.9@20d → **+13.3@252d**). **Verdict: NO trims** — the model diversifies across horizons (fast forensic/microstructure `governance`/`delivery` peak @20d + slow value/analyst `book_to_price`/`accruals`/`pt_upside` peak @252d), weights broadly matched to natural horizons. Only genuine flag: `consensus` MID weak at ALL horizons (held on v1 → MID re-judge, Next-3 #3). Evidence only, no weight changed; [signal-weights.md](../reference/signal-weights.md). **Methodology win: judging marginal IC at 20d alone under-credits slow factors.** _(Caught + corrected: weekly/monthly mixing, OLS sign-flips → partial-corr, imputation distortion, NW overlap.)_ **Next (3.3b-3):** within-group orthogonalization. · 💤 3.3c mean-variance portfolio (↔2.4) · 💤 3.3d Barra-style risk model.
   - _`SIGNAL_WEIGHTS_RETURN`/`SHARPE` variants shipped but not the production default._

## Side plans
- ✅ [0005](0005-data-confidence-to-95.md) Data confidence 75→95 (~93/100; per-stock lineage wave 1 done, wave 2 = remaining ~31 signal modules).
- ✅ [0006](0006-sector-dossiers.md) Sector dossiers (A-E) · ✅ [0007](0007-trust-pipeline-uhs.md) Trust pipeline + UHS (7 gates, per-pick UHS; honest ceiling 95/100).
- ✅ MF research section · ✅ Ops cockpit split (:3001) · ✅ DuckDB read-replica ([ADR 0031](../decisions/0031-duckdb-read-replica.md)) · ✅ offsite DB backup (nightly VACUUM→gzip→Drive).
  - ✅ **MF NAV-splice fix (2026-06-14)** — `mf_nav_history` carried scale artifacts (early segment stored ÷10/÷100, or leading near-zero) → a phantom 10×/100× NAV step that made any metric crossing it garbage (ICICI Overnight 5Y CAGR read +67% vs true ~5.6%). New `clean_nav_series()` ([signals/mf_metrics.py](../../signals/mf_metrics.py)) splices upward >1.5×/day artifacts (rescales the earlier segment, trusts the recent AMFI value), wired into both `compute()` and the chart ([cockpit/mf.py](../../cockpit/mf.py) `get_mf_nav_series`). 247 schemes had the artifact; full recompute → absurd (>50%) 5Y CAGRs 2→0, max 5Y now 30.2%; health green.
- ⏳ [0003](0003-market-share-momentum-factor.md) market-share momentum (proposed) · ⏳ [0004](0004-consumer-demand-pulse.md) consumer-demand pulse (research-gated).
- ⏳ **[0008](0008-multibagger-model.md) Multibagger model** — SEPARATE screen (OUT of `daily_picks`). SELECTION confirmed dead (regime-dominated, [ADR 0039](../decisions/0039-multibagger-funnel-regime-dominated.md)) → reframed to **HOLDING**: junk-stripped 19-name watchlist + HOLD/WATCH/REVIEW conviction monitor on `/multibagger` ([ADR 0040](../decisions/0040-multibagger-holding-not-selection.md)). Validation-stage.

## Recently shipped (done-log — full detail in `git log`)
- **2026-06-14:** governance_resignation wired MID −0.08; transcript look-ahead fix; credit-rating feasibility probe.
- **2026-06-09:** BSE scrip→sid crosswalk; DLM managerial-ability + financial-mgmt cockpit lens; gate-6 UHS fix; crypto decoupled to own repo.
- **2026-06-08:** BSE event-stream harvester; rate/credit betas (benched); transcript corpus 3.4K→15.5K + `nlp_scores`.
- **2026-06-05:** `sector_tilt` wired SMALL-only ([ADR 0041](../decisions/0041-sector-tilt-backtest-gated-small-only.md)).
- **2026-06-04:** REXP revenue-plausibility hard exclusion; multibagger bear-hardening + watchlist 35→19.
- **2026-06-03:** multibagger regime finding ([ADR 0039](../decisions/0039-multibagger-funnel-regime-dominated.md)); horizon-gate weight review; monthly-snapshot cron fix.
- **2026-06-02:** net-of-cost promotion gate ([ADR 0038](../decisions/0038-horizon-resolved-promotion-gate.md)); industry_id + macro betas.
- **2026-06-01:** IC-decay diagnostic ([ADR 0036](../decisions/0036-horizon-resolved-factor-evaluation.md)); pick_outcomes trading-day windows; /system false-CRITICAL fix.
- **2026-05-31:** promotion wave (pt_upside/pledge/delivery → production); §3.2.2-5 factor builds; offsite backup.
- **2026-05-29→30:** walk-forward OOS (SMALL validated, LARGE/MID ~zero); financial-signal split; DuckDB replica; trust pipeline.

## Open questions
- `pt_upside` |t|=7-9 — real alpha or PIT artifact? Re-test after ≥3 monthly snapshots (~2026-08).
- credit-rating direction — worth a PDF/text-extraction layer to recover the buried downgrades (the valuable half)?
- 2.3 commodity-data gaps — skip cement/steel until manual curation?
- insider/regulatory/macro signal weights — tertiary 0.2× for the first two, zero for macro?

## Roadmap-shaping decisions (recent; full set in `docs/decisions/`)
- [0043](../decisions/0043-multiple-testing-aware-factor-significance.md) multiple-testing haircut (HLZ) — |t|≥2.5 necessary-not-sufficient; robust core = pt_upside/pledge/delivery; evidence-only.
- [0042](../decisions/0042-data-acquisition-build-not-buy.md) data is build-not-buy — BSE event stream keystone, 2018 history floor.
- [0040](../decisions/0040-multibagger-holding-not-selection.md) multibagger = HOLDING not selection · [0039](../decisions/0039-multibagger-funnel-regime-dominated.md) regime-dominated.
- [0038](../decisions/0038-horizon-resolved-promotion-gate.md) net-of-cost promotion gate · [0036](../decisions/0036-horizon-resolved-factor-evaluation.md) factors have heterogeneous horizons.
- [0035](../decisions/0035-fno-iv-derived-from-bhav.md) F&O IV derived in-house · [0034](../decisions/0034-fno-oi-data-model.md) F&O OI data model.
- [0032](../decisions/0032-tier-direction-flip-split-signal.md) split a factor when its IC sign flips across tiers · [0030](../decisions/0030-banking-metrics-screener-first.md) banking metrics = Screener-first.
- [0027](../decisions/0027-per-stock-data-lineage.md) per-stock lineage · [0017](../decisions/0017-factor-library-two-tier-registry.md) two-tier factor registry (`BACKTEST_SIGNALS` + `FACTOR_LIBRARY`).
- _(0009-0026 — tracks/tiers/PT-model/UHS/observability/eligibility foundations — see `docs/decisions/`.)_
