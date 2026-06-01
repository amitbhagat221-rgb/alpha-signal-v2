"""
Alpha Signal v2 — Daily Health Report

Single source of truth for "is the system healthy?". Gathers state from
pipeline_log, data_health() (which now covers DB tables AND file outputs),
and watchdog history. Classifies findings into CRITICAL / WARN / OK and
formats for three surfaces:

  - terminal: `/catchup` block at the top of every session
  - email:    daily HTML brief at 04:00 UTC
  - push:     ntfy.sh + URGENT-prefixed email on CRITICAL only

The whole point: silent failures stop being silent. Every channel renders
from the same gather() call, so terminal/email/push can never disagree.

Usage:
    python -m tools.health_report                   # terminal only
    python -m tools.health_report --email           # send daily brief
    python -m tools.health_report --push            # push CRITICAL only
    python -m tools.health_report --email --push    # cron: daily run
    python -m tools.health_report --since-days 3    # widen failure window

Env vars:
    GMAIL_USER, GMAIL_APP_PASSWORD, EMAIL_RECIPIENT — for --email and URGENT push
    NTFY_TOPIC — optional, enables ntfy.sh push for CRITICAL. Pick a unique
                 hard-to-guess string; install the ntfy.sh phone app and subscribe.
"""

import argparse
import os
import re
import smtplib
import sys
import urllib.request
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import data_health, read_sql

# Shared with output/email_sender.py — single source of truth for the cockpit
# URL so health emails and the daily brief stay in sync.
COCKPIT_URL = os.environ.get("COCKPIT_BASE_URL", "http://140.245.248.166:3000")


# ─────────────────────── Severity classification ───────────────────────

CRITICAL = "CRITICAL"
WARN = "WARN"
INFO = "INFO"
OK = "OK"

# Tables whose staleness should page (not just warn). Keep this short.
CRITICAL_TABLE_OUTDATED = {
    "daily_picks",          # screener output — the whole point of the system
    "daily_snapshots",      # signal store
    "stock_prices",         # underlying universe data
    "_file_dossiers",       # LLM thesis output
}

# ── Empty-table policy (the ONE source of truth; cockpit consumes this) ──
# An empty table is not automatically a failure. Two classes are benign:
#   *_quarantine — Trust-Pipeline (Plan 0007) reject sinks. Rows here = bad
#                  news; EMPTY means nothing was quarantined, i.e. clean. (OK)
#   the set below — features that legitimately have no rows yet. (INFO)
# Anything else empty = a producer wrote 0 rows where rows are expected. (CRITICAL)
EXPECTED_EMPTY_SUFFIXES = ("_quarantine",)
EXPECTED_EMPTY_TABLES = {
    "paper_trades",        # paper-trading not live yet
    "paper_positions",
    "paper_nav_history",
    "uhs_calibration_log", # Plan 0007 Phase 8 calibration scaffold — not yet populated
}


def empty_table_severity(table):
    """Severity for an EMPTY table. OK = healthy/expected (suppress),
    INFO = known-not-yet-populated, CRITICAL = unexpected 0-row producer."""
    if table.endswith(EXPECTED_EMPTY_SUFFIXES):
        return OK
    if table in EXPECTED_EMPTY_TABLES:
        return INFO
    return CRITICAL


# A step name failing on 2+ consecutive days = systemic, not a fluke
FAILURE_STREAK_DAYS = 2


# ─────────────────────── Gathering ───────────────────────


