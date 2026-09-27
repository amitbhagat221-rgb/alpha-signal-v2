#!/bin/bash
# Alpha Signal v2 — nightly DB backup to Google Drive (rclone).
#
# Why this shape:
#   • NEVER `cp` a live SQLite file — the pipeline + cockpit write to it and a
#     raw copy can be torn/corrupt. `VACUUM INTO` makes a consistent, compacted
#     snapshot safely while the DB is in use.
#   • Integrity-check the snapshot BEFORE trusting it (a backup you can't restore
#     is not a backup).
#   • gzip ~2.6x → the 2.6 GB DB lands as ~1 GB.
#   • Credentials live in rclone's own config (~/.config/rclone/rclone.conf),
#     created once via `rclone config` — never in this script (CLAUDE.md).
#
# One-time setup before the cloud upload works:
#   rclone config        # n) new remote, name it: gdrive, type: drive,
#                        # leave client_id/secret blank, scope: 1 (full) or
#                        # drive.file, "Use auto config?" -> N on this headless
#                        # VM, then follow the URL+code flow. See backup notes.
#
# Until that remote exists this script still protects you: it keeps the last 2
# compressed snapshots locally in ./backups/ and logs a reminder.
set -u

DB="/home/ubuntu/alpha-signal-v2/data/alpha_signal.db"
REMOTE="gdrive:alpha-signal-v2-backups"
LOCAL_DIR="/home/ubuntu/alpha-signal-v2/backups"
TMP="/tmp/alpha_db_backup"
STAMP="$(date -u +%Y%m%d)"
GZ="$TMP/alpha_signal_${STAMP}.db.gz"
RETAIN_DAILY_DAYS=7   # remote: drop dailies older than this (month-1st kept long)

log() { echo "[backup $(date -u +%FT%TZ)] $*"; }

mkdir -p "$TMP" "$LOCAL_DIR"
rm -f "$TMP"/*.db "$TMP"/*.gz 2>/dev/null

# 1. Consistent, compacted snapshot
log "snapshot via VACUUM INTO ..."
sqlite3 "$DB" "VACUUM INTO '$TMP/snap.db'" || { log "VACUUM failed"; exit 1; }

# 2. Trust-but-verify
CHK="$(sqlite3 "$TMP/snap.db" 'PRAGMA integrity_check;' | head -1)"
[ "$CHK" = "ok" ] || { log "integrity_check FAILED: $CHK"; rm -f "$TMP/snap.db"; exit 1; }

# 3. Compress
gzip -1 -c "$TMP/snap.db" > "$GZ" || { log "gzip failed"; rm -f "$TMP/snap.db"; exit 1; }
rm -f "$TMP/snap.db"
log "snapshot ok ($(du -h "$GZ" | cut -f1)), integrity ok"

# 4. Ship it (or fall back to a local copy)
if rclone listremotes 2>/dev/null | grep -q '^gdrive:'; then
    if rclone copy "$GZ" "$REMOTE/" 2>&1; then
        log "uploaded $(basename "$GZ") -> $REMOTE"
        # Success marker — config.FILE_OUTPUTS watches its mtime (review F13: a failed
        # or skipped backup was invisible; backup.log is appended either way).
        touch /home/ubuntu/alpha-signal-v2/output/backup_last_ok
        # Retention: delete dailies older than N days, but keep month-1st snapshots.
        rclone delete "$REMOTE/" --min-age "${RETAIN_DAILY_DAYS}d" \
            --include 'alpha_signal_*.db.gz' --exclude 'alpha_signal_*01.db.gz' 2>/dev/null
        rm -f "$GZ"
    else
        log "rclone upload FAILED — keeping local copy in $LOCAL_DIR"
        mv "$GZ" "$LOCAL_DIR/"
    fi
else
    log "gdrive remote not configured yet — keeping local copy in $LOCAL_DIR (run: rclone config)"
    mv "$GZ" "$LOCAL_DIR/"
fi

# Keep only the newest 2 local fallback copies (offsite is the real backup).
ls -1t "$LOCAL_DIR"/alpha_signal_*.db.gz 2>/dev/null | tail -n +3 | xargs -r rm -f
log "done"
