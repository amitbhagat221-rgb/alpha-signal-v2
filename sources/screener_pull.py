"""
Alpha Signal v2 — Screener.in Premium fundamentals pull (F1.1)

Pulls Excel exports from Screener.in Premium and lands them in long format.

Two auth paths, both end up populating ~/.cache/screener_cookie.json:

  (A) Auto-login from env vars — if your Screener account accepts
      username+password (separate from Google OAuth):
          source ~/alpha-signal/run_pipeline.sh
          python -m sources.screener_pull --login
      Reads SCREENER_USERNAME and SCREENER_PASSWORD, POSTs to /login/,
      saves the resulting session cookie. Re-run anytime to refresh.

  (B) Manual cookie export — if your account is Google-OAuth-only and
      password login fails:
        1. Log in at https://www.screener.in/ in a browser.
        2. DevTools → Application → Cookies → screener.in.
        3. Copy `sessionid` (and optionally `csrftoken`).
        4. Save as JSON to ~/.cache/screener_cookie.json:
              {"sessionid": "...", "csrftoken": "..."}
           chmod 600 ~/.cache/screener_cookie.json

When the cookie expires the script raises PermissionError and stops.
Run `--login` again (path A) or re-extract (path B).

Reads:  ~/.cache/screener_cookie.json, stocks (for sid → ticker mapping)
Writes: fundamentals_screener (long format), screener_pull_errors

Usage:
    python -m sources.screener_pull --login                # auto-login (A)
    python -m sources.screener_pull --check-cookie         # validate auth only
    python -m sources.screener_pull --sid RELI             # one stock
    python -m sources.screener_pull --sid RELI --dry-run   # parse but don't write
    python -m sources.screener_pull --tier LARGE           # all large caps
    python -m sources.screener_pull --universe             # all 2,448
"""

import argparse
import io
import json
import os
import random
import re
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from db import get_db, insert_df, read_sql, upsert_df

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

COOKIE_FILE = Path.home() / ".cache" / "screener_cookie.json"
HOME_URL = "https://www.screener.in/"
LOGIN_URL = "https://www.screener.in/login/"
COMPANY_URL = "https://www.screener.in/company/{ticker}/"
COMPANY_CONSOLIDATED_URL = "https://www.screener.in/company/{ticker}/consolidated/"
EXPORT_URL_BASE = "https://www.screener.in"  # form action is relative

# Rate-limit policy. Conservative — Screener has banned accounts for aggressive
# scraping. Numbers tuned for "looks like a researcher refreshing the page",
# not a bot. Inter-stock delay is randomized to avoid mechanical patterns.
DELAY_BETWEEN_STOCKS = (2.5, 4.0)  # seconds — uniform random in this range
DELAY_BETWEEN_STEPS = (0.5, 1.2)   # seconds — between page GET and export POST
BACKOFF_ON_429 = 60.0              # seconds to wait if rate-limited

# Section header (col 0 in Data Sheet) → period_type for rows that follow.
# 'Quarters' starts a quarterly section; everything else is annual fiscal.
SECTION_TO_PERIOD_TYPE = {
    "PROFIT & LOSS": "annual",
    "QUARTERS": "quarterly",
    "BALANCE SHEET": "annual",
    "CASH FLOW:": "annual",
    "DERIVED:": "annual",
}


def load_cookies() -> dict:
    if not COOKIE_FILE.exists():
        raise FileNotFoundError(
            f"No cookie file at {COOKIE_FILE}. "
            "See module docstring for setup."
        )
    cookies = json.loads(COOKIE_FILE.read_text())
    if "sessionid" not in cookies:
        raise ValueError(f"{COOKIE_FILE} missing 'sessionid' key.")
    return cookies


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "*/*"})
    for name, value in load_cookies().items():
        s.cookies.set(name, value, domain="www.screener.in")
    return s