def gather(since_days=1):
    """Build the canonical health report dict.

    Returns:
        {
            "as_of": ISO datetime,
            "pipeline": {
                "last_run_date": "...",
                "last_run_status": "SUCCESS" / "FAILED" / None,
                "failed_steps_today": [{step, error, at}],
                "failed_streaks": [{step, days, sample_error}],
            },
            "tables": {
                "fresh": int,
                "stale": [(table, age, threshold, producer)],
                "outdated": [(table, age, threshold, producer)],
                "empty": [table],
            },
            "watchdog": {
                "last_run": "...",
                "healed": int, "failed": int, "skipped": int,
            },
            "issues": [{severity, code, message, detail}],
            "summary": {"critical": int, "warn": int, "verdict": str},
        }
    """
    out = {"as_of": datetime.now().isoformat(timespec="seconds")}

    # The five sub-gatherers are independent (each opens its own read-only DB
    # connection and returns a distinct key). Run them concurrently — the slow
    # pair (_gather_sanity ~11s, _gather_tables ~7s) dominated a serial ~18s
    # gather(); overlapping them takes the cold /system page off that floor.
    import concurrent.futures as _cf
    _tasks = {
        "pipeline": lambda: _gather_pipeline(since_days),
        "tables":   _gather_tables,
        "watchdog": _gather_watchdog,
        "dossiers": _gather_dossiers,
        "sanity":   _gather_sanity,
    }
    with _cf.ThreadPoolExecutor(max_workers=len(_tasks)) as _ex:
        _futs = {k: _ex.submit(fn) for k, fn in _tasks.items()}
        for k, fut in _futs.items():
            out[k] = fut.result()

    issues = _classify(out)
    out["issues"] = issues
    critical = sum(1 for i in issues if i["severity"] == CRITICAL)
    warn = sum(1 for i in issues if i["severity"] == WARN)
    if critical:
        verdict = f"⚠ {critical} CRITICAL, {warn} warn"
    elif warn:
        verdict = f"⚠ {warn} warn"
    else:
        verdict = "✓ all healthy"
    out["summary"] = {"critical": critical, "warn": warn, "verdict": verdict}
    return out


def _gather_pipeline(since_days):
    """Last pipeline run summary + recent failures + failure streaks."""
    out = {"last_run_date": None, "last_run_status": None,
           "failed_steps_today": [], "failed_streaks": []}

    # Latest run date with any logged step
    latest = read_sql(
        "SELECT MAX(run_date) as d FROM pipeline_log"
    )
    if latest.empty or latest.iloc[0]["d"] is None:
        return out
    last_date = latest.iloc[0]["d"]
    out["last_run_date"] = last_date

    # Failed steps on the latest run
    failed_today = read_sql(
        "SELECT step_name, status, started_at, error_message "
        "FROM pipeline_log WHERE run_date = ? AND status = 'FAILED' "
        "ORDER BY started_at",
        params=[last_date],
    )
    out["failed_steps_today"] = [
        {
            "step": r["step_name"],
            "error": (r["error_message"] or "")[:200],
            "at": r["started_at"],
        }
        for _, r in failed_today.iterrows()
    ]

    # Failure streaks: same step failing N+ days in a row AND not yet recovered.
    # A step that failed Mon+Tue but succeeded Wed is historical noise, not actionable.
    streaks = read_sql(
        """
        WITH latest_status AS (
            SELECT step_name,
                   status,
                   ROW_NUMBER() OVER (PARTITION BY step_name ORDER BY id DESC) AS rn
            FROM pipeline_log
            WHERE status IN ('SUCCESS', 'FAILED')
        ),
        currently_broken AS (
            SELECT step_name FROM latest_status WHERE rn = 1 AND status = 'FAILED'
        )
        SELECT pl.step_name,
               COUNT(DISTINCT pl.run_date) AS n_days,
               MAX(pl.error_message) AS sample_error
        FROM pipeline_log pl
        JOIN currently_broken cb ON cb.step_name = pl.step_name
        WHERE pl.status = 'FAILED'
          AND pl.run_date >= date('now', ?)
        GROUP BY pl.step_name
        HAVING n_days >= ?
        ORDER BY n_days DESC
        """,
        params=[f"-{since_days + FAILURE_STREAK_DAYS} days", FAILURE_STREAK_DAYS],
    )
    out["failed_streaks"] = [
        {
            "step": r["step_name"],
            "days": int(r["n_days"]),
            "sample_error": (r["sample_error"] or "")[:200],
        }
        for _, r in streaks.iterrows()
    ]

    # Overall run status: SUCCESS if no failures today, FAILED otherwise
    out["last_run_status"] = "FAILED" if out["failed_steps_today"] else "SUCCESS"
    return out


def _gather_tables():
    """Freshness breakdown from data_health()."""
    # cache_ttl lets this share the scan with cockpit's get_data_freshness on a
    # cold /system load (same 60s window) instead of recomputing the ~7s scan.
    df = data_health(cache_ttl=60)
    fresh = int((df["freshness"] == "FRESH").sum())
    stale = [
        (r["table"], r["age_days"], r["threshold_days"], r["produced_by"])
        for _, r in df[df["freshness"] == "STALE"].iterrows()
    ]
    outdated = [
        (r["table"], r["age_days"], r["threshold_days"], r["produced_by"])
        for _, r in df[df["freshness"] == "OUTDATED"].iterrows()
    ]
    empty = df[df["status"] == "EMPTY"]["table"].tolist()
    return {"fresh": fresh, "stale": stale, "outdated": outdated, "empty": empty}


