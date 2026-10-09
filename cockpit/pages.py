"""
Alpha Signal Cockpit (:3000) — the page list. The left rail and the mobile tab bar
are rendered from it (cockpit/templates/_nav.html); adding a page = a route, its
template and one entry here.

  path, id        URL and the `page` id its route passes to the template
  title, subtitle rail text; icon = an _icons.html name
  section         rail group heading (rail order = list order)
  mobile          position in the mobile bottom bar (1-4); pages without one go
                  in the bar's "More" sheet
  also            other `page` ids that light this entry up (sub-pages)
"""

PAGES = [
    {"path": "/", "id": "brief", "title": "Morning Brief", "subtitle": "Today's read & top picks",
     "icon": "sun", "section": "Daily", "mobile": 1, "short": "Brief"},
    {"path": "/actions", "id": "actions", "title": "Action Queue", "subtitle": "Buys & sells to act on",
     "icon": "target", "section": "Daily", "mobile": 3, "short": "Actions"},
    {"path": "/explorer", "id": "explorer", "title": "Explorer", "subtitle": "Browse 2,448 stocks",
     "icon": "search", "section": "Daily", "mobile": 4, "short": "Explore"},
    {"path": "/news", "id": "news", "title": "News", "subtitle": "Today, 7 themes, sectors",
     "icon": "activity", "section": "Daily", "mobile": 2, "short": "News"},
    {"path": "/portfolio", "id": "portfolio", "title": "Portfolio", "subtitle": "Holdings & tier mix",
     "icon": "briefcase", "section": "Analysis", "short": "Portfolio"},
    {"path": "/sectors", "id": "sectors", "title": "Sectors", "subtitle": "Industry rotation",
     "icon": "layers", "section": "Analysis", "short": "Sectors"},
    {"path": "/model", "id": "model", "title": "Model & Backtest", "subtitle": "Weights · backtest · outcomes",
     "icon": "sliders", "section": "Analysis", "short": "Model", "also": ["model-outcomes"]},
    {"path": "/multibagger", "id": "multibagger", "title": "Multibagger", "subtitle": "Quality-gated watchlist",
     "icon": "trending-up", "section": "Analysis", "short": "Multibagger"},
    {"path": "/playbooks", "id": "playbooks", "title": "Investor Playbooks", "subtitle": "Avoid · insiders · compounders · cloning",
     "icon": "compass", "section": "Analysis", "short": "Playbooks"},
    {"path": "/mutual-funds", "id": "mutual-funds", "title": "Mutual Funds",
     "subtitle": "~14k schemes · scored + ranked", "icon": "pie-chart", "section": "Funds", "short": "Funds"},
]

# The other app, linked from the rail foot and the mobile bar (host-relative port).
OTHER_APP = {"port": 3001, "path": "/system", "section": "Ops console", "title": "Open Ops →",
             "subtitle": "port 3001 (separate service)", "icon": "zap", "short": "Ops →",
             "tooltip": "Health Center, Pipeline, Command, SQL — runs on port 3001"}

BRAND = {"href": "/", "label": "Alpha Signal", "aria": "Alpha Signal", "subtitle": "v2 cockpit", "icon": "diamond", "style": "",
         "title_suffix": "Alpha Signal"}
