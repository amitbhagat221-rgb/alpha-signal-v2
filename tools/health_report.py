"""
Alpha Signal v2 — Daily Health Report

The single answer to "is the system healthy?", organised as five questions
(checks.THEMES): did everything run · did the data arrive · is the data right ·
can today's picks be trusted · is the model still sound.

This module only renders and delivers. checks.report.gather() builds the ONE state
(facts per area from checks/system.py → one issue list, a five-row scorecard, a
catalog of every check). Three surfaces render it here, and the MCP and the ops
Health page read the same state — none of them derives its own:

  - terminal: `/catchup` block at the top of every session
  - email:    daily HTML brief at 04:00 UTC
  - push:     ntfy.sh + URGENT-prefixed email on CRITICAL only

Usage:
    python -m tools.health_report                   # terminal only
    python -m tools.health_report --catalog         # every check, by question, with its status
    python -m tools.health_report --email           # send daily brief
    python -m tools.health_report --push            # push CRITICAL only
    python -m tools.health_report --email --push    # cron: daily run

Env vars:
    GMAIL_USER, GMAIL_APP_PASSWORD, EMAIL_RECIPIENT — for --email and URGENT push
    NTFY_TOPIC — optional, enables ntfy.sh push for CRITICAL. Pick a unique
                 hard-to-guess string; install the ntfy.sh phone app and subscribe.
"""

import argparse
import os
import smtplib
import sys
import urllib.request
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from checks import CRITICAL, INFO, SEVERITY_MEANING, THEMES, WARN, history, report
from checks.report import gather  # noqa: F401  (the one state; re-exported for the MCP, the ops page, the org desks)


# ─────────────────────── Formatting ───────────────────────

_MARK = {CRITICAL: "❌", WARN: "⚠", "BROKEN": "❌", "WATCH": "⚠", "OK": "✓"}


def _counts(row):
    """'1 to act on today, 2 to look at' for a scorecard row ('' when clean)."""
    return ", ".join(filter(None, [f"{row['critical']} to act on today" if row["critical"] else "",
                                   f"{row['warn']} to look at" if row["warn"] else ""]))


def _age(issue):
    """' · new' / ' · day 12' / ' · standing, day 40' — how long an issue has been firing."""
    if issue["days"] <= 1:
        return " · new"
    return f" · standing, day {issue['days']}" if issue["standing"] else f" · day {issue['days']}"


def _by_theme(issues):
    """[(question, [issues])] for the questions that have any, in THEMES order."""
    return [(THEMES[t][0], [i for i in issues if i["theme"] == t])
            for t in THEMES if any(i["theme"] == t for i in issues)]


def format_terminal(state):
    """Plain-text block for /catchup: the five answers, then the issues under
    their question — what was found, the evidence, what to do first."""
    lines = [f"━━━ SYSTEM HEALTH  ({state['as_of'][:16]})  {state['summary']['verdict']}"]
    for row in state["scorecard"]:
        lines.append(f"  {_MARK[row['status']]} {row['question']:<31}"
                     + " · ".join(filter(None, [_counts(row), row["facts"]])))
    for question, issues in _by_theme(state["issues"]):
        lines += ["", question.upper()]
        for i in issues:
            lines.append(f"  {_MARK[i['severity']]} {i['message']}   [{i['id']}{_age(i)}]")
            if i["detail"]:
                lines.append(f"      {i['detail'][:200]}")
            lines.append(f"      → {i['fix']}")
    if not state["issues"]:
        lines += ["", "No issues. System is healthy."]
    lines += ["", f"❌ = {SEVERITY_MEANING[CRITICAL]} · ⚠ = {SEVERITY_MEANING[WARN]}",
              "Every check and what it means: python -m tools.health_report --catalog",
              "━" * 80]
    return "\n".join(lines)


def format_catalog(state):
    """Every check the system runs, by question, with its status right now."""
    rows = report.catalog(state)
    lines = [f"━━━ WHAT WE CHECK  ({len(rows)} checks, as of {state['as_of'][:16]})",
             "  ✓ passing · ❌ act today · ⚠ look this week · · firing but tolerated (no action)"]
    for theme, (question, covers) in THEMES.items():
        mine = [r for r in rows if r["theme"] == theme]
        lines += ["", f"{question.upper()}  — {covers}"]
        for r in mine:
            mark = {CRITICAL: "❌", WARN: "⚠", INFO: "·"}.get(r["status"], "✓")
            n = f" ({r['n_checks']} checks)" if r["n_checks"] else ""
            lines.append(f"  {mark} {r['code']}{n}: {r['when']}")
            lines.append(f"      why: {r['why']}")
            lines.append(f"      severity: {r['severity']}")
            if r["failing"]:
                lines.append(f"      now: {'; '.join(str(f) for f in r['failing'][:6])[:200]}")
            elif r["tracked_since"]:
                lines.append(f"      last fired: {r['last_fired'] or 'not since tracking began ' + r['tracked_since']}")
    lines.append("━" * 80)
    return "\n".join(lines)