def _gather_dossiers():
    """Inspect the newest dossier file for hallucinated content.

    Returns { latest_file, n_total, n_thesis, n_validated, n_failed_validation,
              failed_samples: [(ticker, n_violations, sample_snippet)] }.
    """
    import glob as _glob
    out = {
        "latest_file": None, "latest_date": None,
        "n_total": 0, "n_thesis": 0,
        "n_validated": 0, "n_failed_validation": 0,
        "failed_samples": [],
    }
    files = sorted(_glob.glob(str(PROJECT_ROOT / "output" / "dossiers_*.json")), reverse=True)
    if not files:
        return out
    latest = files[0]
    out["latest_file"] = Path(latest).name
    m = re.search(r"(\d{4}-\d{2}-\d{2})", Path(latest).name)
    if m:
        out["latest_date"] = m.group(1)
    try:
        import json as _json
        with open(latest) as fh:
            data = _json.load(fh)
    except Exception:
        return out
    out["n_total"] = len(data)
    for d in data:
        if not isinstance(d, dict):
            continue
        if d.get("thesis"):
            out["n_thesis"] += 1
            v = d.get("validation")
            if v is None:
                # Legacy dossier (pre-validator) — neither pass nor fail
                continue
            if v.get("ok"):
                out["n_validated"] += 1
            else:
                out["n_failed_validation"] += 1
                if len(out["failed_samples"]) < 3 and v.get("violations"):
                    sample = v["violations"][0]
                    out["failed_samples"].append({
                        "ticker": d.get("ticker", d.get("sid", "?")),
                        "n_violations": len(v["violations"]),
                        "sample": f"{sample['field']}: '{sample['snippet']}' ({sample['kind']})",
                    })
    return out


def _gather_sanity():
    """Run the assertion suite from tools/data_sanity. Returns the violation list."""
    try:
        from tools.data_sanity import run as run_sanity
        return run_sanity()
    except Exception as e:
        return [{"severity": WARN, "code": "SANITY_CHECK_RAISED",
                 "message": f"data_sanity audit itself raised: {type(e).__name__}: {e}"}]


def _gather_watchdog():
    """Last watchdog run summary from pipeline_log."""
    out = {"last_run": None, "healed": 0, "failed": 0, "skipped": 0}
    df = read_sql(
        "SELECT step_name, status, started_at FROM pipeline_log "
        "WHERE step_name LIKE 'watchdog_%' "
        "ORDER BY started_at DESC LIMIT 100"
    )
    if df.empty:
        return out
    out["last_run"] = df.iloc[0]["started_at"]
    same_day = df[df["started_at"].str[:10] == df.iloc[0]["started_at"][:10]]
    out["healed"] = int((same_day["status"] == "SUCCESS").sum())
    out["failed"] = int((same_day["status"] == "FAILED").sum())
    out["skipped"] = int((same_day["status"] == "SKIPPED").sum())
    return out


