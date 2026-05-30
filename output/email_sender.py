"""
Alpha Signal v2 — Email Sender

Sends daily picks via Gmail SMTP. Builds a rich HTML email from daily_picks +
daily_snapshots + dossiers + regime + daily_changes.

Design goals:
  - Tier-aware layout (LARGE / MID / SMALL sections, matches v2 architecture).
  - Each pick links into the cockpit (/explorer/{sid}) on the same VM.
  - Show signal contributions so the user understands WHY a stock ranked.
  - Keep dossier prose readable (no walls of text).
  - Inline CSS only — Gmail strips <style> blocks.

Requires env vars: GMAIL_USER, GMAIL_APP_PASSWORD, EMAIL_RECIPIENT
Optional:           COCKPIT_BASE_URL  (default: http://140.245.248.166:3000)

Usage:
    python -m output.email_sender            # send today's email
    python -m output.email_sender --dry-run  # build email but don't send
"""

import argparse
import json
import os
import smtplib
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import PROJECT_ROOT
from db import read_sql

COCKPIT_URL = os.environ.get("COCKPIT_BASE_URL", "http://140.245.248.166:3000")
TOP_N_PER_TIER = 5

# ── Color palette (match cockpit dark-on-light email skin) ──
C_BG = "#f5f6f8"
C_CARD = "#ffffff"
C_BORDER = "#e4e7ec"
C_TEXT = "#1a1d29"
C_MUTED = "#6b7280"
C_FAINT = "#9ca3af"
C_GREEN = "#15803d"
C_GREEN_BG = "#dcfce7"
C_RED = "#b91c1c"
C_RED_BG = "#fee2e2"
C_AMBER = "#b45309"
C_AMBER_BG = "#fef3c7"
C_BLUE = "#1d4ed8"
C_PURPLE = "#6b21a8"
C_PURPLE_BG = "#f3e8ff"
C_HEADER_FROM = "#0f172a"
C_HEADER_TO = "#1e293b"

ACTION_STYLES = {
    "BUY":   (C_GREEN, C_GREEN_BG, "🟢"),
    "WATCH": (C_AMBER, C_AMBER_BG, "🟡"),
    "AVOID": (C_RED, C_RED_BG, "🔴"),
    "EXIT":  (C_RED, C_RED_BG, "🔴"),
}

# Signal field → (label, formatter, "is high good" sign).
# Sourced from daily_snapshots (raw signal values), not the legacy daily_picks._adj
# columns which v2's percentile-rank screener leaves at 0.
def _fmt_f_score(v):  return f"{int(v)}/9"
def _fmt_signed(v):   return f"{float(v):+.2f}"
def _fmt_yield(v):    return f"{float(v)*100:.1f}%" if abs(float(v)) < 1 else f"{float(v):.1f}%"
def _fmt_pct_v(v):    return f"{float(v):.0f}%"

SNAPSHOT_SIGNALS = [
    ("piotroski_f",      "F-Score",   _fmt_f_score, +1, 5.0,   9.0),
    ("earnings_yield",   "E/P",       _fmt_yield,   +1, 0.06,  0.20),
    ("consensus_signal", "Consensus", _fmt_signed,  +1, 0.10,  1.00),
    ("promoter_qoq",     "Promoter",  _fmt_signed,  +1, 0.10,  1.00),
    ("cf_accruals",      "Accruals",  _fmt_signed,  +1, 0.20,  1.00),
    ("smart_money",      "Smart$",    _fmt_signed,  +1, 0.20,  1.00),
    ("delivery_pct",     "Delivery",  _fmt_pct_v,   +1, 50.0,  90.0),
    ("mom_12m",          "Mom 12M",   _fmt_signed,  +1, 0.10,  1.00),
    ("sentiment_7d",     "News",      _fmt_signed,  +1, 0.20,  1.00),
]


import math


def _has(x):
    """True iff x is a usable number (not None, not NaN)."""
    if x is None:
        return False
    try:
        return not math.isnan(float(x))
    except (TypeError, ValueError):
        return False


