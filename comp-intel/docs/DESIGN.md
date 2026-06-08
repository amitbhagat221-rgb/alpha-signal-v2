# comp-intel — design

## What this is
A tiny, **self-contained** compensation-benchmarking tool. It answers *"is my comp fair for my
role/level/location?"* using **aggregate** ranges — never any named individual's pay. It lives
in the alpha-signal repo for convenience but shares nothing with the quant model (own package,
own SQLite, own venv, own deps).

## The core idea: two comp layers, different reliability
Compensation data splits cleanly:

1. **Posted ranges** — abundant, noisy. Employer-stated salary ranges inside live job listings.
   Often absent/wide for senior finance roles, but great for *role/demand mapping* (what's open,
   where, what skills, what stated bands). Source: **JobSpy** over Naukri/Indeed/Glassdoor.
   Scrapes fine from a normal IP.
2. **Total comp** — precise, gated. base + bonus + stock by *level*. Lives on levels.fyi /
   AmbitionBox / Blind, which **block datacenter scraping**. So the workflow is *export → import*:
   download the CSV from the site, drop in `data/imports/`, run `import-comp`. The importer maps
   common column names flexibly and normalises Indian shorthand (12L, 1.2Cr) + currency → INR.

`analyze.py` merges both into one percentile view (p25/median/p75), sliced by role/location/firm,
with an **India↔UAE** multiple (the number that matters for a Gulf move — and UAE is tax-free, so
the *net* gap is larger than the gross multiple shows).

## Module map
| File | Role |
|---|---|
| `config.py` | the watchlist — roles, locations, firms, FX, which portals |
| `comp_intel/store.py` | own SQLite (`data/comp_intel.db`); `jobs` + `comp_records` tables |
| `comp_intel/sources/jobs_jobspy.py` | live postings → normalised → store |
| `comp_intel/sources/comp_csv.py` | CSV import for the gated total-comp sources |
| `comp_intel/analyze.py` | percentile benchmarks + region/firm rollups |
| `comp_intel/cli.py` | `pull-jobs` / `import-comp` / `benchmark` / `stats` |

## Source reliability matrix
| Source | Layer | From a server IP | Notes |
|---|---|---|---|
| Naukri (JobSpy) | posted ranges | usually OK | richest Indian fields (skills, experience, rating) |
| Indeed (JobSpy) | posted ranges | usually OK | needs `country_indeed` |
| Glassdoor (JobSpy) | posted ranges | flaky | aggressive blocking |
| **LinkedIn** (JobSpy/Voyager) | postings | **OFF by default** | ToS §8.2 → account-ban risk; throwaway acct only |
| levels.fyi | total comp | **blocked (403)** | export CSV → `import-comp` |
| AmbitionBox | India CTC | blocked | export → import (Naukri/InfoEdge owns it) |
| Blind | total comp | blocked | manual → import |

## Ethics / ToS
Aggregate only; no individual targeting. Unofficial backends → throttle, personal use, no
redistribution. Scraped data stays local (`data/` git-ignored — only code + docs are committed).

## Possible extension (dual-use, NOT built)
The same `jobs` table is alternative data: **per-company hiring velocity** (open-postings count
over time) is a documented growth/forewarning signal. If ever useful to the quant model, it would
live there as its own factor — kept out of this personal tool by design.