def _classify(state):
    """Generate issue list with severities from the gathered state."""
    issues = []

    # Pipeline failures today
    for f in state["pipeline"]["failed_steps_today"]:
        sev = CRITICAL if any(crit in f["step"] for crit in ("screener", "snapshot", "dossier")) else WARN
        issues.append({
            "severity": sev,
            "code": "PIPELINE_STEP_FAILED",
            "message": f"{f['step']} failed in latest pipeline run",
            "detail": f["error"],
        })

    # Streaks always escalate
    for s in state["pipeline"]["failed_streaks"]:
        issues.append({
            "severity": CRITICAL,
            "code": "PIPELINE_STREAK",
            "message": f"{s['step']} has failed {s['days']} consecutive days",
            "detail": s["sample_error"],
        })

    # Outdated tables — critical if in the page-set, warn otherwise
    for tbl, age, threshold, producer in state["tables"]["outdated"]:
        sev = CRITICAL if tbl in CRITICAL_TABLE_OUTDATED else WARN
        issues.append({
            "severity": sev,
            "code": "TABLE_OUTDATED",
            "message": f"{tbl} is OUTDATED ({age}d old, threshold {threshold}d)",
            "detail": f"producer: {producer}",
        })

    # Stale = warn only (within 2× threshold)
    for tbl, age, threshold, producer in state["tables"]["stale"]:
        issues.append({
            "severity": WARN,
            "code": "TABLE_STALE",
            "message": f"{tbl} is STALE ({age}d / threshold {threshold}d)",
            "detail": f"producer: {producer}",
        })

    # Empty tables — benign quarantine sinks (OK) and not-yet-live feature
    # tables (INFO) are suppressed from the email; only an *unexpected* 0-row
    # producer (CRITICAL) is actionable. The cockpit applies the full
    # OK/INFO/CRITICAL policy via empty_table_severity() for its richer pane.
    for tbl in state["tables"].get("empty", []):
        if empty_table_severity(tbl) != CRITICAL:
            continue
        issues.append({
            "severity": CRITICAL,
            "code": f"TABLE_EMPTY:{tbl}",
            "message": f"{tbl} is EMPTY (table exists but no rows)",
            "detail": "producer wrote 0 rows where rows are expected",
        })

    # Data sanity violations — catches "rows are wrong" (PT==price, rank dups, etc.)
    # Severity comes from the assertion itself; we just rebadge with the SANITY_ prefix.
    for v in state.get("sanity", []):
        if v["severity"] == INFO:
            continue  # INFO-level sanity findings stay out of the alerts pane
        issues.append({
            "severity": v["severity"] if v["severity"] in (CRITICAL, WARN) else WARN,
            "code": f"SANITY:{v['code']}",
            "message": v["message"],
            "detail": (f"{v.get('table','?')}.{v.get('column','?')} — "
                       f"{v.get('n_violations','?')}/{v.get('n_total','?')}"
                       + (f" ({v['pct_violations']:.1f}%)" if v.get('pct_violations') is not None else "")
                       + (f" · {v['sample']}" if v.get('sample') else "")),
        })

    # Dossier hallucination check — any failed validation in the latest file is CRITICAL.
    # Cockpit refuses to render them, but the file still contains them and the
    # LLM may need prompt-tuning if the rate is high.
    d = state["dossiers"]
    if d["n_failed_validation"] > 0:
        sample_text = "; ".join(
            f"{s['ticker']} ({s['n_violations']} hits: {s['sample']})"
            for s in d["failed_samples"]
        )
        issues.append({
            "severity": CRITICAL,
            "code": "DOSSIER_HALLUCINATION",
            "message": f"{d['n_failed_validation']}/{d['n_thesis']} dossiers smuggled numbers into narrative",
            "detail": f"latest={d['latest_file']}; samples: {sample_text}",
        })

    # Watchdog hasn't run at all → critical (covers the original 2026-05-22 bug)
    if state["watchdog"]["last_run"] is None:
        issues.append({
            "severity": CRITICAL,
            "code": "WATCHDOG_NEVER_RAN",
            "message": "freshness_watchdog has no run history",
            "detail": "Check crontab. Without the watchdog, silent producer failures accumulate.",
        })
    else:
        # Watchdog ran but >36h ago → warn (it's a daily cron)
        last_dt = datetime.fromisoformat(state["watchdog"]["last_run"])
        age_h = (datetime.now() - last_dt).total_seconds() / 3600
        if age_h > 36:
            issues.append({
                "severity": WARN,
                "code": "WATCHDOG_STALE",
                "message": f"freshness_watchdog last ran {age_h:.0f}h ago",
                "detail": "Expected daily. Check cron.",
            })

    # Sort: CRITICAL first, then WARN
    severity_rank = {CRITICAL: 0, WARN: 1, OK: 2}
    issues.sort(key=lambda i: (severity_rank[i["severity"]], i["code"]))
    return issues


# ─────────────────────── Formatting ───────────────────────


def format_terminal(state):
    """Plain-text block for /catchup. Width-aware, fits a 100-col terminal."""
    lines = []
    s = state["summary"]
    lines.append(f"━━━ SYSTEM HEALTH  ({state['as_of'][:16]})  {s['verdict']}")

    p = state["pipeline"]
    lines.append(f"  Pipeline: last={p['last_run_date']} → {p['last_run_status']}"
                 + (f" ({len(p['failed_steps_today'])} steps failed)" if p['failed_steps_today'] else ""))
    t = state["tables"]
    lines.append(f"  Tables: {t['fresh']} fresh, {len(t['stale'])} stale, {len(t['outdated'])} outdated, {len(t['empty'])} empty")
    w = state["watchdog"]
    if w["last_run"]:
        lines.append(f"  Watchdog: {w['last_run'][:16]} (healed={w['healed']}, failed={w['failed']}, skipped={w['skipped']})")
    else:
        lines.append("  Watchdog: NEVER RUN — check crontab")

    if state["issues"]:
        lines.append("")
        lines.append("ISSUES:")
        for i in state["issues"]:
            marker = "❌" if i["severity"] == CRITICAL else "⚠"
            lines.append(f"  {marker} [{i['severity']}] {i['message']}")
            if i["detail"]:
                lines.append(f"      {i['detail'][:140]}")
    else:
        lines.append("")
        lines.append("No issues. System is healthy.")
    lines.append("━" * 80)
    return "\n".join(lines)


