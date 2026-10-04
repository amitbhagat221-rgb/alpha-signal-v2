"""
Alpha Signal Ops (:3001) — the page list; the rail and mobile bar render from it
(cockpit/templates/_nav.html). Same entry shape as cockpit/pages.py.
"""

PAGES = [
    {"path": "/org", "id": "org", "title": "Boardroom", "subtitle": "Agent org · inbox · memos",
     "icon": "briefcase", "section": "Fund", "mobile": 1, "short": "Board"},
    {"path": "/system", "id": "system", "title": "Health Center", "subtitle": "Issues · data · factors · pipeline",
     "icon": "zap", "section": "Ops", "mobile": 2, "short": "Health"},
    {"path": "/flow", "id": "flow", "title": "Pipeline Flow", "subtitle": "Producer/consumer DAG",
     "icon": "git-branch", "section": "Ops", "mobile": 3, "short": "Pipeline"},
    {"path": "/feeds", "id": "feeds", "title": "Data Supply", "subtitle": "Feeds · canaries · discovery",
     "icon": "database", "section": "Ops", "mobile": 4, "short": "Feeds"},
    {"path": "/command", "id": "command", "title": "Command Centre", "subtitle": "Scripts & rebuilds",
     "icon": "compass", "section": "Ops", "short": "Command"},
    {"path": "/sql", "id": "sql", "title": "SQL Console", "subtitle": "Ad-hoc queries",
     "icon": "terminal", "section": "Ops", "short": "SQL"},
]

OTHER_APP = {"port": 3000, "path": "/", "section": "Trading cockpit", "title": "Open trading →",
             "subtitle": "port 3000 (separate)", "icon": "compass", "short": "Trading", "tooltip": ""}

BRAND = {"href": "/system", "label": "Alpha Signal", "aria": "Alpha Signal Ops", "subtitle": "ops · port 3001", "icon": "zap",
         "style": "background: linear-gradient(135deg, #ef4444 0%, #b91c1c 100%);"}
