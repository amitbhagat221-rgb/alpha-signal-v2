"""
Recover false-quarantined broker_recommendations rows.

WHY
    The live Identity Gate (validators/identity_check._verify_moneycontrol)
    matched the slug against the NSE *ticker* via substring until 2026-05-31.
    Moneycontrol slugs are *company-name*-derived, so that check false-
    quarantined every correct mapping where ticker ≠ slug (CEATLTD vs 'ceat',
    BHARTIARTL vs 'bhartiairtel', …) — 805 rows in broker_recommendations_
    quarantine, all reasoned "url '…' does not contain ticker 'X'".

WHAT
    Re-evaluate every quarantined row against the slug it was ACTUALLY fetched
    from (parsed out of _q_reason — NOT stocks.mc_slug, which was corrected
    during the Plan 0007 remediation and would mask genuine wrong-entity rows
    like APLL→apollohospitals). Promote only the rows the fixed gate now PASSes;
    leave genuine wrong-entity rows (Oil India→indianoilcorporation, …) in
    quarantine.

SAFETY
    - Dry-run by default; --apply performs writes inside one transaction.
    - INSERT OR IGNORE into broker_recommendations (append-only; PK dedupes).
    - Promotes only rows whose ACTUAL-slug re-verdict is PASS — never trusts the
      reason-text classification alone.
    - Idempotent: a second run finds nothing left to promote.

USAGE
    python -m tools.recover_quarantined_recos            # dry-run, prints plan
    python -m tools.recover_quarantined_recos --apply    # perform the recovery
"""
import argparse
import re
from datetime import datetime

from db import get_db, read_sql
from validators.identity_check import verify_identity

# Base columns shared by broker_recommendations and its _quarantine mirror.
_BASE_COLS = ["sid", "broker", "reco_date", "reco_type", "reco_price",
              "target_price", "report_url", "fetched_at"]


def _slug_from_reason(reason: str):
    """Extract the slug/URL the row was actually fetched from, out of _q_reason.

    Two shapes appear in the wild:
      A) "url '/india/stockpricequote/tyres/ceat/C07' does not contain ticker 'CEATLTD'"
      B) "wrong-entity (mc_)slug='apollohospitalsenterprises' for 'Apollo Micro …'"
    Returns a slug/URL string the identity gate can consume, or None.
    """
    if not reason:
        return None
    m = re.search(r"url '([^']+)'", reason)
    if m:
        return m.group(1)
    m = re.search(r"(?:mc_)?slug='([^']+)'", reason)
    if m:
        # Wrap the bare company segment as a pseudo-URL so the gate's
        # company-segment extractor (parts[-2]) sees it.
        return f"/india/stockpricequote/x/{m.group(1)}/X"
    return None


def analyse():
    """Return (recoverable_rows, kept_rows, unparseable) as lists of dicts."""
    rows = read_sql(
        """
        SELECT q.rowid AS _rid, q.sid, q.broker, q.reco_date, q.reco_type,
               q.reco_price, q.target_price, q.report_url, q.fetched_at,
               q._q_reason, s.name
        FROM broker_recommendations_quarantine q
        LEFT JOIN stocks s ON s.sid = q.sid
        """
    )
    recoverable, kept, unparseable = [], [], []
    for d in rows.to_dict("records"):
        slug = _slug_from_reason(d["_q_reason"])
        if not slug:
            unparseable.append(d)
            continue
        v = verify_identity(d["sid"], slug, source="moneycontrol",
                            expected_name=d["name"] or d["sid"],
                            expected_url_segment=d["sid"])
        if v.status == "PASS":
            recoverable.append(d)
        else:
            kept.append(d)
    return recoverable, kept, unparseable


def apply_recovery(recoverable):
    """Promote recoverable rows to live + delete from quarantine + mark TRUSTED.
    One transaction. Returns (n_promoted, n_deleted)."""
    if not recoverable:
        return 0, 0
    cols_sql = ",".join(_BASE_COLS)
    ph = ",".join("?" * len(_BASE_COLS))
    now = datetime.now().isoformat(timespec="seconds")
    promoted = deleted = 0
    affected_sids = set()
    with get_db() as conn:
        for d in recoverable:
            conn.execute(
                f"INSERT OR IGNORE INTO broker_recommendations ({cols_sql}) VALUES ({ph})",
                [d[c] for c in _BASE_COLS],
            )
            promoted += 1
            conn.execute("DELETE FROM broker_recommendations_quarantine WHERE rowid=?",
                         [d["_rid"]])
            deleted += 1
            affected_sids.add(d["sid"])

        # Flip the trust verdict to TRUSTED ONLY for sids with no remaining
        # quarantined rows. A sid that still has a genuine wrong-entity row
        # (mixed provenance — some slugs right, one wrong) must stay QUARANTINED;
        # promoting its good rows doesn't resolve the outstanding identity fault.
        for sid in affected_sids:
            still_bad = conn.execute(
                "SELECT 1 FROM broker_recommendations_quarantine WHERE sid=? LIMIT 1", [sid]
            ).fetchone()
            if still_bad:
                continue
            conn.execute(
                """
                UPDATE trust_verdicts
                   SET gate_1_identity=1, verdict_overall='TRUSTED',
                       reasons_json=json_set(COALESCE(reasons_json,'{}'),
                                             '$.gate_1_identity.recovered_at', ?)
                 WHERE source_table='broker_recommendations' AND sid=?
                   AND verdict_overall='QUARANTINED'
                """,
                [now, sid],
            )
    return promoted, deleted


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="perform the recovery (default: dry-run)")
    args = ap.parse_args()

    recoverable, kept, unparseable = analyse()
    rec_sids = sorted({d["sid"] for d in recoverable})
    kept_sids = sorted({d["sid"] for d in kept})
    print(f"Quarantined broker recos: {len(recoverable)+len(kept)+len(unparseable)} rows")
    print(f"  RECOVERABLE (fixed gate → PASS on actual slug): {len(recoverable)} rows / {len(rec_sids)} sids")
    print(f"  KEPT (genuine wrong-entity):                    {len(kept)} rows / {len(kept_sids)} sids")
    print(f"  UNPARSEABLE reason (left as-is):                {len(unparseable)} rows")
    if kept_sids:
        print(f"  kept sample: {kept_sids[:8]}")

    if not args.apply:
        print("\nDRY-RUN — no writes. Re-run with --apply to promote the recoverable rows.")
        return
    promoted, deleted = apply_recovery(recoverable)
    print(f"\nAPPLIED: promoted {promoted} rows to broker_recommendations, "
          f"removed {deleted} from quarantine.")


if __name__ == "__main__":
    main()