def format_email_html(state):
    """HTML email body. Reuses the dark cockpit palette so it doesn't feel alien."""
    s = state["summary"]
    color = "#10b981" if s["critical"] == 0 and s["warn"] == 0 else (
        "#f59e0b" if s["critical"] == 0 else "#ef4444")

    issue_rows = []
    for i in state["issues"]:
        sev_color = "#ef4444" if i["severity"] == CRITICAL else "#f59e0b"
        issue_rows.append(f"""
        <tr>
          <td style="padding:8px 12px; vertical-align:top; white-space:nowrap;">
            <span style="background:{sev_color};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">{i['severity']}</span>
          </td>
          <td style="padding:8px 12px;">
            <div style="color:#fff; font-weight:500;">{_html_escape(i['message'])}</div>
            <div style="color:#94a3b8; font-size:12px; margin-top:4px;">{_html_escape(i.get('detail',''))}</div>
          </td>
        </tr>
        """)
    if not issue_rows:
        issue_rows.append("""
        <tr><td colspan="2" style="padding:24px; text-align:center; color:#10b981; font-weight:500;">
          No issues. System is healthy.
        </td></tr>
        """)

    p = state["pipeline"]
    t = state["tables"]
    w = state["watchdog"]
    watchdog_summary = (
        f"{w['last_run'][:16] if w['last_run'] else 'NEVER RUN'}"
        + (f" (healed={w['healed']}, failed={w['failed']})" if w['last_run'] else "")
    )

    return f"""<!doctype html>
    <html><head><meta charset="utf-8"></head>
    <body style="margin:0;padding:0;background:#0f172a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
      <div style="max-width:720px;margin:24px auto;padding:24px;background:#1e293b;border-radius:8px;border-top:4px solid {color};">
        <div style="font-size:11px;letter-spacing:1.5px;color:#94a3b8;font-weight:700;">ALPHA SIGNAL v2 — SYSTEM HEALTH</div>
        <div style="font-size:28px;font-weight:700;color:#fff;margin-top:8px;">{_html_escape(s['verdict'])}</div>
        <div style="font-size:12px;color:#94a3b8;margin-top:4px;">As of {state['as_of'][:16]}</div>

        <table style="width:100%; margin-top:20px; border-collapse:collapse; font-size:13px;">
          <tr><td style="padding:8px 0; color:#94a3b8;">Pipeline last run</td>
              <td style="padding:8px 0; color:#fff; text-align:right;">{_html_escape(p['last_run_date'] or '—')} → {_html_escape(p['last_run_status'] or '—')}</td></tr>
          <tr><td style="padding:8px 0; color:#94a3b8;">Tables</td>
              <td style="padding:8px 0; color:#fff; text-align:right;">{t['fresh']} fresh / {len(t['stale'])} stale / {len(t['outdated'])} outdated</td></tr>
          <tr><td style="padding:8px 0; color:#94a3b8;">Watchdog</td>
              <td style="padding:8px 0; color:#fff; text-align:right;">{_html_escape(watchdog_summary)}</td></tr>
        </table>

        <div style="margin-top:24px;font-size:11px;letter-spacing:1px;color:#94a3b8;font-weight:700;">ISSUES</div>
        <table style="width:100%;margin-top:8px;border-collapse:collapse;border-top:1px solid #334155;">
          {''.join(issue_rows)}
        </table>

        <div style="margin-top:24px;font-size:11px;color:#64748b;">
          Drill down: <a href="{COCKPIT_URL}/system" style="color:#60a5fa;">/system</a> ·
          <a href="{COCKPIT_URL}/" style="color:#60a5fa;">cockpit</a><br>
          Generated by <code style="color:#94a3b8;">tools/health_report.py</code>
        </div>
      </div>
    </body></html>
    """


