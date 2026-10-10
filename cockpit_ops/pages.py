"""
Alpha Signal Ops (:3001) — the page list; the rail and mobile bar render from it
(cockpit/templates/_nav.html). Same entry shape as cockpit/pages.py.
"""

PAGES = [
    {"path": "/system", "id": "system", "title": "Health", "subtitle": "Is everything working?",
     "icon": "zap", "section": "Ops", "mobile": 1, "short": "Health",
     "tabs": [("overview", "Overview"), ("checks", "What we check"), ("inventory", "Inventory")]},
    {"path": "/feeds", "id": "feeds", "title": "Feeds", "subtitle": "Data sources, canaries, data",
     "icon": "database", "section": "Ops", "mobile": 2, "short": "Feeds", "also": ["command"]},
    {"path": "/flow", "id": "flow", "title": "Flow", "subtitle": "What runs, and the pipeline log",
     "icon": "git-branch", "section": "Ops", "mobile": 3, "short": "Flow"},
    {"path": "/org", "id": "org", "title": "Boardroom", "subtitle": "Agent org · inbox · memos",
     "icon": "briefcase", "section": "Fund", "mobile": 4, "short": "Board"},
    {"path": "/options", "id": "options", "title": "Options", "subtitle": "Paper book · forward test",
     "icon": "trending-up", "section": "Fund", "short": "Options"},
    {"path": "/sql", "id": "sql", "title": "SQL", "subtitle": "Ad-hoc queries",
     "icon": "terminal", "section": "More", "short": "SQL"},
]

# Retired URLs (applied in cockpit_ops/app.py; same shape as cockpit/pages.py REDIRECTS).
REDIRECTS = [
    ("/command", "/system"),
]

OTHER_APP = {"port": 3000, "path": "/", "section": "Trading cockpit", "title": "Open trading →",
             "subtitle": "picks, stocks, markets", "icon": "compass", "short": "Trading", "tooltip": ""}

BRAND = {"href": "/system", "label": "Alpha Signal", "aria": "Alpha Signal Ops", "subtitle": "ops", "icon": "zap",
         "title_suffix": "Ops", "style": "background: linear-gradient(135deg, #ef4444 0%, #b91c1c 100%);"}
