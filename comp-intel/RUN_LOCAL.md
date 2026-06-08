# comp-intel — run it on your laptop (not the server)

**Why:** the live job scrape (`pull-jobs`) needs a **residential IP**. From the Oracle VM's
datacenter IP the portals gate you — **Naukri → 406 (recaptcha), Glassdoor → 400, Indeed →
rows but no salaries**. The CSV-import + benchmark path works anywhere; only the live scrape
needs your laptop. So: pull this repo locally and run the whole thing there.

---

## 0. Pull the latest
```bash
git clone https://github.com/amitbhagat221-rgb/alpha-signal-v2.git   # first time
# or, if already cloned:
git pull
cd alpha-signal-v2/comp-intel
```

## 1. Setup (its own venv — separate from the alpha-signal venv)
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Pull live postings (the residential-IP step)
```bash
# all roles × locations from config.py:
python -m comp_intel.cli pull-jobs
# or target one:
python -m comp_intel.cli pull-jobs --role "market risk" --location "Mumbai, India"
```
Caveats seen in testing:
- **Indeed India rarely prints salaries**, and a bare `"market risk"` query surfaces generic
  IT/engineering roles (Siemens/Airbus). Tighten the query → see TODOs below.
- If Naukri still 406s even from home, add a small delay / proxy in
  `comp_intel/sources/jobs_jobspy.py`.

## 3. Import precise total-comp (base+bonus+stock)
levels.fyi / AmbitionBox / Blind block scraping — so export their CSV by hand, drop it in
`data/imports/`, then import (Indian shorthand `12L`/`1.2Cr` + currency are normalised to INR):
```bash
python -m comp_intel.cli import-comp data/imports/levels_export.csv --source levels.fyi
python -m comp_intel.cli import-comp data/imports/ambitionbox.csv   --source ambitionbox
```

## 4. Benchmark
```bash
python -m comp_intel.cli benchmark --role "market risk"   # p25 / median / p75, India↔UAE + firm rollups
python -m comp_intel.cli stats                            # row counts (jobs, comp_records)
```

**Verified:** the CSV-import + benchmark path reproduced **India ~80L vs UAE ~232L (~2.9×)**.
Live `pull-jobs` is the only piece still pending a residential-IP run.

---

## Hand it to a fresh Claude on your laptop

Paste this into a new Claude session in the `alpha-signal-v2/comp-intel/` directory:

```
I have a self-contained comp-benchmarking tool at alpha-signal-v2/comp-intel/.
Goal: benchmark compensation for a role by (role × level × location × firm) using
AGGREGATE ranges only — never any individual's pay. My focus: "market risk" and
"quantitative researcher / risk quant" roles, India (Bengaluru, Mumbai) vs UAE
(Dubai, Abu Dhabi), with firm rollups for Millennium / Citadel / Balyasny / etc.

It has two data layers:
  1. Posted salary ranges from LIVE job listings (Naukri/Indeed/Glassdoor) via the
     python-jobspy library — comp_intel/sources/jobs_jobspy.py.
  2. Precise total comp (base+bonus+stock) from levels.fyi / AmbitionBox / Blind,
     which block scraping — so I export their CSV and import via
     comp_intel/sources/comp_csv.py.

Setup:
  cd comp-intel
  python3 -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt

Tasks:
  1. Run `python -m comp_intel.cli pull-jobs` for my roles/locations (config.py).
     I'm on a residential IP now, so the portals should respond. If Naukri still
     blocks (406), add a small delay / proxy and tighten the search_term so it
     returns FINANCE risk roles, not generic IT.
  2. I'll download CSV exports from levels.fyi and AmbitionBox into data/imports/;
     import them: `python -m comp_intel.cli import-comp <file>.csv --source levels.fyi`.
  3. Run `python -m comp_intel.cli benchmark --role "market risk"` and give me the
     India-vs-UAE percentile picture + firm medians.
Improve query targeting and add a Blind importer if useful. Keep it aggregate-only.
```

---

## TODOs (good first follow-up commit from the laptop)
- **Tighten query targeting** so finance risk/quant roles surface instead of generic IT —
  e.g. append firm/skill qualifiers, or post-filter postings against `config.FIRMS` and
  finance keywords in `jobs_jobspy.py`.
- **Add a Blind importer** to `comp_intel/sources/comp_csv.py` (or a sibling) for Blind's
  total-comp exports.
- Optional: per-location `COUNTRY_INDEED` switch (config currently hardcodes `"India"`).

> Reminder: `data/` is git-ignored — scraped postings and the SQLite DB never get committed.
> Keep it aggregate-only; never store or surface a named individual's pay.
