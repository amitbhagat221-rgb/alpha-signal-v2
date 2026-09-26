# Honest Return Prediction + Signal-Generation Audit — 2026-07-05

Executed per [return-prediction-and-signal-audit-prompt.md](../_archive/return-prediction-and-signal-audit-prompt.md).
Grounded in the CLEAN post-ADR-0047 panel (`pit_ic_by_tier_v2` `v2_recompute` rows), the
2026-07-04 audit, the 2026-07-05 re-baseline, ADRs 0043/0045/0047/0049/0050, and a fresh
`tools/rebalance_sim.py` run. New tool: [tools/expected_return.py](../../tools/expected_return.py)
(prediction logged to `data/expected_return_predictions.jsonl`, scoreable against realized in 2027-07).

---

## Task 1 — Honest expected 1Y return

**E[1Y] = +11.1% IF operated at monthly cadence · −10.1% AS CURRENTLY OPERATED.**
Scenario CI (bear→bull beta, monthly costs): **[−21.5%, +35.7%]**.

| Component | %/yr | Source |
|---|---|---|
| **Beta** (36% LARGE / 38% MID / 26% SMALL × 11/12/12.5% tier assumptions) | **+11.8** | long-run Indian equity: ~6-7% real + ~4.5% CPI; NOT a forecast of next year |
| **Alpha, gross** (clean IC × dispersion × selection × OOS shrink) | **+2.6** | unshrunk in-sample would be +8.4; shrink = walk-forward OOS (SMALL 0.5, LARGE/MID 0.25) |
| — LARGE +1.7%/yr standalone (book contrib +0.6) | | composite IC .032, σ .085, z̄ 2.0 |
| — MID +2.5%/yr standalone (contrib +1.0) | | composite IC .047 (in-sample-rich, hence 0.25 shrink) |
| — SMALL +4.1%/yr standalone (contrib +1.1) | | composite IC .027, σ .118 — the only walk-forward-validated tier |
| **Costs, as operated** (banded, 6.2%/day one-way, measured) | **−24.5** | rebalance_sim 61d: gross +30.3% ann → net +2.0%, net Sharpe +0.11 |
| **Costs, monthly cadence** (~20%/mo one-way, 69bps/side book-weighted) | **−3.3** | prospective; requires the EMA-smoothing / cadence change |

Three things the cockpit's "Expected 1Y = 11%" hides:
1. It's analyst-PT upside (`cockpit/api.py:1525`), not a return model. That it lands near the
   honest monthly-mode number is **coincidence** — PTs are +12-25% optimistic and PT-upside was
   *pulled from the model* as a look-ahead artifact (ADR 0045).
2. **~90% of the honest expected return is market beta.** The factor model, fully believed,
   moves the needle ~2.6pp/yr net of nothing; after costs it must first pay a toll.
3. **The book as currently operated has a NEGATIVE expected return.** 6.2%/day one-way turnover
   × the system's own cost assumptions = −24.5%/yr — 9× the entire gross alpha. Every
   conversation about factors is second-order until this is fixed.

Gap to 25% (monthly mode): **13.9pp**. Alpha at 1.5× its estimate closes ~1.3pp of it; the other
~12.6pp is "the market must rise" — the tier-blend must return ~26% for the book to hit 25%.

## Task 2 — Is 25% achievable, and by what lever

Ranked by how much of the gap each lever honestly closes:

