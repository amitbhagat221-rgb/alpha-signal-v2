# Demerger parent-drift study (plan 0013 B1)

Read-only. Research 0003 cites 221 BSE spin-offs 2003-2020 → parent CAAR +2.64% at
[+1,+5]. This tests whether our in-house event set (survivorship-safe by
construction — the parent/announcer stays listed through a demerger) reproduces a
positive parent drift, using `tools/event_study.py` (plan 0013 A1) over
`event_calendar` (plan 0013 A3).

**Events:** `event_calendar` where `event_type='demerger'`, day0 = `announce_date`
(first `bse_announcements` filing whose `subcategory` is Scheme of Arrangement /
Amalgamation-Merger-Demerger AND whose headline matches demerger/de-merger/demerge).
Tradeable leg = the **parent** (the listed announcer) — no survivorship adjustment
needed, that name never delists on a demerger.

## Drift curve (market-adjusted CAR vs NIFTY-50, as of 2026-07-11)

| window | n | mean CAR | std | t-stat | median | hit-rate |
| --- | --- | --- | --- | --- | --- | --- |
| [-1,+1] | 81 | +0.82% | 6.27% | 1.18 | +0.16% | 53.1% |
| [0,+5] | 110 | +0.91% | 7.91% | 1.21 | +0.24% | 52.7% |
| [0,+20] | 109 | -0.89% | 14.96% | -0.62 | -0.82% | 46.8% |
| [0,+60] | 103 | -2.75% | 22.27% | -1.25 | -0.62% | 49.5% |

## Verdict

**Edge NOT reproduced.** Per the DECIDED rule ("edge reproduced" iff mean CAR > 0
with t ≥ 1.5 in ≥1 of the (0,5)/(0,20)/(0,60) windows), no window clears the bar:
[0,+5] is directionally positive but t=1.21 (< 1.5); [0,+20] and [0,+60] flip
negative (t=-0.62, -1.25). Per G2, this is a valid, valuable **null result** — it is
reported honestly, not tuned toward a positive.

This does not reproduce research 0003's cited +2.64% parent CAAR. Plausible reasons
(not tested further here, per scope): the cited study used the demerger *effective*
date and a 2003-2020 sample; ours uses the *announcement* date over a different,
more recent window (see caveats).

## Caveats

- **n = 81-110** depending on window (fewer at [-1,+1]/[0,+60] where more events
  fall too close to `as_of` for the window to have closed, per the look-ahead
  guard). Thin relative to the cited 221-event study.
- **Date range: 2018-02 to 2026-07**, not "2020+ only" as this plan's background
  section assumed — the in-house `bse_announcements` corpus actually starts 2018,
  so the event set spans the full available history.
- **Announce-date, not effective-date.** Day0 is the *announcement* of the scheme,
  not the demerger's legal/trading effective date (record date of the listed
  child, or the date the parent's price is ex-adjusted for the spin-off). A
  demerger scheme typically takes many months (sometimes years) from announcement
  to effectiveness via NCLT approval — the announcement-date CAR captures the
  market's day-of-news reaction, not the drift around the actual corporate event.
  This is the most likely explanation for the negative-turning 20/60d drift: it is
  measuring "did the stock keep moving after the announcement headline," an
  unrelated question to "does the parent re-rate once the demerger completes."
- **sid-mapping coverage:** 155 headline-matched candidate rows → 117 (75.5%) had
  a raw `sid`; `tools.sid_crosswalk` (plan 0013 A2) recovered 2 more (see A2's own
  finding: the crosswalk barely lifts coverage beyond the raw column here, since
  `sources/scrip_master.py` already backfills `bse_announcements.sid` from the
  same map). 112 final rows after PK dedup (same-sid same-day multi-filings
  collapse to one event).
- Market-adjustment is NIFTY-50 only (no sector/size adjustment) — same convention
  as the wired `announcement_car`.

## Next

Per D7, a null does not get tuned toward a positive. If this hypothesis is
revisited, the natural next test (not attempted here, needs new data plumbing —
`corporate_actions`/child-listing linkage to derive an *effective* date) is the
same drift curve anchored on the demerger's effective/listing date instead of the
announcement date. **Not** "Engine-3 sleeve candidate" — G2/D7 apply.
