# Plan 0027 — Forensic data audit by research agents

Status: **proposed, not urgent** (Amit 2026-10-16: "plan note (future, not urgent): forensic data audit by deep research"). Owner: Amit. Linked to plan [0026](0026-multibagger-desk.md) stage 4b ([research 0011](../research/0011-multibagger-deep-research-brief.md)).

## Why
The stage-4b research agents read primary filings against our per-stock pack and found at least eleven classes of data error our checks missed:

1. **Pre-demerger fundamentals.** BHIL #1, VERAN #10 and DCM #82 were scored on the whole company before its demerger.
2. **Stale share counts.** IIAB #2 was 22× too small and AFI 10× too small; 22 pond stocks were affected.
3. **Stale annual data.** OMXA's annuals stopped at FY2015.
4. **Quarterly revenue counting one-off gains or other income.** THEM was 2.1×, plus SATI, HEST and KIRI.
5. **Partial holder lists.** 279 filings in 246 stocks made holders appear to "exit" and "re-enter".
6. **Wrong sector or industry tags**, which make the peer tables meaningless.
7. **Mis-tagged events.** Companies file regulator orders under "Award of Order", and prices are left unadjusted for some splits and bonuses.
8. **Annual profit inflated by one-offs.** Land-sale surplus (MUKA), a deferred-tax write-back (TNNP Rs 219 Cr) and exceptional gains (VSKI) feed the cheapness part through E/P.
9. **Pending merger into a parent.** BRLE and TPLP will become slices of their parent, so "small" and "cheap" no longer describe what a holder will own.
10. **Prices not adjusted for a bonus or split.** RSWM 2022, KOTY, REIN and HMA. Since 2025-07, 23 one-day falls of more than 40 % have no corporate adjustment within 5 days; 4 are pond stocks (GLOR, SADH, TAC, VMA). Some may be real crashes, so this needs a check, not an automatic gate.
11. **Event severity false positives.** MANBA's "auditor resignation" (marked high, and an exit flag) was a routine RBI-mandated tenure rotation. Read the resignation reason before marking it high.

Classes 1, 2 and 4 are now gated in the thesis run (`signals/multibagger.data_checks`, config `MB_THESIS["data_checks"]`). Every class was found by an agent reading a filing, never by a health check. A recurring audit would catch new classes before they reach a score.

## Design
- **Sample.** Each month, about 10–20 random stocks across tiers, stratified LARGE / MID / SMALL / MICRO / SME, plus a few from the live picks and the multibagger top 100.
- **The agent's job is not a verdict.** It checks each pack field against the primary filing: shares, market cap, last 4 quarters, last annual, promoter %, pledge, sector and industry, latest corporate action. For each field it records match, mismatch or could-not-check, with the source.
- **Output.** A `data_audit` table holding field, our value, filed value, source URL and error class.
- **From finding to check.** Each confirmed mismatch class becomes a deterministic health check (ADR 0060: it must be able to fail and has a fire drill). The agent finds a class once; code catches it from then on.
- **Measure.** Error rate per field per tier over time. The audit earns its keep while new classes keep appearing. If months pass with no new class, cut the sample.
- **Cost.** The verdict research ran at about 230–300k tokens and 5–12 minutes per stock. A field-check audit should cost roughly a third of that.

## Done when
- The `data_audit` table and its brief exist.
- The first monthly sample has run.
- Every class found has a health check, or an explicit "not worth a check" note.

## Fix at the source (agreed by Amit 2026-10-16)
The desk gates (classes 1, 2 and 4) protect only the multibagger thesis. These fixes reach the main model too:
- [ ] **Market caps from a stale vendor share count.** 22 pond names were affected (IIAB 22×, FIS 10.6×, AFI 10×). `signals/_fundamentals.market_caps` / `shares_and_book` set live tiers, the MICRO carve-out and `stocks.market_cap_cr`, so daily picks can be affected.
  - Cross-check against the latest filed `shareholding_categories.total_shares`, adjusted for later splits and bonuses.
  - Build it on a worktree branch and measure the change in picks; merge only on Amit's OK.
- [ ] **Industry tags.** The vendor tags were wrong for about 1 in 6 researched names. They feed the thesis "industry momentum" part and every peer table.
  - Add NSE's four-level industry classification as a feed (`feeds.FEEDS` entry, canary on 3 stocks).
  - Until then, the desk shows research sectors (`output/mb_sectors.py`).
- [ ] **Gates or checks for the rest:**
  - stale annuals (OMXA, KAMI, ADVAN);
  - annual profit inflated by one-offs (other income or a tax credit as a large share of profit; feeds E/P);
  - pending mergers into a parent (scheme filings);
  - price falls of more than 40 % with no corporate adjustment;
  - event severity (read the auditor-resignation reason; "order win" text needs the PDF, plan 0026 4.4).
- [ ] **Partial holder lists in other consumers.** The fix is in `output/mb_deepdive` and `signals/mb_watch`. Check whether smart-money and promoter signals compare consecutive holder lists the same way.

## To-do
- [ ] Brief for the field-check agent (reuse `output/mb_research.pack`; one row per field).
- [ ] `data_audit` table (`schema.sql` and `tables.TABLES`), plus a loader with validation.
- [ ] A health check for each class found so far that is not yet gated: stale annuals, partial holder lists, industry tags, unadjusted splits.
- [ ] Monthly sampler and cron (`run.sh`), only after Amit agrees the cost.
