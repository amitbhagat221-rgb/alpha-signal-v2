"""Live job postings via JobSpy (Naukri / Indeed / Glassdoor / LinkedIn).

These carry POSTED salary RANGES — noisy and often absent for senior finance roles, but the
best free signal for *what roles exist, where, at what stated bands*. JobSpy abstracts each
portal's unofficial backend behind one call.
"""

import hashlib

import config
from comp_intel import store


def _firm_tag(company):
    c = (company or "").lower()
    for f in config.FIRMS:
        if f.lower() in c:
            return f
    return None


def _to_inr_year(amount, interval, currency):
    if amount is None:
        return None
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return None
    per = (interval or "yearly").lower()
    if per.startswith("month"):
        amt *= 12
    elif per.startswith("hour"):
        amt *= 2000          # ~ full-time hours/year
    elif per.startswith("week"):
        amt *= 52
    elif per.startswith("day"):
        amt *= 250
    fx = config.FX_TO_INR.get((currency or "INR").upper(), 1.0)
    return round(amt * fx, 0)


def _job_id(site, url, title, company):
    basis = url or f"{title}|{company}|{site}"
    return f"{site}:{hashlib.md5(basis.encode('utf-8','replace')).hexdigest()[:16]}"


def _get(row, *names):
    for n in names:
        if n in row and row[n] is not None and str(row[n]) != "nan":
            return row[n]
    return None


def pull(role, location, sites=None, results=None, hours_old=None):
    """Scrape one (role × location) across the configured sites → store. Returns rows written."""
    from jobspy import scrape_jobs   # imported lazily so the rest of the tool runs without it

    sites = sites or config.JOBSPY_SITES
    results = results or config.RESULTS_PER_QUERY
    hours_old = hours_old or config.HOURS_OLD

    df = scrape_jobs(
        site_name=sites,
        search_term=role,
        location=location,
        results_wanted=results,
        hours_old=hours_old,
        country_indeed=config.COUNTRY_INDEED,
    )
    if df is None or len(df) == 0:
        return 0

    rows = []
    for r in df.to_dict("records"):
        site = _get(r, "site") or "?"
        url = _get(r, "job_url", "job_url_direct", "url")
        title = _get(r, "title")
        company = _get(r, "company")
        currency = _get(r, "currency") or "INR"
        interval = _get(r, "interval", "salary_period")
        smin = _get(r, "min_amount", "salary_min")
        smax = _get(r, "max_amount", "salary_max")
        rows.append({
            "job_id":        _job_id(site, url, title, company),
            "source":        site,
            "title":         title,
            "company":       company,
            "firm_tag":      _firm_tag(company),
            "location":      _get(r, "location") or location,
            "role_query":    role,
            "salary_min":    smin,
            "salary_max":    smax,
            "salary_period": interval,
            "currency":      currency,
            "salary_inr_min": _to_inr_year(smin, interval, currency),
            "salary_inr_max": _to_inr_year(smax, interval, currency),
            "experience":    _get(r, "experience_range", "experience"),
            "skills":        _get(r, "skills"),
            "is_remote":     1 if _get(r, "is_remote") in (True, "True", 1, "1") else 0,
            "date_posted":   str(_get(r, "date_posted") or ""),
            "url":           url,
            "fetched_at":    store.now(),
        })
    return store.upsert("jobs", rows, "job_id")
