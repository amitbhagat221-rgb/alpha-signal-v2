#!/bin/bash
# Alpha Signal v2 — nightly ENCRYPTED backup of VM-only secrets + wiring to Drive.
#
# Why: backup_db.sh covers all DATA (the SQLite DB). But the credentials, cron
# wiring, and rclone token live ONLY on this VM (gitignored, not in the DB). If
# the VM dies you'd keep your data but lose the orchestration + every secret.
# This bundles those files, GPG-symmetric-encrypts them (AES256), and ships the
# CIPHERTEXT to Drive — plaintext secrets never leave the VM.
#
# Passphrase: read from ~/.alpha_backup_passphrase (chmod 600) or $BACKUP_GPG_PASSPHRASE.
#   ********************************************************************
#   SAVE THE PASSPHRASE IN YOUR PASSWORD MANAGER. If the VM dies, the
#   passphrase file dies with it and the Drive bundle is undecryptable.
#   ********************************************************************
#
# Restore on a fresh box:
#   rclone copy gdrive:alpha-signal-v2-backups/secrets/<latest>.tar.gz.gpg .
#   gpg -d -o bundle.tar.gz <file>.tar.gz.gpg      # prompts for the passphrase
#   tar xzf bundle.tar.gz                           # recreates home/ubuntu/... tree
set -u

REMOTE="gdrive:alpha-signal-v2-backups/secrets"
PASS_FILE="$HOME/.alpha_backup_passphrase"
TMP="/tmp/alpha_secrets_backup"
STAGE="$TMP/stage"
STAMP="$(date -u +%Y%m%d)"
TAR="$TMP/secrets_${STAMP}.tar.gz"
ENC="$TAR.gpg"
RETAIN_DAYS=35   # keep ~a month of dailies; month-1st bundles kept long

log() { echo "[secrets-backup $(date -u +%FT%TZ)] $*"; }

# --- passphrase (env wins, else the 600 file) ---
PASS="${BACKUP_GPG_PASSPHRASE:-}"
[ -z "$PASS" ] && [ -f "$PASS_FILE" ] && PASS="$(cat "$PASS_FILE")"
[ -z "$PASS" ] && { log "FATAL: no passphrase ($PASS_FILE missing and \$BACKUP_GPG_PASSPHRASE unset)"; exit 1; }

mkdir -p "$TMP"
rm -f "$TMP"/*.tar.gz "$TMP"/*.gpg 2>/dev/null
rm -rf "$STAGE"; mkdir -p "$STAGE"

# --- collect DR-critical VM-only files (preserve path + mode) ---
FILES=(
  /home/ubuntu/alpha-signal/run_pipeline.sh           # v1 — holds the real credentials
  /home/ubuntu/.config/rclone/rclone.conf             # Drive OAuth token
  /home/ubuntu/.cache/screener_cookie.json            # Screener session (re-creatable via --login)
  /home/ubuntu/.config/alpha-signal/cockpit_auth.json # cockpit login: password HASH + session secret
  /etc/systemd/system/alpha-cockpit.service           # (also versioned in ops/systemd/)
  /etc/systemd/system/alpha-cockpit-ops.service
  # run.sh, backup_db.sh and this script are in git since 2026-09-27 (review F13)
)
n=0
for f in "${FILES[@]}"; do
  if [ -f "$f" ]; then mkdir -p "$STAGE$(dirname "$f")"; cp -p "$f" "$STAGE$f"; n=$((n+1)); fi
done
crontab -l > "$STAGE/crontab.txt" 2>/dev/null || true
[ "$n" -gt 0 ] || { log "FATAL: no source files found"; exit 1; }
log "staged $n files + crontab"

# --- archive + encrypt ---
tar czf "$TAR" -C "$STAGE" . || { log "tar failed"; exit 1; }
printf '%s' "$PASS" | gpg --batch --yes --pinentry-mode loopback --passphrase-fd 0 \
    --cipher-algo AES256 -c -o "$ENC" "$TAR" || { log "gpg encrypt failed"; rm -f "$TAR"; exit 1; }
rm -f "$TAR"
rm -rf "$STAGE"
log "encrypted $(basename "$ENC") ($(du -h "$ENC" | cut -f1))"

# --- ship it ---
if rclone listremotes 2>/dev/null | grep -q '^gdrive:'; then
  if rclone copy "$ENC" "$REMOTE/" 2>&1; then
    log "uploaded $(basename "$ENC") -> $REMOTE"
    rclone delete "$REMOTE/" --min-age "${RETAIN_DAYS}d" \
        --include 'secrets_*.tar.gz.gpg' --exclude 'secrets_*01.tar.gz.gpg' 2>/dev/null
    rm -f "$ENC"
  else
    log "rclone upload FAILED — kept local $ENC"; exit 1
  fi
else
  log "gdrive remote not configured — kept local $ENC"
fi
log "done"
