"""
Alpha Signal v2 — Hosts: every external dependency and its politeness, declared once.

ADR 0052 block "Host", invariant 5 "Politeness". sources/_http.py is the one door:
  polite_get / polite_request   resolve a URL's host here (gap, headers, retries)
  pace(host)                    paces library clients that do their own HTTP
                                (yfinance, nselib, feedparser, kiteconnect, Bharat_sm_data)
  time_budget(host)             reads budget_min
LLM callers read HOSTS["anthropic"]["models"].

Per host — every key optional, missing keys fall back to DEFAULT:
  netlocs     URL netlocs that resolve to this host (exact match); calls to all of
              them share ONE gap
  gap         min seconds from the END of one call to the START of the next (CLAUDE.md ≥2)
  jitter      extra uniform-random seconds on top of each gap (anti-bot rhythm)
  headers     sent when the caller passes neither a session nor headers
              ({} = the HTTP library's defaults)
  retries     polite_get retries on timeout / connection error / 429 / 5xx
  budget_min  wall-clock minutes one run may spend on the host (time_budget)
  impersonate curl_cffi browser profile for warm_session (e.g. "chrome") — for WAFs
              that reject python-requests' TLS fingerprint (BSE/Akamai, 2026-09-19)
An undeclared netloc gets DEFAULT and its own gap. Plain dicts (ADR 0004).
"""

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
# Full desktop-browser UA for sites that gate on it (BSE, Screener, Tickertape, ETMoney).
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

DEFAULT = {"gap": 2.0, "jitter": 0.0, "headers": {"User-Agent": UA}, "retries": 2,
           "budget_min": None, "impersonate": None}

HOSTS = {
    # ── Exchanges ──
    # nselib calls are paced here too: every nselib fetch warms www.nseindia.com.
    "nse": {"netlocs": ["www.nseindia.com"],
            "headers": {"User-Agent": UA, "Accept": "application/json"}},
    "nse_archives": {"netlocs": ["archives.nseindia.com", "nsearchives.nseindia.com"]},
    # Filing PDFs are served only with a browser UA + a bseindia referer.
    # Akamai 403s python-requests on api.bseindia.com since ~2026-09-19 (TLS fingerprint);
    # a Chrome-impersonating session passes. The warm-up host decides the session type.
    "bse": {"netlocs": ["www.bseindia.com"], "jitter": 1.0, "impersonate": "chrome",
            "headers": {"User-Agent": BROWSER_UA, "Referer": "https://www.bseindia.com/"}},
    "bse_api": {"netlocs": ["api.bseindia.com"], "jitter": 1.0, "impersonate": "chrome",
                "headers": {"User-Agent": BROWSER_UA, "Referer": "https://www.bseindia.com/",
                            "Origin": "https://www.bseindia.com",
                            "Accept": "application/json, text/plain, */*"}},

    # ── Research sites (scraped; bans are account- or IP-wide) ──
    # Screener has banned accounts for aggressive scraping: 2.5–4 s, jittered.
    "screener": {"netlocs": ["www.screener.in"], "gap": 2.5, "jitter": 1.5,
                 "headers": {"User-Agent": BROWSER_UA, "Accept": "*/*"}},
    "tickertape": {"netlocs": ["tickertape.in", "www.tickertape.in", "api.tickertape.in",
                               "analyze.api.tickertape.in"],
                   "headers": {"User-Agent": BROWSER_UA,
                               "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                               "Accept-Language": "en-US,en;q=0.5"}},
    # 2 s tripped the Moneycontrol WAF; the Referer pin matters, and the autosuggest
    # endpoint 403s unless Accept advertises JSON. Daily run is budgeted, stalest-first.
    "moneycontrol": {"netlocs": ["www.moneycontrol.com"], "gap": 12.0, "budget_min": 90,
                     "headers": {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                                "Chrome/120.0.0.0 Safari/537.36"),
                                 "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9",
                                 "Referer": "https://www.moneycontrol.com/"}},
    "yahoo": {"netlocs": ["query1.finance.yahoo.com", "query2.finance.yahoo.com",
                          "fc.yahoo.com", "guce.yahoo.com"]},
    "kite": {"netlocs": ["api.kite.trade", "kite.zerodha.com", "kite.trade"]},

    # ── Mutual funds ──
    # ETMoney soft-blocks faster steady-state scraping.
    "etmoney": {"netlocs": ["www.etmoney.com"], "gap": 2.5,
                "headers": {"User-Agent": BROWSER_UA, "Accept": "text/html,application/xhtml+xml",
                            "Accept-Language": "en-US,en;q=0.9"}},
    "amfi": {"netlocs": ["www.amfiindia.com", "portal.amfiindia.com"]},
    "mfapi": {"netlocs": ["api.mfapi.in"]},

    # ── Macro, news, regulatory ──
    "data_gov": {"netlocs": ["api.data.gov.in"]},
    "fred": {"netlocs": ["fred.stlouisfed.org"]},
    "rbi": {"netlocs": ["www.rbi.org.in"]},
    "pib": {"netlocs": ["pib.gov.in"], "headers": {"User-Agent": UA, "Accept": "text/html"}},
    "google_news": {"netlocs": ["news.google.com"]},
    "wayback": {"netlocs": ["web.archive.org"]},
    "economictimes": {"netlocs": ["economictimes.indiatimes.com"]},
    "livemint": {"netlocs": ["www.livemint.com"]},
    "pexels_api": {"netlocs": ["api.pexels.com"]},
    "pexels_images": {"netlocs": ["images.pexels.com"]},

    # ── Reference files (fetched with the HTTP library's default headers) ──
    "upstox": {"netlocs": ["assets.upstox.com"], "headers": {}},
    "github_raw": {"netlocs": ["raw.githubusercontent.com"], "headers": {}},

    # ── LLM ── Claude model id by purpose. No call/spend cap exists yet; spend is
    # tracked per call in `llm_usage` (db.log_llm_usage). regulatory_deep is ~60% of
    # daily spend — flip it to Haiku ONLY after `python -m tools.compare_reg_models`
    # reports ≥90% agreement on direction + is_regulatory.
    "anthropic": {"netlocs": ["api.anthropic.com"],
                  "models": {"news_brief": "claude-sonnet-4-6",
                             "news_classify": "claude-haiku-4-5-20251001",
                             "regulatory_prefilter": "claude-haiku-4-5-20251001",
                             "regulatory_deep": "claude-sonnet-4-6",
                             "dossier": "claude-sonnet-4-6",
                             "industry_classify": "claude-haiku-4-5-20251001",
                             "sector_narrative": "claude-sonnet-4-6",
                             "sector_dossier": "claude-sonnet-4-6"}},
}