def format_push_text(state):
    """Short text for ntfy.sh / SMS-equivalent push. ≤200 chars.

    Pushes on EITHER:
      - any CRITICAL issue (existing behaviour), OR
      - Plan 0007 Phase 8: system UHS dropping below 60 (any tier-1 table
        UHS <60 → system geomean falls; user gets alerted before any pick
        based on that stale/broken table reaches morning_brief).
    """
    s = state["summary"]
    critical_issues = [i for i in state["issues"] if i["severity"] == CRITICAL]

    # Plan 0007 Phase 8 — system UHS check
    uhs_alert = _system_uhs_alert()

    if s["critical"] == 0 and not uhs_alert:
        return None  # nothing critical AND system UHS healthy
    head_lines = []
    if s["critical"]:
        head_lines.append(f"⚠ Alpha Signal: {s['critical']} CRITICAL")
    if uhs_alert:
        head_lines.append(uhs_alert)
    body_lines = [f"• {i['message']}" for i in critical_issues[:3]]
    if len(critical_issues) > 3:
        body_lines.append(f"…+{len(critical_issues)-3} more")
    return "\n".join(head_lines + body_lines)


def _system_uhs_alert():
    """Return alert string if system UHS < 60 in the latest snapshot, else None."""
    try:
        from db import read_sql
        df = read_sql(
            """
            SELECT score_pct FROM health_score
            WHERE entity_kind = 'system' AND entity_id = 'SYSTEM'
            ORDER BY snapshot_date DESC LIMIT 1
            """
        )
        if df.empty or df.iloc[0]["score_pct"] is None:
            return None
        score = int(df.iloc[0]["score_pct"])
        if score < 60:
            return f"🔴 System UHS {score} (<60 = AVOID — tier-1 table compromised)"
    except Exception:
        return None
    return None


def _html_escape(s):
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# ─────────────────────── Dispatch ───────────────────────


def send_email(html, subject, urgent=False):
    """Send via the same Gmail SMTP path the daily email uses."""
    gmail_user = os.environ.get("GMAIL_USER")
    gmail_pass = os.environ.get("GMAIL_APP_PASSWORD")
    recipient = os.environ.get("EMAIL_RECIPIENT", gmail_user)
    if not gmail_user or not gmail_pass:
        print("  GMAIL_USER / GMAIL_APP_PASSWORD not set — skipping email.")
        return False

    msg = MIMEMultipart("alternative")
    if urgent:
        subject = f"🚨 URGENT · {subject}"
    msg["Subject"] = subject
    msg["From"] = f"Alpha Signal Health <{gmail_user}>"
    msg["To"] = recipient
    if urgent:
        msg["X-Priority"] = "1"  # gmail/most clients honor this
        msg["Importance"] = "high"
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, recipient, msg.as_string())
        print(f"  Sent {'URGENT ' if urgent else ''}email to {recipient}")
        return True
    except Exception as e:
        print(f"  Email send failed: {e}")
        return False


def send_ntfy(text, urgent=False):
    """Push to ntfy.sh if NTFY_TOPIC is configured. No-op otherwise."""
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("  NTFY_TOPIC not set — skipping ntfy push.")
        return False
    url = f"https://ntfy.sh/{topic}"
    headers = {
        "Title": "Alpha Signal v2",
        "Priority": "urgent" if urgent else "default",
        "Tags": "warning" if urgent else "information_source",
    }
    req = urllib.request.Request(url, data=text.encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"  ntfy push sent → {url} (HTTP {resp.status})")
        return True
    except Exception as e:
        print(f"  ntfy push failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", action="store_true", help="Send daily HTML email brief")
    parser.add_argument("--push", action="store_true", help="Push CRITICAL alerts (URGENT email + ntfy)")
    parser.add_argument("--since-days", type=int, default=1,
                        help="Failure-streak window (default 1)")
    args = parser.parse_args()

    state = gather(since_days=args.since_days)

    # Always print terminal version
    print(format_terminal(state))
    print()

    if args.email:
        subject = f"Alpha Signal Health · {date.today().strftime('%a %d %b')} · {state['summary']['verdict']}"
        send_email(format_email_html(state), subject, urgent=False)

    if args.push and state["summary"]["critical"] > 0:
        push_text = format_push_text(state)
        # URGENT email (works without any extra setup)
        send_email(format_email_html(state),
                   f"Alpha Signal · {state['summary']['critical']} CRITICAL",
                   urgent=True)
        # ntfy push (opt-in via NTFY_TOPIC)
        send_ntfy(push_text, urgent=True)

    # Exit non-zero on CRITICAL so cron mailer flags it independently
    return 1 if state["summary"]["critical"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