def do_login() -> tuple[bool, str]:
    """Auto-login via env vars. POST credentials to /login/, save cookies.

    Returns (success, detail). On success, ~/.cache/screener_cookie.json
    is written with sessionid + csrftoken. Caller can then call
    make_session() / check_auth() as normal.
    """
    user = os.environ.get("SCREENER_USERNAME")
    pwd = os.environ.get("SCREENER_PASSWORD")
    if not user or not pwd:
        return False, (
            "SCREENER_USERNAME / SCREENER_PASSWORD not set in env. "
            "Did you `source ~/alpha-signal/run_pipeline.sh`?"
        )

    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "text/html,*/*"})

    # Step 1: GET login page to receive csrftoken cookie + form's csrfmiddlewaretoken.
    r = s.get(LOGIN_URL, timeout=15)
    if r.status_code != 200:
        return False, f"GET {LOGIN_URL} returned HTTP {r.status_code}"
    csrf_form = re.search(
        r'name=["\']csrfmiddlewaretoken["\']\s+value=["\']([^"\']+)', r.text
    )
    if not csrf_form:
        return False, "could not find csrfmiddlewaretoken on login page"
    csrf_token = csrf_form.group(1)

    # Step 2: POST credentials. Django CSRF requires Referer header on POST.
    r2 = s.post(
        LOGIN_URL,
        data={
            "csrfmiddlewaretoken": csrf_token,
            "username": user,
            "password": pwd,
            "next": "/",
        },
        headers={"Referer": LOGIN_URL},
        timeout=15,
        allow_redirects=False,
    )

    # Successful login: 302 to / (or /dash/). Failure: 200 with form re-rendered
    # and an error message somewhere in the body.
    if r2.status_code in (301, 302):
        loc = r2.headers.get("location", "")
        if "/login" in loc.lower():
            return False, f"login refused (redirected back to {loc})"
        # Step 3: persist the resulting cookies.
        cookies = {
            c.name: c.value
            for c in s.cookies
            if c.name in ("sessionid", "csrftoken")
        }
        if "sessionid" not in cookies:
            return False, (
                f"redirect to {loc} but no sessionid in response — "
                "likely Google-OAuth-only account; use manual cookie path"
            )
        COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
        COOKIE_FILE.write_text(json.dumps(cookies, indent=2))
        try:
            COOKIE_FILE.chmod(0o600)
        except OSError:
            pass
        return True, f"saved sessionid (+csrftoken) to {COOKIE_FILE}"

    # Status 200 = form re-rendered with error.
    body = r2.text.lower()
    if "google" in body and ("oauth" in body or "sign in with" in body):
        return False, "account is Google-OAuth-only; use manual cookie path (B)"
    if "incorrect" in body or "invalid" in body:
        return False, "credentials rejected by Screener"
    return False, f"unexpected response (HTTP {r2.status_code}); login likely failed"


def check_auth(s: requests.Session) -> tuple[bool, str]:
    """Hit homepage and look for logged-in markers. Returns (ok, detail)."""
    r = s.get(HOME_URL, timeout=15, allow_redirects=False)
    if r.status_code != 200:
        return False, f"HTTP {r.status_code} on /"
    text = r.text.lower()
    # Logged-in homepage shows "logout" link; logged-out shows "login".
    if "logout" in text or "/account/" in text:
        return True, "found logged-in marker"
    if "/login/" in text and "logout" not in text:
        return False, "homepage shows login link only"
    return False, "could not determine auth state from homepage"