1. **Turnover (not on his list, but it's the biggest number in the system): +21pp/yr.**
   Banded-daily → monthly cadence takes the cost line from −24.5 to −3.3. This is 8× the total
   gross alpha of every wired factor combined. Next lever per HANDOFF: EMA-smooth `final_score`.
2. **Market/beta: the only path to 25% in one year.** Required tier-blend market return ≈ 26%.
   Indian small/mid bull years (2014, 2017, 2021, 2023) clear this; a flat year cannot be
   factor-ed around: with zero market return the honest ceiling is alpha − costs ≈ **−1 to +3%**.
   25% is a *bull-year outcome*, not a model property. Base-rate honesty: roughly 1 year in 3.
3. **Tier tilt to SMALL: small, costly.** 100% SMALL ⇒ beta 12.5 + alpha 4.1 − costs ~7.2 (150bps
   side at monthly cadence) ≈ **+9.4%** — *lower* than the blended book, because SMALL's cost
   assumption eats its alpha edge; and smallcap drawdowns are −35% (2018-19) to −60% (2008).
   A *moderate* tilt (e.g. 40% SMALL) adds ~+0.3-0.5pp E[return] for ~+2pp vol. Not a lever, a trim.
4. **Leverage: doesn't work at retail funding.** MTF/futures funding ~9-12% ≥ the 11.8% beta it
   levers; 1.5× ≈ +12-13% E[return] with 1.5× drawdown. Uncompensated risk — flagged.
5. **Concentration (15→8 names): noise, not return.** Rank IC ~0.03 doesn't localize skill in the
   top 8 vs top 15; adds idio vol with no reliable E[return] gain.
6. **Alpha: single digits, ever.** Realistic ceiling for validated free-data long-only Indian
   factor alpha: **+3-6pp/yr net** (vs +2.6 today) after every candidate below ships and works.
   Alpha alone can NEVER close a 13.9pp gap. Any plan that claims it will is the pt_upside
   mistake with better branding.

**Blunt summary: the market does the work.** The honest pitch for this book is "market return
+2-4pp with a validated SMALL edge, at controlled risk" — i.e. ~14-16% in an average year once
costs are fixed — not 25%.

## Task 3 — Missing-factor gap analysis

Status map (canonical families → this fund). Confirmed dead ends honored (SUE-PEAD, NLP
transcripts, credit_beta, forecast_history PT — not re-proposed).

| Family | Status here |
|---|---|
| Momentum 12-1 (Jegadeesh-Titman) | BUILT (`mom_6m_adj`), failed clean bar (S 1.34), dropped ADR 0049 |
| **Residual/idio momentum** (Blitz-Huij-Martens) | **ABSENT** → card below |
| Low-vol/BAB (Frazzini-Pedersen, Ang et al.) | BUILT 2026-07-05, contrarian sign in bull-only window, parked with re-read trigger (drawdown regime) |
| Short-term reversal (Jegadeesh 1990) | BUILT, sub-bar; weekly-cadence retest queued (structurally handicapped at monthly) |
| Profitability (Novy-Marx GP) | BUILT, **negative sign in India panel** — transfer risk is real, parked |
| Quality composite (QMJ) | PARTIAL (piotroski wired) → card below, high bar |
| Investment/asset growth (CMA, Cooper-Gulen-Schill) | BUILT, correct sign, insignificant (−0.9), library |
| Accruals (Sloan) | BUILT + WIRED (MID −2.65) |
| PEAD | WIRED as announcement_car (ADR 0050); consensus-SUE permanently blocked (no PIT consensus EPS) |
| **Analyst revisions** | **VALIDATED, NOT WIRED** (`eps_revision_yoy` S t=2.78 clean) → card |
| **Value composite** | **VALIDATED, NOT WIRED** (S t=3.32 clean) → card |
| **MAX/lottery** (Bali-Cakici-Whitelaw) | **ABSENT** → card |
| Seasonality/turn-of-month (Heston-Sadka) | ABSENT → card (empirical-leaning, high bar) |
| F&O positioning (OI/PCR/max-pain) | BUILT, library, never cleared 1.5; weekly retest candidate |
| Liquidity (Amihud/Kyle) | BUILT, benched for cause (cost-coupled, ρ=−0.73 with ADTV) — stays benched |
| India structural: delivery microstructure, pledge, governance events | WIRED (the fund's real edge) → "more juice" card |

### Build-candidate cards (ABSENT / unwired only)

**1. `eps_revision_yoy` producer (wire the validated factor)** — Evidence: **BOTH**
(analyst-revision drift: Chan-Jegadeesh-Lakonishok 1996, Womack 1996 lineage; validated
*in-house on clean Indian data*, SMALL t=2.78, n=38). Story: **behavioral** — investors
underreact to analyst estimate changes; persists in Indian small-caps because coverage is thin
and slow to propagate. India evidence: it IS the India evidence — own panel. Net alpha:
+0.5-1pp book-level. Data: in-house. Effort: **LOW** (extend `scoring/screener.py::_load_signals`,
the exact ADR-0050 inline-producer pattern; already Scope B). Orthogonality: analyst dim
currently carried only by consensus — check ρ before sizing.

**2. `value_composite` wiring** — Evidence: **BOTH** (value: FF 1992 + massive replication;
in-house clean SMALL t=3.32 vs book_to_price alone 1.88). Story: **risk-premium** (distress/
duration risk compensation) with a behavioral extrapolation kicker; persists because it hurts
to hold. India: own panel + value robust in EM broadly. Net alpha: +0.3-0.8pp (partly replaces
book_to_price — ADR 0049 rule 4: one value rep, swap not stack). Data: in-house. Effort: **LOW**
(same Scope B producer). Risk: redundancy with wired b2p — decide swap vs skip on ρ.

**3. Residual momentum 12-1** — Evidence: **ACADEMIC** (Jegadeesh-Titman 1993; residual variant
Blitz-Huij-Martens 2011 — same premium, ~half the crash risk; momentum replicates strongly in
Indian equities across multiple studies). Story: **behavioral** — underreaction/anchoring;
persists via limits-to-arbitrage in a retail-heavy, coverage-thin market. India: generic
momentum well-replicated; *residual* variant is a US/EU import — flag transfer risk. Honest
note: plain momentum FAILED the clean bar here (S 1.34) — this is a *designed* retest
(strip market/sector beta from the return before ranking), not a re-roll of the same test.
Net alpha: +1-2pp if it works (momentum is the largest premium absent from the book). Data:
in-house (prices 2020+, beta infra exists). Effort: **MED** (PIT helper + rolling residual
regression). Orthogonal: nothing momentum-shaped is wired.

**4. MAX / lottery-stock avoidance** — Evidence: **ACADEMIC** (Bali-Cakici-Whitelaw 2011,
replicated in EM). Story: **behavioral** — retail lottery preference overprices extreme-daily-
return names; India's options/smallcap retail boom is the *ideal* habitat; persists because the
clientele doesn't optimize. Long-only capture is exclusion-shaped (avoid the overpriced tail),
like governance_resignation's negative weight. Net alpha: +0.3-0.8pp, SMALL-concentrated. Data:
in-house (daily prices). Effort: **LOW**. Orthogonal to everything wired.

**5. QMJ correct-sign quality composite** — Evidence: **ACADEMIC** (Asness-Frazzini-Pedersen)
BUT in-house evidence is *hostile* (gross_profitability negative all tiers, roic negative —
bull-regime junk rally). Story: risk-premium/behavioral hybrid. **Demand the elevated
EMPIRICAL-tier t-bar** despite the pedigree — the India transfer visibly fails in this sample.
Effort MED. Build only after a drawdown regime enters the panel (same trigger as low-vol).

**6. Turn-of-month / cross-sectional seasonality** — Evidence: **EMPIRICAL-leaning** (TOM +
Heston-Sadka have journal homes but fragile OOS records). Story: **structural** (institutional
flow timing) — plausible but thin. High t-bar, tiny capacity, interacts with rebalance timing
more than stock selection. Effort LOW. Queue tail.

**7. More India-structural juice (pledge/SAST detail extraction)** — Evidence: **EMPIRICAL**
(own discovery class — the delivery/pledge/governance family is the fund's only BY-FDR-grade
alpha). Story: **structural** — disclosure frictions + retail inattention in an under-arbitraged
segment; the *strongest persistence argument in the whole queue* (no US fund is arbitraging BSE
pledge filings). The SAST-buried pledge detail and PDF-locked credit-rating downgrades are the
known unmined seams. Effort: **HIGH** (PDF/XML extraction). Net alpha: unknowable ex-ante, but
this family produced delivery_anomaly_z (t=7.78) — the best expected-value-per-hypothesis soil
the fund has. Deferred cost is real; don't let it fall off the map.

### Ranked queue

**Strong story + pedigree, build with confidence:** 1) eps_revision_yoy (shovel-ready),
2) value_composite (shovel-ready), 3) residual momentum (shovel-ready), 4) MAX/lottery.
**Empirical-only / hostile-transfer, demand a high bar:** 5) QMJ (wait for regime),
6) seasonality, 7) SAST/pledge extraction (high effort, best persistence story — schedule, don't improvise).

## Task 4 — Scores

**Idea generation: 82/100.** 277 deduped hypotheses tested against a PIT archive; two original
data unlocks a paid shop would envy (BSE event firehose to 2018, survivorship-free universe via
bhavcopy); IV surface inverted in-house from settle prices; and — rarest — the discipline ran
*against* its own book twice in one week (pt_upside pulled, pledge_quality demoted, weights
re-derived on deflated numbers). Held back from 90+ by process debt the audit surfaced: the
survivors-only backtest panel, 38 signals in registry limbo, no scheduled backtest refresh, and
the fact that two contamination classes (forecast_history, late-anchor returns) shipped before
being caught.

**Signal generation: 55/100.** The owner's suspicion is correct. Validated, multiple-testing-
robust alpha = **one factor, one tier** (delivery_anomaly_z SMALL, t=7.78); the diversifier band
(consensus/sector_tilt/CAR SMALL, t≈3.7) is real but haircut-failing; LARGE's best is t=2.23
after three consecutive canonical factors failed; walk-forward says LARGE/MID OOS ≈ 0. Gross
book alpha ≈ 2.6pp/yr shrunk — and the measured book, at its own cost assumptions, nets
+2.0%/yr against a +30.3% gross tape (net Sharpe +0.11). That is rubric-band "40-59: thin /
mostly beta", scored at the top of the band because the SMALL edge is genuine and the sign
discipline (no wrong-sign wiring) protects what exists. **Why:** free public Indian data has
no consensus-EPS history, no intraday, no borrow — the alpha-bearing seams (microstructure,
disclosures) are exactly where the fund already dug. **Ceiling** for this universe/data/
long-only: net alpha +3-6pp/yr ⇒ signal-gen ceiling ≈ 70-75 even executed perfectly.

**The gap (82 vs 55) is the finding:** a research process two bands better than its product.
That is the *right* asymmetry early — the process is the compounding asset — but it also means
the marginal hour now goes further in *execution* (cost cadence, wiring validated factors) than
in *discovery*.

## Final synthesis

1. **The one honest sentence:** this book's expected 1Y return is **~+11%** (of which ~+11.8pp
   market beta, ~+2.6pp factor alpha, −3.3pp costs at monthly cadence) — and **−10% as currently
   operated** (−24.5pp cost drag); 25% requires a ~26% tier-blend market year, which no
   achievable amount of factor work substitutes for.