def _fmt_pct(x, decimals=1):
    if not _has(x):
        return "—"
    x = float(x)
    color = C_GREEN if x > 0 else (C_RED if x < 0 else C_MUTED)
    return f'<span style="color:{color};font-weight:600">{x:+.{decimals}f}%</span>'


def _fmt_num(x, decimals=1, suffix=""):
    if not _has(x):
        return "—"
    return f"{float(x):.{decimals}f}{suffix}"


def _fmt_price(x):
    if not _has(x):
        return "—"
    return f"₹{float(x):,.0f}"


def _fmt_mcap(cr):
    if not _has(cr):
        return "—"
    cr = float(cr)
    if cr >= 100_000:
        return f"₹{cr/100_000:.1f}L Cr"
    return f"₹{cr:,.0f} Cr"


def _signal_pills(row):
    """Top 3 strongest snapshot signals (by 'how far past the trigger threshold')."""
    contribs = []
    for col, label, fmt, sign, lo, hi in SNAPSHOT_SIGNALS:
        val = row.get(col)
        if not _has(val):
            continue
        v = float(val)
        # strength: 0 below lo, 1 at hi, capped
        strength = (sign * v - lo) / (hi - lo) if hi > lo else 0
        if strength <= 0:
            continue
        contribs.append((label, fmt(v), min(strength, 1.0)))
    contribs.sort(key=lambda x: x[2], reverse=True)
    top = contribs[:3]
    if not top:
        return ""
    pills = []
    for label, vstr, _strength in top:
        pills.append(
            f'<span style="display:inline-block;background:{C_GREEN_BG};color:{C_GREEN};'
            f'padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;'
            f'margin-right:4px">{label} {vstr}</span>'
        )
    return "".join(pills)


def _action_badge(action, conviction):
    color, bg, icon = ACTION_STYLES.get(action or "", (C_MUTED, "#f3f4f6", "⚪"))
    return (
        f'<span style="display:inline-block;background:{bg};color:{color};'
        f'padding:3px 10px;border-radius:12px;font-size:11px;font-weight:700;'
        f'letter-spacing:0.3px">{icon} {action or "—"}'
        f'{f" · {conviction}" if conviction else ""}</span>'
    )


def _list_html(items, color=C_TEXT):
    if not items:
        return ""
    lis = "".join(f'<li style="margin:3px 0;color:{color}">{i}</li>' for i in items)
    return f'<ul style="margin:4px 0 0;padding-left:18px;font-size:12px;line-height:1.55">{lis}</ul>'


