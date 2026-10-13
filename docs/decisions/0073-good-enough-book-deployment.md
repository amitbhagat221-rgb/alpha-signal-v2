# ADR 0073 — Deploy a book on "good enough" evidence, sized to the evidence

**Status:** accepted 2026-10-13 (Amit: "the tests are too punitive … idea is to have something good enough with well and calculated risk taking"; "agreed with the ADR"). Covers **deploying a book** only; factor wiring stays under [ADR 0043](0043-multiple-testing-aware-factor-significance.md) / [0063](0063-weights-on-corrected-evidence.md) until a separate decision.
**Evidence:** [slow-core-tactical-2026-10.md](../studies/slow-core-tactical-2026-10.md), [long-horizon-2026-10.md](../studies/long-horizon-2026-10.md), [research 0007](../research/0007-long-horizon-findings.md).

## Decision

A book (a rule that turns a score into holdings) is graded on its after-cost, after-tax excess over its tier index. The grade sets its size and its exits. A strict-bar failure is no longer an automatic "index only".

| grade | evidence (all required) | size |
|---|---|---|
| **A, strong** | t ≥ 2.0 after the variant haircut; DSR ≥ 0.95; PBO ≤ 0.20 | full sleeve |
| **B, good enough** | t ≥ 1.5; DSR ≥ 0.90 or PBO ≤ 0.30; beats the index in ≥ 3 of 5 calendar years **and** in ≥ 10 of 12 staggered start months; worst 12-month excess ≥ −15 % | limited sleeve |
| **C** | anything less | research only; the tier stays the index |

- **Planning return** = half the back-tested excess (backtests shrink live: research 0007, NSE factor indices after launch).
- **Book shape:** at least 20 names. Top-10 books swung up to 30 points between start months.
- **Starting allocation** (₹30–40 L): 40 % NIFTY 50 index, 30 % NIFTY MIDCAP 150 index, 30 % SMALL sleeve. The sleeve is 50 % slow book and 50 % tactical book, each grade B, 20 names, reviewed monthly.
- **Kill switch:** pause the sleeve and review if it trails its index by 15 % over any 12 months, or by 20 % from its high-water mark.
- **Review at 12 months:** at or above the planning return → may size up. Below zero → back to the index.
- **Starts as a paper book**, on a worktree branch. Real money only after Amit approves.

## Why

- Under the strict bar every book "failed" (plan 0024, plan 0025), yet SMALL books beat the Smallcap 250 after costs and tax from every one of 12 start months:
  - the tactical `fast_select` book: median +11.2 %/yr;
  - `slow_v2` top 20: median +9.3 %/yr;
  - 50/50 slow + tactical: median +8.1 %/yr, t 2.0, correlation ≈ 0.
- Proving a book of this strength takes ~4–5 years forward (MinTRL). A proof-only rule means never deploying.
- The cost of being wrong is capped by size, the kill switch and the halved planning return, not by refusing to act.

## Today's grades (2026-10-13)

- **SMALL:** slow book (`slow_v2` or `slow_select`, top 20) → **B**. Tactical `fast_select` top 20 → **B** (t 1.64, DSR 0.955, PBO 0.10, 12/12 starts).
- **MID:** `slow_v2` top 20 → **C** (12/12 starts but t 1.0). Tactical → **C** (0/12).
- **LARGE → C.**

## What this does not claim

- Grade B is not proof. Some grade-B books will be luck; the size and kill switch exist for that.
- Every figure is in-sample selection over 2019–26 on today's listed universe (survivorship ~2.8 %/yr in SMALL).
- It does not change live weights, the screener or `daily_picks`.
