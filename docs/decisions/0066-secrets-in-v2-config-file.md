# ADR 0066 — Credentials live in `~/.config/alpha-signal/secrets.env`, outside the repo

**Status:** proposed 2026-10-10 (Amit: "why are we still using the v1 folder" → "YES please"). Replaces the credentials rule from the v2 rebuild (ADR 0007): v2 had been reading v1's `~/alpha-signal/run_pipeline.sh` exports.

## Decision

1. **One file.** Every external secret is one `export NAME="value"` line in `~/.config/alpha-signal/secrets.env`:
   - mode 600, owned by `ubuntu`;
   - outside both repos and git;
   - next to the cockpit's `cockpit_auth.json`.
2. **Loaded once.** The `run.sh` preamble sources it for every scheduled job. Processes not started by `run.sh` (the cockpit services) read a key from the same file through `sources.kite_pull._env`. That is a fallback, not a second copy.
3. **Not inside `~/alpha-signal-v2/`.** The repo is read by git, Claude sessions, the agent org's builder seats, graphify and the MCP servers. A secrets file there is one `git add` or one tool read away from leaking.
4. **v1's file is no longer read.** It is not edited (CLAUDE.md: never touch `~/alpha-signal/`), so its old copies stay until Amit removes them.
5. **Backup.** `backup_secrets.sh` backs up the new file (encrypted).

## Why

- v1 has run nothing since 2026-05. "Don't duplicate secrets" had made v2 depend on a dead project's script for every credential.
- The Kite Connect keys (plan 0022) were the first new secret; they should not go into v1.

## Checked

- Values in the new file are identical to v1's: the 8 exports were compared by hash, without printing.
- All 11 variables the jobs use resolve from a clean environment through the `run.sh` preamble.
- Full test suite passes.
- Error messages, OPERATOR.md §4, kite-setup.md and CLAUDE.md now name the new file.