def _build_pick_card(row, dossier, idx):
    sid = row["sid"]
    ticker = row["ticker"] or sid
    name = (row["name"] or "")[:60]
    sector = row["sector"] or "—"
    score = row["final_score"]
    rank = row["rank"]
    # Plan 0007 Phase 5 — per-pick UHS
    uhs_score = row.get("uhs_score")
    uhs_label = row.get("uhs_label")
    uhs_worst = row.get("uhs_worst_dim")

    price = row.get("close_price")
    pe = row.get("pe_ratio")
    pb = row.get("pb_ratio")
    roe = row.get("roe")
    f_score = row.get("piotroski_f")
    earnings_yield = row.get("earnings_yield")
    delivery_pct = row.get("delivery_pct")
    mcap = row.get("market_cap_cr")
    ret_1m = row.get("ret_1m_pct")
    ret_3m = row.get("ret_3m_pct")
    ret_12m = row.get("ret_12m_pct")

    action = (dossier or {}).get("action")
    conviction = (dossier or {}).get("conviction")
    accent_color, _, _ = ACTION_STYLES.get(action or "", (C_MUTED, "", ""))
    target = (dossier or {}).get("target_price")
    stop = (dossier or {}).get("stop_loss")
    upside_html = ""
    if _has(target) and _has(price) and float(price) > 0:
        upside = (float(target) / float(price) - 1) * 100
        upside_html = (
            f'<span style="color:{C_MUTED}">·&nbsp;Target&nbsp;</span>'
            f'<span style="color:{C_TEXT};font-weight:600">{_fmt_price(target)}'
            f'</span> <span style="color:{C_GREEN if upside>0 else C_RED};font-weight:600">'
            f'({upside:+.0f}%)</span>'
        )

    cockpit_link = f"{COCKPIT_URL}/explorer/{sid}"

    # Header row: rank, ticker, score, action badge
    header = f"""
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:6px">
      <tr>
        <td>
          <span style="display:inline-block;background:#f3f4f6;color:{C_MUTED};
                width:22px;height:22px;border-radius:50%;text-align:center;
                line-height:22px;font-size:11px;font-weight:700;margin-right:6px">{rank}</span>
          <a href="{cockpit_link}" style="font-size:17px;font-weight:800;color:{C_TEXT};
                text-decoration:none;letter-spacing:-0.2px">{ticker}</a>
          <span style="color:{C_FAINT};font-size:13px;margin-left:6px">↗</span>
        </td>
        <td align="right" style="vertical-align:middle">
          {_action_badge(action, conviction)}
          <span style="display:inline-block;background:{C_HEADER_FROM};color:#fff;
                padding:3px 10px;border-radius:12px;font-size:11px;font-weight:700;
                margin-left:6px">{score:.2f}</span>
        </td>
      </tr>
    </table>
    <div style="font-size:13px;color:{C_MUTED};margin-bottom:10px">
      {name} · <span style="color:{C_FAINT}">{sector}</span>
    </div>
    """

    stat_row = f"""
    <table cellpadding="0" cellspacing="0" border="0" style="margin-bottom:6px;font-size:12px">
      <tr>
        <td style="padding:2px 18px 2px 0"><span style="color:{C_FAINT}">Price&nbsp;</span>
          <span style="color:{C_TEXT};font-weight:700">{_fmt_price(price)}</span></td>
        <td style="padding:2px 18px 2px 0"><span style="color:{C_FAINT}">1M&nbsp;</span>{_fmt_pct(ret_1m)}</td>
        <td style="padding:2px 18px 2px 0"><span style="color:{C_FAINT}">3M&nbsp;</span>{_fmt_pct(ret_3m)}</td>
        <td style="padding:2px 18px 2px 0"><span style="color:{C_FAINT}">12M&nbsp;</span>{_fmt_pct(ret_12m)}</td>
        <td style="padding:2px 0 2px 0"><span style="color:{C_FAINT}">MCap&nbsp;</span>
          <span style="color:{C_TEXT};font-weight:600">{_fmt_mcap(mcap)}</span></td>
      </tr>
    </table>
    <table cellpadding="0" cellspacing="0" border="0" style="margin-bottom:10px;font-size:12px">
      <tr>
        <td style="padding:2px 18px 2px 0"><span style="color:{C_FAINT}">P/E&nbsp;</span>
          <span style="color:{C_TEXT};font-weight:600">{_fmt_num(pe, 1)}</span></td>
        <td style="padding:2px 18px 2px 0"><span style="color:{C_FAINT}">P/B&nbsp;</span>
          <span style="color:{C_TEXT};font-weight:600">{_fmt_num(pb, 1)}</span></td>
        <td style="padding:2px 18px 2px 0"><span style="color:{C_FAINT}">ROE&nbsp;</span>
          <span style="color:{C_TEXT};font-weight:600">{_fmt_num(roe, 1, "%")}</span></td>
        <td style="padding:2px 18px 2px 0"><span style="color:{C_FAINT}">F&nbsp;</span>
          <span style="color:{C_TEXT};font-weight:600">{f"{int(f_score)}/9" if _has(f_score) else "—"}</span></td>
        <td style="padding:2px 0 2px 0"><span style="color:{C_FAINT}">Deliv&nbsp;</span>
          <span style="color:{C_TEXT};font-weight:600">{_fmt_num(delivery_pct, 0, "%")}</span></td>
      </tr>
    </table>
    """

    # Signal contribution pills
    pills_html = _signal_pills(row)
    pills_block = ""
    if pills_html:
        pills_block = f"""
        <div style="margin:0 0 10px;font-size:11px">
          <span style="color:{C_FAINT};margin-right:4px">drivers:</span>{pills_html}
        </div>
        """

    # Dossier block (if exists)
    dossier_block = ""
    if dossier and dossier.get("thesis"):
        thesis = dossier.get("thesis", "")
        bull = dossier.get("bull_case") or []
        bear = dossier.get("bear_case") or []
        cats = dossier.get("catalysts") or []
        risks = dossier.get("risks") or []
        if isinstance(bull, str): bull = [bull]
        if isinstance(bear, str): bear = [bear]
        if isinstance(cats, str): cats = [cats]
        if isinstance(risks, str): risks = [risks]
        dossier_block = f"""
        <div style="background:{C_PURPLE_BG};border-left:3px solid {C_PURPLE};
              border-radius:0 6px 6px 0;padding:11px 14px;margin-top:6px">
          <div style="font-size:11px;font-weight:700;color:{C_PURPLE};
                margin-bottom:6px;letter-spacing:0.4px">🧠 AI THESIS
            <span style="color:{C_MUTED};font-weight:500;margin-left:6px">{upside_html}</span>
          </div>
          <div style="font-size:12px;color:{C_TEXT};line-height:1.55;margin-bottom:8px">{thesis}</div>
          <table width="100%" cellpadding="0" cellspacing="0" border="0">
            <tr>
              <td valign="top" width="50%" style="padding-right:10px">
                <div style="font-size:11px;font-weight:700;color:{C_GREEN}">BULL</div>
                {_list_html(bull, C_TEXT)}
              </td>
              <td valign="top" width="50%" style="padding-left:10px;border-left:1px solid {C_BORDER}">
                <div style="font-size:11px;font-weight:700;color:{C_RED}">BEAR</div>
                {_list_html(bear, C_TEXT)}
              </td>
            </tr>
            <tr><td colspan="2" style="padding-top:8px"></td></tr>
            <tr>
              <td valign="top" width="50%" style="padding-right:10px">
                <div style="font-size:11px;font-weight:700;color:{C_BLUE}">CATALYSTS</div>
                {_list_html(cats, C_TEXT)}
              </td>
              <td valign="top" width="50%" style="padding-left:10px;border-left:1px solid {C_BORDER}">
                <div style="font-size:11px;font-weight:700;color:{C_AMBER}">RISKS</div>
                {_list_html(risks, C_TEXT)}
              </td>
            </tr>
          </table>
        </div>
        """

    # Plan 0007 Phase 5 — UHS footer line
    uhs_footer = ""
    if uhs_score is not None:
        if uhs_score >= 80:
            uhs_emoji = "🟢"
            uhs_color = C_GREEN
        elif uhs_score >= 60:
            uhs_emoji = "🟡"
            uhs_color = C_AMBER
        else:
            uhs_emoji = "🔴"
            uhs_color = C_RED
        worst_text = f" · weakest dim: {uhs_worst}" if uhs_worst else ""
        uhs_footer = (
            f'<div style="font-size:10.5px;color:{C_MUTED};'
            f'padding-top:8px;margin-top:6px;border-top:1px solid {C_BORDER}">'
            f'{uhs_emoji} <b style="color:{uhs_color}">UHS {uhs_score} · {uhs_label or ""}</b>'
            f'{worst_text}'
            f'</div>'
        )

    return f"""
    <div style="background:{C_CARD};border:1px solid {C_BORDER};
          border-left:4px solid {accent_color};border-radius:8px;
          padding:16px 18px;margin-bottom:12px">
      {header}
      {stat_row}
      {pills_block}
      {dossier_block}
      {uhs_footer}
    </div>
    """