def format_email_html(state):
    """HTML email body. Reuses the dark cockpit palette so it doesn't feel alien."""
    from output.email_sender import COCKPIT_URL, OPS_URL
    s = state["summary"]
    color = "#ef4444" if s["critical"] else "#f59e0b" if s["warn"] else "#10b981"
    tone = {"BROKEN": "#ef4444", "WATCH": "#f59e0b", "OK": "#10b981", CRITICAL: "#ef4444", WARN: "#f59e0b"}
    esc = _html_escape

    score_rows = "".join(f"""
          <tr>
            <td style="padding:7px 0;width:18px;color:{tone[r['status']]};font-weight:700;">{_MARK[r['status']]}</td>
            <td style="padding:7px 8px 7px 0;color:#fff;font-weight:600;white-space:nowrap;">{esc(r['question'])}</td>
            <td style="padding:7px 0;color:#94a3b8;font-size:12px;">{esc(' · '.join(filter(None, [_counts(r), r['facts']])))}</td>
          </tr>""" for r in state["scorecard"])

    sections = []
    for question, issues in _by_theme(state["issues"]):
        rows = "".join(f"""
          <tr>
            <td style="padding:10px 12px 10px 0;vertical-align:top;white-space:nowrap;">
              <span style="background:{tone[i['severity']]};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">{i['severity']}</span>
            </td>
            <td style="padding:10px 0;border-bottom:1px solid #334155;">
              <div style="color:#fff;font-weight:500;">{esc(i['message'])}</div>
              <div style="color:#94a3b8;font-size:12px;margin-top:4px;">{esc(i['detail'])}</div>
              <div style="color:#cbd5e1;font-size:12px;margin-top:6px;"><b>Why it matters:</b> {esc(i['why'])}</div>
              <div style="color:#cbd5e1;font-size:12px;margin-top:2px;"><b>Do first:</b> {esc(i['fix'])}</div>
              <div style="color:#64748b;font-size:10px;margin-top:4px;font-family:monospace;">{esc(i['id'] + _age(i))}</div>
            </td>
          </tr>""" for i in issues)
        sections.append(f"""
        <div style="margin-top:24px;font-size:11px;letter-spacing:1px;color:#94a3b8;font-weight:700;">{esc(question.upper())}</div>
        <table style="width:100%;margin-top:6px;border-collapse:collapse;border-top:1px solid #334155;">{rows}
        </table>""")
    if not sections:
        sections.append("""
        <div style="padding:24px;text-align:center;color:#10b981;font-weight:500;">No issues. System is healthy.</div>""")

    return f"""<!doctype html>
    <html><head><meta charset="utf-8"></head>
    <body style="margin:0;padding:0;background:#0f172a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
      <div style="max-width:720px;margin:24px auto;padding:24px;background:#1e293b;border-radius:8px;border-top:4px solid {color};">
        <div style="font-size:11px;letter-spacing:1.5px;color:#94a3b8;font-weight:700;">ALPHA SIGNAL v2 — SYSTEM HEALTH</div>
        <div style="font-size:28px;font-weight:700;color:#fff;margin-top:8px;">{esc(s['verdict'])}</div>
        <div style="font-size:12px;color:#94a3b8;margin-top:4px;">As of {state['as_of'][:16]}</div>

        <table style="width:100%;margin-top:20px;border-collapse:collapse;font-size:13px;">{score_rows}
        </table>
        {''.join(sections)}

        <div style="margin-top:24px;font-size:11px;color:#64748b;line-height:1.6;">
          CRITICAL = {esc(SEVERITY_MEANING[CRITICAL])}.<br>WARN = {esc(SEVERITY_MEANING[WARN])}.<br>
          Every check and what it means: <a href="{OPS_URL}/system" style="color:#60a5fa;">Health Center</a> ·
          <a href="{COCKPIT_URL}/" style="color:#60a5fa;">cockpit</a>
        </div>
      </div>
    </body></html>
    """


def format_push_text(state):
    """Short text for the ntfy.sh push: the CRITICAL issues, or None when there are none."""
    critical = [i for i in state["issues"] if i["severity"] == CRITICAL]
    if not critical:
        return None
    body = [f"• {i['message']}" for i in critical[:3]]
    if len(critical) > 3:
        body.append(f"…+{len(critical) - 3} more")
    return "\n".join([f"⚠ Alpha Signal: {len(critical)} CRITICAL"] + body)


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
    parser.add_argument("--catalog", action="store_true",
                        help="List every check by question, with what it means and its status now")
    args = parser.parse_args()

    state = gather()

    # Always print terminal version
    print(format_catalog(state) if args.catalog else format_terminal(state))
    print()

    if args.email:
        subject = f"Alpha Signal Health · {date.today().strftime('%a %d %b')} · {state['summary']['verdict']}"
    try:
        history.record(report.records(state))
    except Exception as e:                          # noqa: BLE001 — history must never break the report
        print(f"  health history not recorded: {type(e).__name__}: {e}")
        send_email(format_email_html(state), subject, urgent=False)

    if args.push and state["summary"]["critical"] > 0:
        # URGENT email (works without any extra setup)
        send_email(format_email_html(state),
                   f"Alpha Signal · {state['summary']['critical']} CRITICAL",
                   urgent=True)
        # ntfy push (opt-in via NTFY_TOPIC)
        send_ntfy(format_push_text(state), urgent=True)

    # Exit non-zero on CRITICAL so cron mailer flags it independently
    return 1 if state["summary"]["critical"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
