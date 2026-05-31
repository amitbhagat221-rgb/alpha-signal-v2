# Kite Connect setup (Plan 0002 §3.1c)

`sources/kite_pull.py` is built and importing, but **pending live credentials** —
not wired into `config.PIPELINE_STEPS` until verified. This is the one-time setup.

## What you do (one-time)

1. **Create a Kite Connect app** at <https://developers.kite.trade> (separate
   ₹500/mo subscription on top of your trading login). You get an **`api_key`**
   and **`api_secret`**. Set the app's **redirect URL** to anything (e.g.
   `https://127.0.0.1`) — the headless login parses the token out of the redirect.
2. **Grab your TOTP secret** — when you set up the authenticator 2FA on Zerodha,
   it shows a base32 secret string (the thing behind the QR). Save that; it lets
   cron log in unattended (`pyotp` regenerates the 6-digit code each morning).
3. **Add 5 exports to v1's `run_pipeline.sh`** (where all secrets live — never in
   code or git):
   ```sh
   export KITE_API_KEY="..."
   export KITE_API_SECRET="..."
   export KITE_USER_ID="ZXXXXX"        # your Zerodha client id
   export KITE_PASSWORD="..."
   export KITE_TOTP_SECRET="..."       # the base32 2FA seed
   ```

## What I do (once creds are in)

```sh
source ~/alpha-signal/venv/bin/activate
eval "$(grep '^export ' /home/ubuntu/alpha-signal/run_pipeline.sh)"
python -m sources.kite_pull --check-auth          # 1. proves the key + login work
python -m sources.kite_pull --instruments         # 2. maps our SIDs → NSE tokens
python -m sources.kite_pull --backfill-bars --universe fno --days 5   # 3. smoke
python -m sources.kite_pull --backfill-bars --universe fno --days 60  # 4. full
```
Then wire `compute_fno_iv`-style daily step (`{"name":"fetch_kite_bars", ...}`) into
`PIPELINE_STEPS`, and the 3 true-intraday §3.2.3 factors start accumulating.

## Reality checks
- **Connect app ≠ trading account.** The ₹500/mo dev-app is a separate signup.
- **Token expires ~06:00 IST daily** — cached in `~/.kite_access_token.json`
  (0600 perms); the headless TOTP login refreshes it once/day. If the undocumented
  web-login flow ever breaks, use `--request-token <tok>` (open
  `https://kite.trade/connect/login?api_key=<key>&v=3`, log in, copy from redirect).
- **Intraday history is ~60 trading days rolling** — the 3 factors it feeds
  (`volume_clock_concentration`, `tick_imbalance_5d`, `intraday_momentum_persistence`)
  are forward-accumulation; ~90 days of nightly capture before backtest-grade.
- **Static IP** required by SEBI for API — Oracle VM already has one ✅.
- The other 6 §3.2.3 microstructure factors are daily-derivable (no Kite) — see
  `signals/microstructure.py` (to be built).