def fetch_export(s: requests.Session, ticker: str) -> tuple[bytes, str]:
    """Download Excel export for a single stock. Returns (xlsx_bytes, basis).

    Two-step: GET the company page to find the per-stock export form action
    (which contains a numeric export ID unique to that stock + view), then
    POST to that URL with csrfmiddlewaretoken from session cookies.

    Tries /consolidated/ first (more comprehensive — includes subsidiaries);
    falls back to standalone (/company/{ticker}/) if /consolidated/ 404s.

    Raises PermissionError on cookie expiry, RuntimeError on parse failures.
    """
    last_err = None
    for view, page_url in [
        ("consolidated", COMPANY_CONSOLIDATED_URL.format(ticker=ticker)),
        ("standalone", COMPANY_URL.format(ticker=ticker)),
    ]:
        page = s.get(page_url, timeout=15, allow_redirects=False)
        if page.status_code in (301, 302):
            loc = page.headers.get("location", "")
            if "/login/" in loc:
                raise PermissionError(f"redirected to {loc} — cookie expired")
            last_err = f"{view}: redirected to {loc}"
            continue
        if page.status_code == 404:
            last_err = f"{view}: page 404"
            continue
        if page.status_code != 200:
            last_err = f"{view}: page HTTP {page.status_code}"
            continue

        # Screener puts the export endpoint on a button via HTML5 `formaction=`,
        # not on the parent <form>'s `action=` attribute.
        action_match = re.search(
            r'formaction=["\'](/user/company/export/\d+/)["\']',
            page.text,
        )
        if not action_match:
            last_err = f"{view}: no export form on page (Premium not active?)"
            continue
        export_path = action_match.group(1)
        export_url = EXPORT_URL_BASE + export_path

        csrf = s.cookies.get("csrftoken")
        if not csrf:
            raise PermissionError("no csrftoken in cookie jar — re-login")

        # Pause briefly between page-load and export-POST to look human.
        time.sleep(random.uniform(*DELAY_BETWEEN_STEPS))

        post = s.post(
            export_url,
            data={"csrfmiddlewaretoken": csrf},
            headers={"Referer": page_url},
            timeout=30,
            allow_redirects=False,
        )
        if post.status_code == 429:
            # Honor server's back-off if Retry-After is set; else fixed.
            retry_after = post.headers.get("retry-after")
            wait_s = float(retry_after) if retry_after and retry_after.isdigit() else BACKOFF_ON_429
            raise RuntimeError(
                f"HTTP 429 rate-limited; would back off {wait_s}s. "
                "Stopping run — try again later."
            )
        if post.status_code in (401, 403):
            raise PermissionError(
                f"export POST returned HTTP {post.status_code} — likely "
                "Premium subscription not active or cookie expired"
            )
        if post.status_code in (301, 302):
            loc = post.headers.get("location", "")
            if "/login/" in loc:
                raise PermissionError(f"redirected to {loc} — cookie expired")
            last_err = f"{view}: POST redirected to {loc}"
            continue
        if post.status_code != 200:
            last_err = f"{view}: POST HTTP {post.status_code}"
            continue
        if not post.content or not post.content.startswith(b"PK"):
            # Not an xlsx (PK is ZIP magic) — likely an HTML error page
            last_err = f"{view}: response not xlsx (got {post.content[:30]!r})"
            continue
        return post.content, view

    raise RuntimeError(f"both consolidated and standalone failed: {last_err}")


def parse_export(xls_bytes: bytes, sid: str) -> pd.DataFrame:
    """Parse Screener Excel "Data Sheet" tab into long format.

    The Data Sheet is structured as:
        Row N:    SECTION HEADER  (e.g. 'PROFIT & LOSS', 'Quarters', 'BALANCE SHEET',
                                   'CASH FLOW:', 'DERIVED:')
        Row N+1:  Report Date  | <date> | <date> | ...   (defines period columns)
        Row N+2..M:  Line Item  | val   | val   | ...
        Blank row → end of section.

    The section header determines period_type ('annual' vs 'quarterly').
    Other tabs (Profit & Loss, Quarters, Balance Sheet, Cash Flow,
    Customization) duplicate this data with broken column headers — we ignore
    them.
    """
    df = pd.read_excel(
        io.BytesIO(xls_bytes),
        sheet_name="Data Sheet",
        engine="openpyxl",
        header=None,
    )
    fetched_at = datetime.now().isoformat(timespec="seconds")
    rows = []
    current_period_type = None
    current_dates: list[str | None] = []

    for _, row in df.iterrows():
        cell0 = row.iloc[0]
        col0 = str(cell0).strip() if pd.notna(cell0) else ""

        # Section header? (always alone in column 0, all-caps mostly)
        section_key = col0.upper().rstrip(":")
        # Match exact section names rather than substring.
        matched_section = None
        for k, v in SECTION_TO_PERIOD_TYPE.items():
            if section_key == k.rstrip(":"):
                matched_section = v
                break
        if matched_section is not None:
            current_period_type = matched_section
            current_dates = []  # reset until next Report Date
            continue

        # Report Date row defines the period columns for this section.
        if col0.lower() == "report date" and current_period_type is not None:
            dates = []
            for v in row.iloc[1:]:
                if pd.notna(v):
                    try:
                        dates.append(pd.Timestamp(v).strftime("%Y-%m-%d"))
                    except (ValueError, TypeError):
                        dates.append(None)
                else:
                    dates.append(None)
            current_dates = dates
            continue

        # Data row: needs a line item label, a known section, and known dates.
        if not col0 or current_period_type is None or not current_dates:
            continue
        # Skip if col0 looks like another section we don't handle (e.g. PRICE:)
        if col0.upper().rstrip(":") in {"PRICE", "META"}:
            continue

        for date_str, val in zip(current_dates, row.iloc[1:]):
            if date_str is None or pd.isna(val):
                continue
            try:
                fval = float(val)
            except (ValueError, TypeError):
                continue
            rows.append(
                {
                    "sid": sid,
                    "period_end": date_str,
                    "period_type": current_period_type,
                    "line_item": col0,
                    "value": fval,
                    "filing_date": None,
                    "fetched_at": fetched_at,
                }
            )

    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    # Dedup defensively — same line item should not appear twice in a section.
    out = out.drop_duplicates(
        subset=["sid", "period_end", "period_type", "line_item"], keep="last"
    )
    return out


