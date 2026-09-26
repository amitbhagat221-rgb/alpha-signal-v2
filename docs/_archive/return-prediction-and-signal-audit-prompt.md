# Prompt — Honest Return Prediction + Signal-Generation Audit (for Fable-5)

> Paste into a fresh session on the alpha-signal-v2 repo. Read-only analysis + a small
> predictor build. Written 2026-07-05 after the honest-model overhaul.

---

## Role & stance
You are a skeptical quant PM doing due diligence on a one-person systematic **long-only** Indian
equity fund (`~/alpha-signal-v2`). The owner wants a **25%+ annual return** and is frustrated the
cockpit "Expected 1Y" stat fell from 28% to 11%. Your job is to tell him the **truth**, not the
number he wants. Three hard rules, non-negotiable:

1. **Never reverse-engineer factors to a target return.** Do NOT propose "add factors until
   predicted return = 25%." That is the exact overfitting that produced this fund's biggest
   past bug (`pt_upside`, a look-ahead artifact — see `docs/decisions/0045`, `0047`). Predict
   honestly first; improvement comes second and separately.
2. **Decompose every return number into BETA (market exposure) vs ALPHA (factor tilt).** This is
   long-only, so most of the return is the market. Never quote a blended number without the split.
3. **The cockpit "Expected 1Y" (11%) is analyst price-target upside, NOT a return forecast**
   (`cockpit/api.py:1525`). Sell-side PTs run structurally +12–25% optimistic. Do not treat it as
   the model's expected return. Building a *real* expected-return model is Task 1.

Ground everything in the CLEAN, re-baselined evidence (post-`ADR 0047` anchor-proximity fix).
Read first: `docs/_archive/audit-2026-07-04-report.md`, `docs/studies/rebaseline-2026-07-05.md`,
`docs/decisions/0043,0045,0047,0049,0050`, `docs/reference/signal-weights.md`,
`config.SIGNAL_WEIGHTS`, `pit_ic_by_tier_v2` (use `source LIKE 'v2_recompute%'` — the clean rows).

Current honest state you're auditing: 1 robust factor (`delivery_anomaly_z` SMALL, t=7.78, sole
BY-FDR survivor) + correct-sign diversifiers; `announcement_car` just wired (LARGE 2.23 / SMALL
3.74); LARGE thin; banded book net Sharpe +0.11 (in-sample 61d). ~14 wired signals, ~1–2 robust.

---

## Task 1 — Honest expected-return model (the thing that actually answers his question)
Build a small, **validatable** predictor of the current book's forward return and write it to
`tools/expected_return.py` (read-only over prices/IC; writes nothing to prod tables).

Decompose expected 1Y return into:
- **Beta component:** the book's net long equity exposure × an honest Indian-equity forward
  return assumption. Do NOT invent a bullish number — use a defensible range (e.g. long-run
  Nifty/​small-cap real+inflation, and state it). This is where ~most of any 25% lives.
- **Alpha component:** from the wired factors' **clean out-of-sample IC** × the book's factor
  exposures × cross-sectional dispersion → expected active return, **net of** the measured
  turnover cost (banded ~6.2%/day one-way → annualized drag; use `tools/rebalance_sim.py`
  numbers). Be explicit that net-of-cost factor alpha here is currently thin (~low single digits).
- **Confidence interval**, and a **decomposition table** (beta pts vs alpha pts vs cost drag).

Deliverable: "Honest expected 1Y = X% (Y from beta, Z from alpha, −C costs), CI [..]." Make it
**trackable against realized** (store the prediction + date so future actuals validate it). State
plainly how far this is from 25% and **what fraction of the gap is 'market must rise' vs 'we need
more alpha'.**

## Task 2 — Is 25% achievable, and by what lever (honestly)?
Given Task 1, decompose what reaching 25% actually requires, ranked by honesty/feasibility:
- **Beta/market:** in a strong Indian small-cap year the book clears 25% on beta alone; in a flat
  year it can't, at any factor quality. Quantify the market-return level implied.
- **Leverage / concentration / tier-tilt:** tilting harder to SMALL (the only tier with edge) or
  concentrating raises *both* expected return and risk — quantify the vol/drawdown cost.
- **Alpha:** realistically how many extra points can *validated* factors add (single digits).
Be blunt about which of these is doing the work. Flag any path that only hits 25% by taking
uncompensated risk or by overfitting.

