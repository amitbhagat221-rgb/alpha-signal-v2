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
  tabs            optional [(key, label)]: the page's tabs, in order. The placeholder page
                  renders them; the page's own template passes the same list to tab_bar.
                  A tab is deep-linked as /path#key.
"""

# The Investor Playbooks tabs, in order (the first is rendered with the page, the rest are fetched
# on first open; cockpit/playbooks.py TABS maps each key to its data).
PLAYBOOK_TABS = [
    ("avoid", "Avoid list"), ("insiders", "Insider buying"), ("compounders", "Compounders"),
    ("strict", "Strict compounders"), ("investors", "Superinvestors"), ("breakouts", "Breakouts"),
    ("deep", "Deep value"), ("categories", "Categories"), ("saydo", "Say vs do"),
    ("cycle", "Market cycle"), ("portfolios", "Portfolios"), ("roadmap", "All approaches"),
]

PAGES = [
    {"path": "/", "id": "today", "title": "Today", "subtitle": "Read and act on today",
     "icon": "sun", "section": "Daily", "mobile": 1, "short": "Today",
     "also": ["brief", "actions"]},
    {"path": "/explorer", "id": "explorer", "title": "Explorer", "subtitle": "Every stock on one heat map",
     "icon": "bar-chart", "section": "Daily", "short": "Explorer"},
    {"path": "/stocks", "id": "stocks", "title": "Stocks", "subtitle": "Screen and open any stock",
     "icon": "search", "section": "Daily", "mobile": 2, "short": "Stocks"},
    {"path": "/markets", "id": "markets", "title": "Markets", "subtitle": "News and themes",
     "icon": "activity", "section": "Daily", "mobile": 3, "short": "Markets", "also": ["news"],
     "tabs": [("today", "Today"), ("themes", "Themes"), ("search", "Search")]},
    {"path": "/sectors", "id": "sectors", "title": "Sectors", "subtitle": "Sector call, industries, rotation",
     "icon": "layers", "section": "Daily", "short": "Sectors",
     "tabs": [("heatmap", "Today"), ("per-sector", "Industry Detail"), ("rotation", "Rotation")]},
    {"path": "/playbooks", "id": "playbooks", "title": "Investor Playbooks", "subtitle": "Screens in the style of known investors",
     "icon": "compass", "section": "Analysis", "short": "Playbooks", "also": ["multibagger"],
     "tabs": PLAYBOOK_TABS},
    {"path": "/book", "id": "book", "title": "Book", "subtitle": "Holdings, risk, results",
     "icon": "briefcase", "section": "Analysis", "mobile": 4, "short": "Book", "also": ["portfolio", "model-outcomes"],
     "tabs": [("book", "The book"), ("risk", "Risk"), ("track-record", "Track record")]},
    {"path": "/model", "id": "model", "title": "Model", "subtitle": "How the model is doing",
     "icon": "sliders", "section": "Analysis", "short": "Model",
     "tabs": [("health", "Health"), ("evidence", "Evidence"), ("library", "Library"), ("rules", "Rules")]},
    {"path": "/mutual-funds", "id": "mutual-funds", "title": "Funds",
     "subtitle": "Scored and ranked by category", "icon": "pie-chart", "section": "Funds", "short": "Funds"},
]

# Redirects from the retired URLs (one list, applied in cockpit/app.py). (old path, target).
# `{name}` in the old path is a path parameter that the target may reuse; the query string
# is carried over. A `#tab` in the target opens that tab on the new page.
REDIRECTS = [
    ("/actions", "/"),
    ("/explorer/{sid}", "/stocks/{sid}"),
    ("/news", "/markets"),
    ("/news/theme/{theme_id}", "/markets/theme/{theme_id}"),
    ("/news/all", "/markets#search"),
    ("/multibagger", "/playbooks#strict"),
    ("/ideas", "/playbooks"),
    ("/portfolio", "/book"),
    ("/model/outcomes", "/book#track-record"),
]

# The other app, linked from the rail foot and the mobile bar (host-relative port).
OTHER_APP = {"port": 3001, "path": "/system", "section": "Ops console", "title": "Open Ops →",
             "subtitle": "health, feeds, flow, SQL", "icon": "zap", "short": "Ops →",
             "tooltip": "Health, Feeds, Flow, Boardroom, SQL — a separate service"}

BRAND = {"href": "/", "label": "Alpha Signal", "aria": "Alpha Signal", "subtitle": "v2 cockpit", "icon": "diamond", "style": "",
         "title_suffix": "Alpha Signal"}
