"""
Alpha Signal v2 — the multibagger desk's lists (plan 0026 phase 2.2, ADR 0075).

The 30 candidates and the 10 held are Amit's decisions, not scores: this module is the only writer of
`multibagger_book`, called from the CLI (and later the cockpit), NEVER by a pipeline step. Every change
writes exactly one `multibagger_book_log` row in the same transaction (append-only, INSERT only).

Rules (config.MB_THESIS): at most `max_book` names are candidate-or-held, at most `max_held` are held,
and a held name must have been a candidate. A dropped name may be re-added as a candidate.

Usage:
    python -m output.mb_book add SID "thesis line" "reason"
    python -m output.mb_book hold SID "reason" [--price 123.4]
    python -m output.mb_book drop SID "reason"
    python -m output.mb_book list [candidate|held|dropped]
"""

import argparse
import getpass
from datetime import date, datetime

import pandas as pd

from config import MB_THESIS
from db import get_db


def _require(text, what):
    if not text or not str(text).strip():
        raise ValueError(f"mb_book: {what} is required — every change carries its reason")
    return str(text).strip()


def _change(conn, sid, action, to_status, reason, actor, **cols):
    """Upsert the book row and append the log row (caller holds the transaction)."""
    now = datetime.now().isoformat(timespec="seconds")
    row = conn.execute("SELECT status FROM multibagger_book WHERE sid = ?", (sid,)).fetchone()
    from_status = row[0] if row else None
    cols = {**cols, "status": to_status, "since": date.today().isoformat(), "reason": reason, "updated_at": now}
    if row is None:
        keys = ["sid", *cols]
        conn.execute(f"INSERT INTO multibagger_book ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
                     [sid, *cols.values()])
    else:
        conn.execute(f"UPDATE multibagger_book SET {', '.join(f'{k} = ?' for k in cols)} WHERE sid = ?",
                     [*cols.values(), sid])
    conn.execute("INSERT INTO multibagger_book_log (ts, sid, action, from_status, to_status, reason, actor) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?)", (now, sid, action, from_status, to_status, reason, actor))


def _counts(conn):
    n_book = conn.execute("SELECT COUNT(*) FROM multibagger_book WHERE status IN ('candidate','held')").fetchone()[0]
    n_held = conn.execute("SELECT COUNT(*) FROM multibagger_book WHERE status = 'held'").fetchone()[0]
    return n_book, n_held


def _status(conn, sid):
    row = conn.execute("SELECT status FROM multibagger_book WHERE sid = ?", (sid,)).fetchone()
    return row[0] if row else None


def add_candidate(sid, thesis_line, reason, actor=None):
    thesis_line, reason = _require(thesis_line, "thesis_line"), _require(reason, "reason")
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM stocks WHERE sid = ?", (sid,)).fetchone() is None:
            raise ValueError(f"mb_book: {sid} is not in the universe (use the universe sid, not the NSE ticker)")
        status = _status(conn, sid)
        if status in ("candidate", "held"):
            raise ValueError(f"mb_book: {sid} is already {status}")
        if _counts(conn)[0] >= MB_THESIS["max_book"]:
            raise ValueError(f"mb_book: the book is full ({MB_THESIS['max_book']} candidates + held) — drop one first")
        _change(conn, sid, "add_candidate", "candidate", reason, actor or getpass.getuser(),
                thesis_line=thesis_line, entry_date=None, entry_price=None)


def hold(sid, reason, entry_price=None, actor=None):
    reason = _require(reason, "reason")
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        status = _status(conn, sid)
        if status != "candidate":
            raise ValueError(f"mb_book: {sid} is {status or 'not in the book'} — only a candidate can be held")
        if _counts(conn)[1] >= MB_THESIS["max_held"]:
            raise ValueError(f"mb_book: {MB_THESIS['max_held']} names are already held — drop one first")
        if entry_price is None:
            r = conn.execute("SELECT close FROM stock_prices WHERE sid = ? AND close > 0 ORDER BY date DESC LIMIT 1",
                             (sid,)).fetchone()
            entry_price = r[0] if r else None
        _change(conn, sid, "hold", "held", reason, actor or getpass.getuser(),
                entry_date=date.today().isoformat(), entry_price=entry_price)


def drop(sid, reason, actor=None):
    reason = _require(reason, "reason")
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        status = _status(conn, sid)
        if status not in ("candidate", "held"):
            raise ValueError(f"mb_book: {sid} is {status or 'not in the book'} — nothing to drop")
        _change(conn, sid, "drop", "dropped", reason, actor or getpass.getuser())


def list_book(status=None):
    q, p = "SELECT * FROM multibagger_book", []
    if status:
        q, p = q + " WHERE status = ?", [status]
    with get_db() as conn:
        return pd.read_sql_query(q + " ORDER BY status, since, sid", conn, params=p)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("sid"), a.add_argument("thesis_line"), a.add_argument("reason")
    h = sub.add_parser("hold")
    h.add_argument("sid"), h.add_argument("reason"), h.add_argument("--price", type=float)
    d = sub.add_parser("drop")
    d.add_argument("sid"), d.add_argument("reason")
    ls = sub.add_parser("list")
    ls.add_argument("status", nargs="?", choices=["candidate", "held", "dropped"])
    args = ap.parse_args()
    if args.cmd == "add":
        add_candidate(args.sid, args.thesis_line, args.reason)
    elif args.cmd == "hold":
        hold(args.sid, args.reason, args.price)
    elif args.cmd == "drop":
        drop(args.sid, args.reason)
    allb = list_book()
    n_book, n_held = (int(allb["status"].isin(["candidate", "held"]).sum()), int((allb["status"] == "held").sum()))
    b = allb if not getattr(args, "status", None) else allb[allb["status"] == args.status]
    print(b.to_string(index=False) if len(b) else "(the book is empty)")
    print(f"\ncandidates + held {n_book}/{MB_THESIS['max_book']} · held {n_held}/{MB_THESIS['max_held']}")


if __name__ == "__main__":
    main()
