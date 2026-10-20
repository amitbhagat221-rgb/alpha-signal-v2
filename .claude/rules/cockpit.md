---
paths:
  - "cockpit/**"
  - "cockpit_ops/**"
  - "webauth.py"
  - "preview.py"
---
# Cockpit (port 3000) and ops cockpit (port 3001)

- Every `<script>`/stylesheet from `/static` carries `?v={{ asset_version(...) }}` — `tests/test_static_cache.py` (an untagged `cockpit.js` left charts blank in Amit's cached browser).
- A template class must have a CSS rule — `tests/test_cockpit_css.py` (a "cleanup" once deleted the industry dossier's styles).
- Verify UI with Playwright at 1440 and 375, including a stale-cache browser.
- Kill a test instance by PID or port, never `pkill -f "uvicorn cockpit.app"` (it matches the prod systemd service).
- Pages cost what they SHOW, not what the DB holds: seek per stock (`WHERE sid = ? ORDER BY date DESC LIMIT n`), window by date or aggregate in SQL; never read a `big: True` table (`tables.TABLES`) whole to use a slice — `tests/test_cockpit_scaling.py` (live DB, read-only; exceptions go in its ALLOW list with a reason). Patterns: `docs/reference/cockpit.md` "Scaling".
