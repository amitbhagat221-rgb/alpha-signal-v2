# comp-intel

A small, **self-contained** career/compensation-intelligence tool. It lives inside the
`alpha-signal-v2` repo for convenience but shares **nothing** with the quant model — its own
module, its own SQLite store, its own venv, its own docs. Personal-research use only.

**Goal:** benchmark a role's comp by *(role × level × location × firm)* — e.g. "market risk /
quant at a multi-strat HF, Bengaluru vs Dubai" — *without* touching any individual's private
data. Aggregate ranges only.

## Why two kinds of source
Compensation lives in two places, with very different reliability:

| Layer | Source | What it gives | Access |
|---|---|---|---|
| **Posted ranges** (noisy, abundant) | Naukri / Indeed / Glassdoor via **JobSpy** | employer-stated salary *ranges* in live listings, by role/location/skills | live scrape (works from a normal IP) |
| **Total comp** (precise, gated) | levels.fyi / AmbitionBox / Blind | base + bonus + stock by *level* | **CSV import** — these block datacenter scraping, so you export from the site and drop the file in `data/imports/` |

`comp-intel` normalises both into one store and produces percentile benchmarks.

## Setup (its own venv — not the alpha-signal venv)
```bash
cd comp-intel
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Usage
```bash
# 1. Pull live job postings (posted salary ranges) — Naukri + Indeed by default
python -m comp_intel.cli pull-jobs --role "market risk" --location "Bengaluru, India"

# 2. Import a total-comp export you downloaded from levels.fyi / AmbitionBox (CSV)
python -m comp_intel.cli import-comp data/imports/levels_export.csv --source levels.fyi

# 3. Benchmark — percentiles by role / location / firm, India vs UAE
python -m comp_intel.cli benchmark --role "market risk"
```

## Ethics / ToS
- **Aggregate only.** Never targets a named individual's pay.
- Job-portal backends are unofficial + ToS-restricted — throttle, personal use, don't redistribute.
- **LinkedIn is OFF by default** (`config.JOBSPY_SITES`): the unofficial Voyager path risks an
  account ban (User Agreement §8.2). Enable at your own risk with a throwaway account.
- Scraped data stays local — `data/` is git-ignored. Nothing personal is committed.

## Layout
```
comp-intel/
  README.md  requirements.txt  .gitignore  config.py
  comp_intel/
    store.py            # own SQLite (data/comp_intel.db)
    sources/
      jobs_jobspy.py    # live postings via JobSpy (Naukri/Indeed/Glassdoor/LinkedIn)
      comp_csv.py       # import total-comp CSV exports (levels.fyi/AmbitionBox/Blind)
    analyze.py          # percentile benchmarks + India↔UAE compare
    cli.py              # entry point
  docs/DESIGN.md
  data/                 # git-ignored: the DB + imports live here
```