2. **Single highest-leverage move:** cut turnover to the signals' natural monthly horizon
   (EMA-smooth `final_score` / widen bands): worth **+21pp/yr**, ~8× the entire gross alpha of
   the factor model. It is not a factor, which is exactly why it's been under-prioritized.
3. **Scores:** idea-gen **82**, signal-gen **55** — great lab, thin product; protect the lab,
   fix the plumbing.
4. **Build queue headline:**
   - `eps_revision_yoy` — BOTH, behavioral: thin-coverage underreaction to estimate changes;
     +0.5-1pp net; data in-house (validated t=2.78); effort LOW.
   - `value_composite` — BOTH, risk-premium: distress compensation, swap for book_to_price;
     +0.3-0.8pp net; data in-house (validated t=3.32); effort LOW.
   - `residual_momentum_12_1` — ACADEMIC, behavioral: underreaction with beta-crash stripped;
     +1-2pp net if India transfer holds; data in-house; effort MED.
5. **Could not verify / do not soften:** beta assumptions are assumptions (the CI is the honest
   output, the point estimate is not a promise); the alpha estimate inherits the survivors-only
   panel (audit Data-F1 — true ICs likely *lower*); cost bps (30/50/150) are unvalidated against
   real fills — if SMALL's true all-in cost is half the assumption, monthly-mode E[1Y] rises
   ~+1pp, and if it's double, SMALL's alpha edge nets to ~zero; the +0.11 net Sharpe is 61
   in-sample days. **25% from alpha is not realistic for this universe — ever.** Realistic:
   market + 2-4pp net with the SMALL edge and fixed cadence, i.e. ~13-16% in an average year,
   ~30%+ in a bull year, negative in a bear year — long-only means owning that honestly.
