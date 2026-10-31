---
paths:
  - "cockpit/**"
  - "cockpit_ops/**"
  - "webauth.py"
  - "preview.py"
  - "ask.py"
  - "org_chat.py"
---
# Cockpit (port 3000) and ops cockpit (port 3001)

- Every `<script>`/stylesheet from `/static` carries `?v={{ asset_version(...) }}` — `tests/test_static_cache.py` (an untagged `cockpit.js` left charts blank in Amit's cached browser).
- A template class must have a CSS rule — `tests/test_cockpit_css.py` (a "cleanup" once deleted the industry dossier's styles).
- Verify UI with Playwright at 1440 and 375, including a stale-cache browser.
- After a `.py` or template change, restart the cockpit that serves it (`sudo -n systemctl restart alpha-cockpit-ops.service` for :3001): a template calling a new filter or Python function 500s on the live page until then.
- Kill a test instance by PID or port, never `pkill -f "uvicorn cockpit.app"` (it matches the prod systemd service).
- The Ask panel (`ask.py`) stays read-only: file tools only via one `Read(<repo>/**)` allow (bare `Grep`/`Glob` search any path); transcripts are `org.assistant`, never `org.ask` (the seats' inbox asks); save `cli_stream`'s `answer`, not `text` (pre-lookup notes) — `tests/test_ask.py`, ADR 0081.
- Pages cost what they SHOW, not what the DB holds: seek per stock (`WHERE sid = ? ORDER BY date DESC LIMIT n`), window by date or aggregate in SQL; never read a `big: True` table (`tables.TABLES`) whole to use a slice — `tests/test_cockpit_scaling.py` (live DB, read-only; exceptions go in its ALLOW list with a reason). Patterns: `docs/reference/cockpit.md` "Scaling".