def log_error(
    sid: str | None, ticker: str | None, error_type: str, message: str,
    http_status: int | None = None,
):
    df = pd.DataFrame(
        [
            {
                "sid": sid,
                "ticker": ticker,
                "error_type": error_type,
                "error_message": message[:500] if message else None,
                "http_status": http_status,
                "attempted_at": datetime.now().isoformat(timespec="seconds"),
            }
        ]
    )
    insert_df(df, "screener_pull_errors")


def pull_one(s: requests.Session, sid: str, ticker: str, dry_run: bool = False) -> int:
    """Pull one stock end-to-end. Returns rows written (or rows parsed if dry-run)."""
    try:
        xls, view = fetch_export(s, ticker)
    except PermissionError:
        raise  # bubble — caller stops the loop
    except requests.HTTPError as e:
        log_error(sid, ticker, "http", str(e), http_status=e.response.status_code)
        return 0
    except Exception as e:
        log_error(sid, ticker, "fetch", f"{type(e).__name__}: {e}")
        return 0

    try:
        long_df = parse_export(xls, sid)
    except Exception as e:
        log_error(sid, ticker, "parse", f"{type(e).__name__}: {e}")
        return 0

    if long_df.empty:
        log_error(sid, ticker, "empty", "parser produced 0 rows")
        return 0

    quarters = long_df.loc[long_df["period_type"] == "quarterly", "period_end"].nunique()
    annuals = long_df.loc[long_df["period_type"] == "annual", "period_end"].nunique()
    if quarters < 4 or annuals < 5:
        log_error(
            sid, ticker, "thin",
            f"only {quarters} quarter periods / {annuals} annual periods",
        )
        # Log but still write — partial data is better than nothing.

    if dry_run:
        return len(long_df)

    return upsert_df(long_df, "fundamentals_screener")


def get_targets(args) -> pd.DataFrame:
    if args.sid:
        return read_sql(
            "SELECT sid, ticker FROM stocks WHERE sid = ?", params=[args.sid]
        )
    if args.tier:
        return read_sql(
            "SELECT sid, ticker FROM stocks WHERE cap_tier = ? AND ticker IS NOT NULL "
            "ORDER BY market_cap_cr DESC",
            params=[args.tier],
        )
    if args.universe:
        return read_sql(
            "SELECT sid, ticker FROM stocks WHERE ticker IS NOT NULL "
            "ORDER BY market_cap_cr DESC"
        )
    return pd.DataFrame()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--sid", help="single stock SID")
    parser.add_argument("--tier", choices=["LARGE", "MID", "SMALL"])
    parser.add_argument("--universe", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="parse but don't write to DB")
    parser.add_argument("--check-cookie", action="store_true",
                        help="just validate auth and exit")
    parser.add_argument("--login", action="store_true",
                        help="POST to /login/ using SCREENER_USERNAME/PASSWORD env vars, "
                             "save cookie file, and exit")
    args = parser.parse_args()

    if args.login:
        ok, detail = do_login()
        print(f"login: {'OK' if ok else 'FAILED'} — {detail}")
        return 0 if ok else 1

    s = make_session()

    if args.check_cookie:
        ok, detail = check_auth(s)
        print(f"auth: {'OK' if ok else 'FAILED'} — {detail}")
        return 0 if ok else 1

    targets = get_targets(args)
    if targets.empty:
        parser.error("no targets — specify --sid, --tier, or --universe")

    print(f"targets: {len(targets)} stocks")
    total_rows = 0
    failures = 0
    for i, (sid, ticker) in enumerate(targets[["sid", "ticker"]].itertuples(index=False), 1):
        try:
            n = pull_one(s, sid, ticker, dry_run=args.dry_run)
            status = "✓" if n > 0 else "·"
            print(f"  [{i}/{len(targets)}] {status} {sid} ({ticker}): {n} rows")
            total_rows += n
            if n == 0:
                failures += 1
        except PermissionError as e:
            print(f"\nAUTH FAILURE on {sid} ({ticker}): {e}")
            print("→ Re-extract the cookie from your browser and retry.")
            return 2
        if i < len(targets):
            time.sleep(random.uniform(*DELAY_BETWEEN_STOCKS))

    print(f"\ntotal rows: {total_rows}  |  failures: {failures}/{len(targets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
