# Buyback record-date price-move study — in-house leg (plan 0013 B2)

Read-only. This is the IN-HOUSE price-move leg only — **the acceptance-ratio
arbitrage math is UNMEASURED here** and needs the PDF/Letter-of-Offer layer
(explicitly out of scope, see plan 0013 §OUT). This study answers "is there a
price move around the buyback record date," not "is the tender arb profitable."

**Events:** `event_calendar` where `event_type='buyback'`, day0 = `record_date`
(= `corporate_actions.ex_date`, the in-house record-date **proxy** — the true
tender record date may differ; this study treats `ex_date` as day0). 242 rows /
151 distinct sids, 2018-03 to 2026-07 (survivorship-safe by construction — the
record-date name stays listed through a buyback).

## Drift curve (market-adjusted CAR vs NIFTY-50, as of 2026-07-11)

| window | n | mean CAR | std | t-stat | median | hit-rate |
| --- | --- | --- | --- | --- | --- | --- |
| [-5,0] (pre) | 171 | -1.35% | 4.25% | -4.15 | -1.41% | 33.3% |
| [-1,+1] | 171 | -3.58% | 3.83% | -12.21 | -3.35% | 14.0% |
| [0,+5] | 242 | -0.76% | 4.79% | -2.47 | -1.04% | 37.6% |
| [0,+20] | 237 | -0.08% | 10.77% | -0.12 | -0.61% | 46.8% |
| [0,+60] | 226 | -2.33% | 18.54% | -1.89 | -6.83% | 38.5% |

## Verdict

**Edge NOT reproduced — and the sign is the opposite of a naive "buy into record
date" hypothesis.** Per the DECIDED rule (>0 with t≥1.5 in ≥1 window), no window
qualifies; every window is negative, and the tight [-1,+1] window is both large
(-3.58%) and extremely significant (t=-12.2, hit-rate only 14%). Per G2, this is
reported as-is — a real, high-confidence finding, just not the hypothesized one.

**Reading the sign:** the record date is when eligibility for the tender is fixed
— only holders as of that date can tender into the buyback. The pattern here
(mildly negative into the record date, then a sharp drop right at/after it) is
consistent with the record-date entitlement being priced in *ahead of time* and
then extracted from the price the moment it's "used up" — i.e. whatever premium
the market assigns to buyback participation gets stripped out at the record date
itself, not paid out gradually afterward. This is the mirror image of an
ex-dividend drop, but sharper and with a strongly negative pre-window rather than
a positive run-up — the in-house data does not show a clean "run-up into record
date" pattern to exploit.

## Caveats

- **`ex_date` is a proxy**, not a confirmed tender record date — `corporate_actions`
  doesn't distinguish tender vs. open-market buybacks, and open-market buybacks
  (company buys in the secondary market over time, no shareholder tender
  mechanics) would have no economic reason to show a record-date price effect at
  all. This study did not separate the two; the strong, consistent negative CAR
  suggests tender-style buybacks dominate the sample, but this is not verified
  here.
- **The arb-leg (retail 15%-reservation, 60-100% acceptance) is UNMEASURED.** A
  retail investor's realized return depends on the tender/buyback price vs. the
  cost basis and the acceptance ratio, not the open-market CAR measured here —
  that needs the PDF/Letter-of-Offer layer (§OUT).
- **Capacity note** (research 0003): even if a tender-arb edge existed, the
  retail-reservation cap (~₹2L/name) makes this an enhancer, not a book-mover.
- Market-adjustment is NIFTY-50 only (no sector/size adjustment), same convention
  as the wired `announcement_car` and B1.
- n drops at [-1,+1]/[0,+60] vs [0,+5]/[0,+20] because more of the most recent
  events haven't had their windows close yet by `as_of` (look-ahead guard).

## Next

Per D7/G2, a negative result does not get tuned toward a positive, and this does
NOT authorize building the PDF/Letter-of-Offer arb-math layer — that is a
separate, supervised, PDF-parsing session per §OUT. If revisited, the natural
follow-up is splitting tender vs. open-market buybacks (needs a `corporate_actions`
subject/announcement-type classifier not currently available) before re-reading
this drift curve.
