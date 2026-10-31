"""
TEMPORARY (2026-10-23, remove after Monday 2026-10-26): when does NSE first publish today's files?

The archive's Last-Modified headers say sec_bhavdata_full (our price + delivery file) at 23:55 IST
and ind_close_all at 23:20 IST every day, the same minute daily, so they may be rewritten
then rather than first published; the price-only UDiFF bhavcopy reads 16:33-16:37 IST. One
200-byte ranged GET per file every 30 min, 15:30-24:00 IST, appended to
output/nse_publish_probe.log. The first "200/206" line per file is the answer that decides
whether the price fetch can move to the evening (checklist: evening price fetch).

    python -m tools.nse_publish_probe             # today's files
    python -m tools.nse_publish_probe --summary   # first time each file was seen, per day
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sources import _http  # noqa: E402

LOG = Path(__file__).resolve().parents[1] / "output" / "nse_publish_probe.log"
IST = timezone(timedelta(hours=5, minutes=30))
FILES = {
    "sec_bhavdata_full": "https://archives.nseindia.com/products/content/sec_bhavdata_full_{dmy}.csv",
    "udiff_cm_bhavcopy": "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip",
    "ind_close_all": "https://nsearchives.nseindia.com/content/indices/ind_close_all_{dmy}.csv",
}


def probe(day=None):
    now = datetime.now(IST)
    day = day or now.date()
    out = []
    for name, url in FILES.items():
        url = url.format(dmy=day.strftime("%d%m%Y"), ymd=day.strftime("%Y%m%d"))
        try:
            # the host's own headers + a range: bare headers drop the browser UA, and nsearchives
            # then stalls every request until the timeout (seen 2026-10-23)
            headers = {**_http.host(url)[1]["headers"], "Range": "bytes=0-200"}
            r = _http.polite_request("GET", url, check=False, retries=0, timeout=30, headers=headers)
            rec = {"status": r.status_code, "last_modified": r.headers.get("Last-Modified"),
                   "csv": r.text[:6] if r.status_code in (200, 206) and not url.endswith(".zip") else None}
        except Exception as e:                       # a probe records the failure, it never raises
            rec = {"status": None, "error": f"{type(e).__name__}: {e}"[:200]}
        out.append({"at_ist": now.strftime("%Y-%m-%d %H:%M"), "day": day.isoformat(), "file": name, **rec})
    with LOG.open("a") as f:
        f.write("".join(json.dumps(o) + "\n" for o in out))
    for o in out:
        print(o)


def summary():
    first = {}
    for line in LOG.read_text().splitlines() if LOG.exists() else []:
        o = json.loads(line)
        key = (o["day"], o["file"])
        if o.get("status") in (200, 206) and key not in first:
            first[key] = o["at_ist"]
        first.setdefault(("_seen",) + key, o["at_ist"])
    days = sorted({k[0] for k in first if k[0] != "_seen"} | {k[1] for k in first if k[0] == "_seen"})
    for d in days:
        for name in FILES:
            print(f"{d}  {name:20s} first available: {first.get((d, name), 'not yet')}"
                  f"  (probing since {first.get(('_seen', d, name), '-')})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--summary", action="store_true")
    a = ap.parse_args()
    summary() if a.summary else probe()