## Task 3 — Missing-factor gap analysis ("what should be there and isn't")
Systematic scan: list the **known-profitable factor families** a serious equity quant shop runs,
mark which are BUILT / BENCHED / ABSENT here, and for each ABSENT one produce a **build-candidate
card** with ALL of the following (a candidate with no strong story does not make the queue — that
rule is the whole point of the fund's anti-data-mining discipline):

- **Evidence class — required, one of:**
  - `ACADEMIC` — published + independently replicated in the peer-reviewed asset-pricing
    literature (name the seminal paper(s): e.g. Frazzini-Pedersen BAB, Novy-Marx gross
    profitability, Cooper-Gulen-Schill asset growth, Jegadeesh-Titman momentum, Ang et al.
    idio-vol, Sloan accruals, HXZ/​q-factor, Fama-French investment/profitability). Highest prior.
  - `EMPIRICAL` — shows up in practitioner/backtest evidence but lacks a clean academic pedigree
    (data-mined or folklore). Lowest prior — must clear a HIGHER t-bar to be trusted (Bayesian:
    weak prior → needs stronger data), and say so.
  - `BOTH` — academically grounded AND empirically robust in Indian data specifically. Best.
- **Economic STORY — required, ≤2 sentences:** the causal mechanism, classified as
  **risk-premium** (compensated risk), **behavioral** (a persistent investor bias), or
  **structural/institutional** (a friction/constraint — often the most durable in an
  under-arbitraged market like Indian small-caps). "It backtests well" is NOT a story and
  disqualifies the candidate. State why the premium should *persist* (why isn't it arbitraged away
  in Indian equities?).
- **India-specific evidence:** does it replicate in Indian equities (cite if known), or is it a
  US-large-cap result being imported on faith? Flag the transfer risk.
- Plus: expected net-of-cost alpha (honest, not wishful), **in-house data availability**, build
  effort, and orthogonality to the wired set.

Cover at least: low-vol/BAB, short-term reversal (both flagged for weekly retest), residual/
idiosyncratic momentum, quality-minus-junk (correct-sign, unlike the wrong-sign junk factors
excluded in ADR 0049), investment/asset-growth, profitability (Novy-Marx GP), analyst-revision
(`eps_revision_yoy` — validated t=2.78, not yet wired, needs a producer), F&O positioning,
seasonality/turn-of-month, and Indian-market-specific structural edges (promoter/pledge/delivery
microstructure, which this fund already exploits — argue whether there's more juice there).

**Rank the queue** by a combined score = (prior from evidence class × story strength) ×
(expected net alpha) ÷ (build effort), and separate the ranking into **"strong story + academic
pedigree, build with confidence"** vs **"empirical-only, build but demand a high t-bar."** Honor
the confirmed dead ends — do NOT re-propose them even if academically famous elsewhere: time-series
SUE PEAD, NLP transcript factors, credit_beta, forecast_history PT (see memory notes / ADRs 0043/
0045/0047). Output the ranked build queue with the top 3 flagged as shovel-ready.

## Task 4 — Re-audit & score IDEA GENERATION and SIGNAL GENERATION (1–100 each)
Two separate scores, each with a rubric and 3–5 sentence justification tied to evidence:
- **Idea generation** — the research *process*: factor sourcing, hypothesis breadth, data-edge
  discovery, use of the survivorship-free/event-stream unlocks, discipline (multiple-testing,
  PIT hygiene, honest re-baselining). (Likely strong — this is the fund's real asset.)
- **Signal generation** — the *actual validated alpha*: how much real, out-of-sample,
  net-of-cost, haircut-surviving edge exists. Be brutal: 1 robust factor + diversifiers, hollow
  LARGE, net Sharpe ~0. The owner suspects "we're poor here" — tell him if he's right, and *why*,
  and what the ceiling is for a free-data long-only Indian book.
Rubric: 90–100 institutional multi-factor edge; 75–89 several validated orthogonal factors;
60–74 one robust + sensible diversifiers; 40–59 thin/mostly beta; <40 no demonstrable edge.

---

## Final synthesis
1. The one honest sentence: "This book's expected 1Y return is ~X%, of which ~Y is market beta
   and ~Z is factor alpha; 25% requires [the specific thing]."
2. The single highest-leverage move toward a *sustainable* higher return (be honest if it's
   'accept more risk / more beta' rather than 'more factors').
3. Idea-gen score, signal-gen score, and the gap between them (great process, thin edge?).
4. **The build queue headline:** the top 3 shovel-ready missing factors, each as
   "`<name>` — [ACADEMIC/EMPIRICAL/BOTH], [risk-premium/behavioral/structural] story: <one line>,
   +~<n>% net alpha, data <in-house?>, effort <low/med/high>." Lead with the ones that have BOTH a
   strong economic story AND academic replication AND in-house data — those are the honest wins.
5. What you could not verify. Do not soften. If 25% from alpha is not realistic for this universe,
   say so — and say what IS realistic.
