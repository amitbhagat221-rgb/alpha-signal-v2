# ADR 0077: Multibagger desk adds deep-research verdicts to the ranking, and the thesis run gets a data gate

**Status:** accepted 2026-10-16.
- Amit: "lets do a heavy 100"; "recompute the 7 names … fix it at the source"; "bake in the qualitative finding into rankings … make those as candidates"; "reject on substantive orders".
- Amends [ADR 0075](0075-multibagger-thesis-replaces-quality-funnel.md) and [ADR 0076](0076-multibagger-desk-after-independent-critique.md); the thesis score itself is unchanged.
- Evidence: [research 0011](../research/0011-multibagger-deep-research-brief.md), `mb_research`, plan [0026](../plans/0026-multibagger-desk.md) stage 4b, plan [0027](../plans/0027-forensic-data-audit.md).

## Decision
- **Data gate inside the live thesis run** (`signals/multibagger.data_checks`, `MB_THESIS["data_checks"]`):
  - if the latest filed share count, adjusted for later splits and bonuses, is more than 1.3× ours, the market cap comes from the filing;
  - if the filing shows fewer shares → gate `shares`;
  - demerged within 450 days and the knowable annual predates the demerger → gate `demerger`;
  - after a recent demerger, or when results-table revenue differs from Screener sales by more than 1.25×, the quarter part is blanked.
- The gates are optional `thesis()` columns, so the backtest frames, which lack them, are unchanged.
- **Deep research per top-100 name.** An agent reads filings and the web against a database pack and returns:
  - a verdict: clean / flag / reject;
  - a 5x case: strong / plausible / weak.

  A high-severity flag means reject.
- **A regulator order is high only when it is substantive:** fraud, insider trading, diversion, misstatement, manipulation, or a market ban. Procedural fines are medium.
- **Research overlay** (`output/mb_research.overlay`, `MB_THESIS["research_overlay"]`):
  - research score = thesis score − flag points + 5x-case points;
  - per medium flag: 0.015 in integrity areas, 0.008 for business ones; low flags 0.005 / 0.003;
  - the penalty is capped at 0.15; a plausible 5x case adds 0.04;
  - a reject is out of the ranking;
  - its top 30 are the candidates.

  Borderline verdicts are marked for Amit's call (`BORDERLINE`).
- **Amit still picks the 10 held (D2 / D7).**

## Why
- 7 of the 2026-10-15 top 100, including #1 and #2, ranked on broken inputs: pre-demerger fundamentals and stale share counts. Only the agents reading filings caught them. 22 pond names had a wrong market cap.
- The thesis cannot see dishonesty, leakage, legal danger or a one-off quarter. The research found these in most names: 29 reject, 67 flag, 4 clean.
- The overlay is judgement, not a backtest. Keeping its points small and capped means the thesis order still dominates within a verdict class.

## Consequences
- **The forward check is pre-registered** (research 0011). In Oct 2028, compare:
  - rejected and flagged names vs clean ones, survivorship-free;
  - the overlay's top 30 vs the thesis top 30.

  If the research does not help by at least 5 points a year, cut it back to a light pass.
- The weekly re-rank brings in unresearched names, which keep their thesis score until researched (plan 0026 4b.2).
- The main model's `market_caps` uses the same stale vendor share count; the fix at the source is plan 0027 and needs Amit's OK.
- Sectors on the desk come from the research (`output/mb_sectors.py`), not the vendor tags, which were wrong for about 1 in 6 names.
