# cockpit_ops — Standalone Ops console (port 3001)

The "Ops" surface (Health Center, Pipeline Flow, Command Centre, SQL
Console) split out of the main trading cockpit so:

- the trading cockpit on **port 3000** stays focused on Daily/Analysis pages
- restarting Ops doesn't disturb trading and vice versa
- `cockpit/api.py` can shrink in Stage 2 (see below) without risk to live UI

## Pages

| Path | Page | Source API function |
|---|---|---|
| `/` | redirects to `/system` | — |
| `/system` | Health Center (Live Issues Inbox, Data, Factors, Pipeline tabs) | `get_health_overview` + 4 others |
| `/flow` | Pipeline producer/consumer DAG | `get_flow_overview` |
| `/command` | Command Centre — plans, factor library, data layer | `get_command_centre` |
| `/sql` | Read-only SQL console | `run_sql_query` |
| `/api/health/overview` | JSON | `get_health_overview` |
| `/api/health` | JSON | `get_data_freshness` |
| `/api/pipeline` | JSON | `get_pipeline_status` |
| `/api/pipeline/rerun/{step_name}` | POST | `rerun_step` |
| `/api/sql` | POST | `run_sql_query` |

## How it's wired (Stage 2 shipped 2026-05-26)

`cockpit_ops/api.py` is now standalone — the 10 Ops functions and their
private helpers were physically moved out of `cockpit/api.py`. Shared
decorators (`_persisted_cache`, `_ttl_cache`) stay in `cockpit.api` and
are imported one-way:

```python
from cockpit.api import _ttl_cache, _persisted_cache
```

Final file sizes after Stage 2:
- `cockpit/api.py`:     4,402 → **2,221** lines (−49.5%)
- `cockpit/app.py`:     586   → **488**   lines (Ops routes deleted)
- `cockpit_ops/api.py`: 22    → **2,239** lines (standalone)
- `cockpit_ops/app.py`: 205   lines (Ops FastAPI app)

Dead Ops routes (`/system`, `/flow`, `/command`, `/sql`,
`/api/pipeline*`, `/api/health*`, `/api/sql`) deleted from cockpit/app.py.
Anyone hitting them on port 3000 now gets a 404; the same paths are live
on port 3001.

## Future improvements (deferred)

- Move shared decorators into a `cockpit_common/cache.py` module so
  cockpit_ops doesn't have to import from cockpit (breaks the one-way
  dep direction cleanly).
- Run a `make_release` style check that ensures `cockpit/api.py` doesn't
  silently regrow Ops-domain functions in the future.

## Starting the service

```bash
# Local dev (foreground)
cd /home/ubuntu/alpha-signal-v2
source ~/alpha-signal/venv/bin/activate
uvicorn cockpit_ops.app:app --host 0.0.0.0 --port 3001 --reload

# Production (systemd) — copy the unit file once, then enable
sudo cp /home/ubuntu/alpha-signal-v2/cockpit_ops/alpha-cockpit-ops.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now alpha-cockpit-ops
sudo systemctl status alpha-cockpit-ops
```

Logs land in `/home/ubuntu/alpha-signal-v2/output/cockpit-ops.log`
(same format as the main cockpit).

## How the two services coordinate

- **Database**: both read/write the same SQLite at `data/alpha_signal.db`.
  SQLite WAL mode + journal handles concurrent readers cleanly.
- **Static assets**: `cockpit_ops/app.py` mounts `/static` from the
  shared `cockpit/static/` directory — no duplication of CSS/JS.
- **Caches**: each service has its own in-process TTL caches.
  Persisted disk cache at `data/.cockpit_cache/*.pkl` is shared — both
  services hit the same cache files. If their cache keys collide,
  whichever service writes last wins (acceptable; same source data
  produces same payload).
- **Cache warmup**: each service warms its OWN cache on startup
  (Ops warms 9 endpoints; trading warms 15). Run sequentially if
  starting both at once to avoid SQLite write contention.

## Health checks

After enabling:
```bash
curl -sf http://localhost:3001/api/health | jq '.[0]' | head
curl -sf http://localhost:3001/system | head -c 200
```

Both should return data; if the trading cockpit on 3000 is also up,
both services run cleanly side-by-side.
