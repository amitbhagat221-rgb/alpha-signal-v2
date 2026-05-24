# ADR 0023 — Health Center: cockpit is the single window into system health

**Status**: accepted · 2026-05-24
**Supersedes part of**: [ADR 0019](0019-observability-sensor-surface-alert.md) (which set the sensor/surface/alert layering but left the surface mostly terminal)

## Context

The system has multiple silent-failure detectors — `tools.health_report`, `tools.data_sanity`, `cockpit_endpoint_audit`, dossier validator, freshness_watchdog. Their output landed in:

- terminal (when run manually),
- 04:00 UTC email digest,
- URGENT push on CRITICAL.

But none in cockpit. The user runs cockpit daily for picks/explorer/factors; to know if the system is healthy they had to also read email or terminal. This is the friction the redesign closes.

## Decision

Cockpit is the **single window** into system health. `/system` (renamed in nav to **Health Center**) becomes the user's only required surface. Email + push remain as out-of-cockpit pings; they should never be the only place a finding shows up.

Architecture:

1. **`cockpit/api.py::get_health_overview()`** is the single aggregation point. It calls `tools.health_report.gather()` + `tools.data_sanity.run()` + queries `pipeline_log endpoint_audit_*` + reads dossier validator output. Returns a uniform issue schema (severity / source / category / code / message / table / column / sample / volume / drilldown). Adding a new detector means adding ONE branch here, not editing the cockpit template.

2. **Overview tab** is the default landing. Verdict banner (CRITICAL/WARN/INFO counts), 4 pillar tiles, **Live Issues Inbox** — one filterable feed. New findings appear without template changes.

3. **Sub-tabs are slices** of the same data, not separate sources of truth. Data tab = freshness/sanity findings for tables. Factor tab = factor health. Pipeline tab = pipeline log + currently-broken steps. Inventory tab = table metadata. Each gets filters (radios / dropdowns / search) for institution-grade ergonomics.

4. **Single registry, multiple surfaces** — the overview API drives both the cockpit HTML render and `/api/health/overview` JSON (for future automation, Slack bot, etc.). Email digest may eventually call the same API to ensure parity.

## Why not just polish email

- Email digest fires once at 04:00 UTC; intra-day finds (a fetch that fails at 14:00) wait until next morning.
- Email has no filters or drilldown — every issue prose-only.
- The user explicitly stated cockpit is their primary window. Optimizing email instead means optimizing the wrong surface.

## Trade-offs

- **One more cockpit dep**: cockpit now imports `tools.data_sanity` and `tools.health_report` directly. That's fine — they're pure functions over the DB.
- **`get_health_overview()` is synchronous and runs every page load** (~1.5s on cold cache). Acceptable for a personal-use cockpit. If load grows, wrap in `_ttl_cache(30)`.
- **Tile grades are heuristics** (F if any CRITICAL, C if ≥5 WARN, B if any WARN, else A). Not science. Tune from feedback.

## Reversal cost

Low. The `get_health_overview()` function is self-contained; the template additions are scoped to `system.html`. Reverting = delete the Overview tab block + revert `app.py::system()` + uninstall the helpful filter toolbars. The 2 CRITICAL fixes (shareholding clamp, consensus gate) are independent and stay regardless.