def _build_html():
    today_iso = date.today().isoformat()
    today_human = date.today().strftime("%A, %d %B %Y")

    # Picks + fundamentals + snapshot signals + price metrics
    picks = read_sql("""
        SELECT
          dp.sid, dp.final_score, dp.rank, dp.cap_tier, dp.sector,
          dp.uhs_score, dp.uhs_label, dp.uhs_worst_dim,
          s.ticker, s.name, s.pe_ratio, s.pb_ratio, s.roe, s.market_cap_cr,
          ds.close_price, ds.piotroski_f, ds.earnings_yield, ds.delivery_pct,
          ds.consensus_signal, ds.promoter_qoq, ds.cf_accruals, ds.smart_money,
          ds.mom_6m, ds.mom_12m, ds.sentiment_7d
        FROM daily_picks dp
        JOIN stocks s ON dp.sid = s.sid
        LEFT JOIN daily_snapshots ds ON dp.sid = ds.sid
              AND ds.snapshot_date = dp.pick_date
        WHERE dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)
          AND (dp.integrity_status IS NULL OR dp.integrity_status != 'FAIL')
          -- Plan 0007 Phase 5 — UHS pick gate. Picks with score < 60 → AVOID
          -- band: shown nowhere in action_queue/morning_brief/email. NULL
          -- fallback covers rows pre-dating Phase 5; once UHS is universal
          -- the NULL branch becomes dead code (Phase 8 will remove it).
          AND (dp.uhs_score IS NULL OR dp.uhs_score >= 60)
        ORDER BY dp.cap_tier, dp.rank
    """)

    if picks.empty:
        return "<p>No picks today.</p>", 0

    # Latest price returns per sid (1M/3M/12M)
    returns = read_sql("""
        WITH latest AS (
          SELECT sid, MAX(date) AS d FROM stock_prices GROUP BY sid
        ),
        cur AS (
          SELECT sp.sid, sp.date, sp.close FROM stock_prices sp
          JOIN latest USING(sid) WHERE sp.date = latest.d
        )
        SELECT cur.sid,
               cur.close AS close_now,
               (SELECT close FROM stock_prices p
                  WHERE p.sid=cur.sid AND p.date <= date(cur.date,'-1 month')
                  ORDER BY p.date DESC LIMIT 1) AS close_1m,
               (SELECT close FROM stock_prices p
                  WHERE p.sid=cur.sid AND p.date <= date(cur.date,'-3 months')
                  ORDER BY p.date DESC LIMIT 1) AS close_3m,
               (SELECT close FROM stock_prices p
                  WHERE p.sid=cur.sid AND p.date <= date(cur.date,'-12 months')
                  ORDER BY p.date DESC LIMIT 1) AS close_12m
        FROM cur
    """)
    if not returns.empty:
        returns["ret_1m_pct"] = (returns["close_now"] / returns["close_1m"] - 1) * 100
        returns["ret_3m_pct"] = (returns["close_now"] / returns["close_3m"] - 1) * 100
        returns["ret_12m_pct"] = (returns["close_now"] / returns["close_12m"] - 1) * 100
        picks = picks.merge(
            returns[["sid", "ret_1m_pct", "ret_3m_pct", "ret_12m_pct"]],
            on="sid", how="left",
        )

    # Regime
    regime = read_sql("SELECT * FROM regime_state WHERE id = 1")
    regime_html = ""
    if not regime.empty:
        r = regime.iloc[0]
        regime_color = {
            "PANIC": C_RED, "STRESS": C_AMBER, "CAUTION": C_AMBER,
            "NEUTRAL": C_BLUE, "EUPHORIA": C_GREEN,
        }.get(r["regime"], C_BLUE)
        regime_html = f"""
        <div style="background:{C_CARD};border:1px solid {C_BORDER};border-radius:8px;
              padding:12px 16px;margin-bottom:14px;font-size:13px">
          <span style="display:inline-block;background:{regime_color};color:#fff;
                padding:3px 10px;border-radius:12px;font-size:11px;font-weight:700;
                margin-right:8px">{r["regime"]}</span>
          <span style="color:{C_MUTED}">VIX</span>
          <span style="color:{C_TEXT};font-weight:700">{r["vix_latest"]:.1f}</span>
          <span style="color:{C_FAINT}">·</span>
          <span style="color:{C_MUTED};margin-left:6px">Allocation</span>
          <span style="color:{C_TEXT};font-weight:600">L {r["alloc_large"]:.0%}</span>
          <span style="color:{C_FAINT}">/</span>
          <span style="color:{C_TEXT};font-weight:600">M {r["alloc_mid"]:.0%}</span>
          <span style="color:{C_FAINT}">/</span>
          <span style="color:{C_TEXT};font-weight:600">S {r["alloc_small"]:.0%}</span>
        </div>
        """

    # Today's changes summary
    changes_summary = read_sql("""
        SELECT change_type, COUNT(*) AS c
        FROM daily_changes
        WHERE change_date = (SELECT MAX(change_date) FROM daily_changes)
        GROUP BY change_type
    """)
    changes_dict = dict(zip(changes_summary["change_type"], changes_summary["c"])) if not changes_summary.empty else {}
    changes_html = ""
    if changes_dict:
        chips = []
        # Skip raw UPGRADE/DOWNGRADE counts — those are rank-shifts on every stock, noise.
        for label, key, color, bg in [
            ("New entries", "ENTRY", C_GREEN, C_GREEN_BG),
            ("Exits", "EXIT", C_RED, C_RED_BG),
            ("Regime change", "REGIME_CHANGE", C_PURPLE, C_PURPLE_BG),
            ("Signals fired", "SIGNAL_FIRED", C_BLUE, "#dbeafe"),
        ]:
            if changes_dict.get(key):
                chips.append(
                    f'<span style="display:inline-block;background:{bg};color:{color};'
                    f'padding:3px 9px;border-radius:10px;font-size:11px;font-weight:600;'
                    f'margin-right:6px">{label}: {changes_dict[key]}</span>'
                )
        if chips:
            changes_html = f"""
            <div style="margin-bottom:14px">
              <div style="font-size:11px;font-weight:700;color:{C_MUTED};
                    letter-spacing:0.4px;margin-bottom:6px">SINCE YESTERDAY</div>
              {"".join(chips)}
            </div>
            """

    # Load dossiers
    dossiers_by_sid = {}
    dossier_path = PROJECT_ROOT / "output" / f"dossiers_{today_iso}.json"
    if dossier_path.exists():
        try:
            with open(dossier_path) as f:
                for d in json.load(f):
                    if "sid" in d:
                        dossiers_by_sid[d["sid"]] = d
        except (json.JSONDecodeError, OSError):
            pass

    # Per-tier sections
    tier_blocks = []
    tier_meta = {
        "LARGE": ("Large Cap", regime.iloc[0]["alloc_large"] if not regime.empty else None),
        "MID":   ("Mid Cap",   regime.iloc[0]["alloc_mid"]   if not regime.empty else None),
        "SMALL": ("Small Cap", regime.iloc[0]["alloc_small"] if not regime.empty else None),
    }
    for tier_key, (tier_name, alloc) in tier_meta.items():
        tier_picks = picks[picks["cap_tier"] == tier_key].head(TOP_N_PER_TIER)
        if tier_picks.empty:
            continue
        cards = "".join(
            _build_pick_card(row, dossiers_by_sid.get(row["sid"]), i)
            for i, (_, row) in enumerate(tier_picks.iterrows())
        )
        alloc_html = (
            f'<span style="background:{C_HEADER_FROM};color:#fff;padding:2px 8px;'
            f'border-radius:10px;font-size:11px;font-weight:700;margin-left:8px">'
            f'{alloc:.0%} alloc</span>' if alloc is not None else ""
        )
        tier_blocks.append(f"""
        <div style="margin-top:18px;margin-bottom:6px">
          <span style="font-size:14px;font-weight:800;color:{C_TEXT};
                letter-spacing:0.5px;text-transform:uppercase">{tier_name}</span>
          <span style="color:{C_FAINT};font-size:12px;margin-left:6px">
            top {min(TOP_N_PER_TIER, len(tier_picks))}</span>
          {alloc_html}
        </div>
        {cards}
        """)

    cockpit_button = f"""
    <a href="{COCKPIT_URL}/" style="display:inline-block;background:#fff;color:{C_HEADER_FROM};
          padding:8px 18px;border-radius:20px;text-decoration:none;
          font-size:13px;font-weight:700;margin-top:8px">Open Cockpit →</a>
    """

    header = f"""
    <div style="background:linear-gradient(135deg,{C_HEADER_FROM},{C_HEADER_TO});
          color:#fff;padding:24px 28px;border-radius:12px 12px 0 0">
      <div style="font-size:11px;font-weight:600;letter-spacing:1.5px;
            opacity:0.7;text-transform:uppercase">Alpha Signal v2 · Daily Brief</div>
      <h1 style="margin:4px 0 0;font-size:22px;font-weight:800;letter-spacing:-0.3px">
        {today_human}</h1>
      {cockpit_button}
    </div>
    """

    footer = f"""
    <div style="border-top:1px solid {C_BORDER};margin-top:18px;padding-top:14px;
          font-size:11px;color:{C_FAINT};text-align:center">
      Generated {datetime.now().strftime("%H:%M IST")} · {len(picks)} stocks scored
      · <a href="{COCKPIT_URL}/" style="color:{C_BLUE};text-decoration:none">Cockpit</a>
      · <a href="{COCKPIT_URL}/explorer" style="color:{C_BLUE};text-decoration:none">Explorer</a>
      · <a href="{COCKPIT_URL}/signals" style="color:{C_BLUE};text-decoration:none">Signals</a>
      · <a href="{COCKPIT_URL}/system" style="color:{C_BLUE};text-decoration:none">System</a>
    </div>
    """

    body = f"""
    <html><body style="font-family:-apple-system,'Segoe UI',Arial,sans-serif;
          background:{C_BG};margin:0;padding:20px;color:{C_TEXT}">
      <div style="max-width:680px;margin:0 auto;background:{C_BG};">
        {header}
        <div style="background:{C_BG};padding:18px 22px 22px">
          {regime_html}
          {changes_html}
          {"".join(tier_blocks)}
          {footer}
        </div>
      </div>
    </body></html>
    """
    return body, len(picks)


def send_email(dry_run=False):
    html, pick_count = _build_html()
    today = date.today().isoformat()
    print(f"Email: {pick_count} picks for {today}")

    local_path = PROJECT_ROOT / "output" / f"email_{today}.html"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(html)
    print(f"  Saved local copy: {local_path} ({len(html):,} bytes)")

    if dry_run:
        print("  Dry run — not sending.")
        return 1

    gmail_user = os.environ.get("GMAIL_USER")
    gmail_pass = os.environ.get("GMAIL_APP_PASSWORD")
    recipient = os.environ.get("EMAIL_RECIPIENT", gmail_user)

    if not gmail_user or not gmail_pass:
        print("  GMAIL_USER / GMAIL_APP_PASSWORD not set — skipping send.")
        return 0

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Alpha Signal · {date.today().strftime('%a %d %b')} · Daily Brief"
    msg["From"] = f"Alpha Signal <{gmail_user}>"
    msg["To"] = recipient
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, recipient, msg.as_string())
        print(f"  Sent to {recipient}")
        return 1
    except Exception as e:
        print(f"  Send failed: {e}")
        return 0


def compute(dry_run=False):
    return send_email(dry_run=dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    send_email(dry_run=args.dry_run)
