---
Status: accepted — open questions resolved 2026-06-09; Phase 0 (validation kill-gate) is next
Created: 2026-06-09
Last updated: 2026-06-09
Owner: Amit
Implementation: none yet — research + plan only
Related ADRs: (to be filed at build start — separate-product + validate-before-build + exit-engine-centric)
Decisions (2026-06-09): spot-only v1 (read funding/OI as a signal, do NOT trade perps) · Solana-first for the live hunt, EVM subgraphs for backtest depth · basket-N deferred to the Phase-0 base-rate study · **own repo** (separate venv + DB regardless).
---

# 0009 — Crypto Convex Cockpit ("lottery-ticket" book)

> A **separate product** from the equity Alpha Signal, sharing only the engineering spine (plain functions, SQLite, no frameworks, cockpit pattern). Different asset class, different objective function, different data layer. Data-source map: [crypto-data-sources.md](../reference/crypto-data-sources.md).

## What problem?

Deploy **1% of net worth** into crypto as a **maximum-convexity barbell**: hunt 10–100x tokens, accept that most go to −100%, and capture the winners with a **disciplined, signal-driven exit**. The model is the GS trader who caught the Dogecoin run *and sold before it collapsed* — systematized. Capped downside (it's 1%), unbounded upside.

This **inverts** the equity model's objective. We optimise **skew/convexity, not Sharpe.** What mattered there (does momentum survive cost, Sharpe, BTC-beta dominance, diversification-for-safety) stops mattering; what matters here:
- **the right tail** — base-rate × payoff of the 10x+ event;
- **early detection** — being in before retail FOMO (smart-money + new-liquidity + attention acceleration);
- **the exit** — calling euphoric tops before the round-trip (the harder, more valuable half);
- **one defensive gate** — outright-fraud screening (a rug is the only −100% worth preventing at 1%).

## What does the solution look like?

A **funnel** — same gate-discipline as the equity screener, re-purposed for convexity. Two hard gates, then a composite entry score, then an exit engine, then a cockpit.

```
ALL TOKENS (survivorship-aware universe, Layer 1/2)
        │
  GATE-0  FRAUD KILL (Layer 6)  ── hard-exclude: honeypot · sell_tax>15% · mintable&owner-live ·
        │                          top10>50% · LP unlocked · RugCheck CRITICAL
        ▼
  GATE-1  TRADABILITY  ── min DEX liquidity (wash-aware) + can-I-exit-1%-cleanly check.
        │                  A 50x you can't sell is worth zero.
        ▼
  IGNITION SCORE (ENTRY — composite, within-tier)
        │   • smart-money accumulation   (Nansen netflows / Dune list watched via Helius)  ← core edge
        │   • new-liquidity / early-innings (GeckoTerminal new_pools age+liq growth;
        │                                     SolanaTracker bonding-curve graduation proximity)
        │   • attention acceleration      (Santiment Δ unique_social_volume z-score; trending-rank velocity)
        │   • narrative tailwind          (DefiLlama category TVL momentum + CoinGecko category)
        ▼
  RANKED LOTTERY CANDIDATES  → tiered (majors / large-alt / long-tail-meme), never cross-tier
        │
  EXIT / EUPHORIA ENGINE (the valuable half)
        │   triggers (signal-driven, NOT a price target — no fair value to anchor):
        │   • funding blow-off  (Coinalyze/exchange funding + OI spike = crowded longs)
        │   • smart-money distribution (the wallets you followed in now sending to exchanges)
        │   • attention saturation (social volume rolling over from peak; Google Trends mainstream peak)
        │   → SCALE OUT in tranches (e.g. trim 25% per trigger), not all-or-nothing
        ▼
  CRYPTO COCKPIT  — ranked candidates · fraud verdict · ignition breakdown · live exit-state per holding
```

**Position sizing:** equal-ish small tickets across N names (basket of lotteries — low hit-rate, fat payoff), per-name cap, Kelly-for-lotteries informed by the Phase-0 base-rate study. The 1% total is the structural stop-loss; no per-name stop (stops guarantee you eat the −100%s without ever holding for the 50x — wrong for a convex book).

**Tiers (the cap-tier analog, carried over):** majors (BTC/ETH) / large-alt / long-tail-meme — segment by liquidity+mcap, rank within tier only. Most convexity lives in the long tail; majors are mostly the regime context.

## Phases

- **Phase 0 — VALIDATION / KILL-GATE (do first, cheap, ~$0 + $79 one-shot).** Run the "oracle" questions as real backtests on the survivorship-free universe (Layer 2) + Santiment history + funding history. Three decide go/no-go:
  1. **Base rates of the right tail** — what fraction of each tier/category hit ≥10x from an identifiable early point, and the payoff distribution? (Is the hunt worth it vs just buying ETH?)
  2. **Are winners separable ex-ante?** — among 10x+ winners, was smart-money accumulation + attention acceleration present *before* the run and *absent* in the duds? (Real edge, or survivorship hindsight?)
  3. **Can the top be called?** — did exit signals (funding blow-off, smart-money distribution, attention saturation) precede the collapse within a useful window?
  Plus: rug base-rate + filterability (Gate-0 false-exclude rate). **Honest caveat:** on-chain smart-money PIT is the hardest/weakest to backfill cheaply (Nansen historical-holdings + Dune) — Phase 0 may validate #2 only partially; say so. **Done-when of Phase 0:** the basket's expected payoff (incl. the rug rate and a realistic exit) beats buy-and-hold ETH on the same window. If not → stop, it's a fun way to set 1% on fire, which is also a fine answer.
- **Phase 1 — data plumbing.** Separate venv + SQLite DB. Collectors for the free sources (CoinGecko, CCXT/Binance Vision, GeckoTerminal, DexScreener, Coinalyze, GoPlus/RugCheck, Santiment, DefiLlama) + Helius webhooks for the curated smart-wallet list. Hourly + 00:00-UTC daily cadence. Config dict, plain functions — mirror the equity producer pattern.
- **Phase 2 — gates.** Gate-0 fraud kill (GoPlus+Honeypot.is EVM / RugCheck+RPC Solana) + Gate-1 tradability (wash-aware liquidity floor). These are hard exclusions, not weighted factors.
- **Phase 3 — ignition score.** The 4-component entry composite, tiered, validated against Phase-0 separability.
- **Phase 4 — exit/euphoria engine.** Signal-driven tranche scale-out. The most valuable, hardest-to-get-right piece — build last, validate hardest.
- **Phase 5 — cockpit surface.** Ranked candidates + fraud verdict + ignition breakdown + per-holding exit-state. Reuse the equity cockpit's component patterns.
- **Phase 6 — paper-trade → live 1%.** Log everything; compare realized basket to buy-hold-to-zero and to ETH.

## Done when

A paper-traded (then live-1%) lottery basket, gated on fraud + tradability, shows — on the survivorship-corrected universe across ≥2 independent windows — a **basket expected payoff that beats buy-and-hold ETH net of the rug rate**, AND the exit engine demonstrably captures more than ride-it-up-and-back-down (the round-trip). The exit engine is the bar that matters: entry can be partly luck; the repeatable edge is the disciplined scale-out.

## Open questions — RESOLVED 2026-06-09

- ~~Spot-only or perps?~~ **DECIDED: spot-only for v1.** Max loss = the ticket, no liquidation to eject us from the drawdown-heavy path a 10x winner takes en route (the equity multibagger study showed 81% of 3x+ winners draw ≥30%). We still **read** funding/OI from Coinalyze (free) as a top/exit signal — we get the crowd-positioning thermometer without taking leverage. Shorting euphoria via perps is a separate, capital-intensive, liquidation-prone book; out of scope for the 1% lottery thesis.
- ~~Chains in scope for v1?~~ **DECIDED: Solana-first for the live hunt, EVM subgraphs for backtest depth.** Solana = where the memecoin convexity + the best free real-time tooling lives (Helius webhooks, SolanaTracker graduation, GeckoTerminal new_pools); EVM = deeper, cleaner survivorship-free history for Phase-0 validation. Each chain used for its strength.
- ~~How many simultaneous tickets (the Kelly-for-lotteries N)?~~ **Still deferred — by design an OUTPUT of the Phase-0 base-rate study, not a pre-commitment.**
- ~~Repo location?~~ **DECIDED: its own repo** (not `alpha-signal-v2/crypto/`). Clean separation of the two products; separate venv + DB regardless. Re-bootstraps the plain-function/SQLite/cockpit spine, copying the patterns (not the deps) from the equity repo.

## Considered & rejected

- **Markowitz / HRP portfolio optimisation** — rejected for this book. Risk-parity is the *equity* Track-2 answer; for a convex lottery basket, diversifying toward low-vol dilutes exactly the right tail we're paying for. Equal-ish small tickets + the 1% cap is the correct construction.
- **Per-name stop-losses** — rejected. Stops guarantee eating the −100%s while cutting winners before the 50x; fatal to a convex payoff. The 1% total *is* the stop.
- **Fundamental/value factors (DCF, quality, PT-upside)** — N/A. No cash flows, no analyst PTs for the long tail. The equity model's entire value half doesn't exist here; this is a momentum + flow + attention + carry market.
- **Direct X/Twitter API dependency** — rejected (priced out 2026, $5K/mo for history, closed to signups). Route social through Santiment.
- **Adding crypto deps to v1's shared venv** — rejected (CLAUDE.md: never touch `~/alpha-signal/`). Separate venv + DB.
- **Expensive institutional data (Kaiko/Glassnode-API/The-TIE/Tardis)** — rejected at 1% scale; free + ~$200/mo stack covers the thesis. Revisit only if AUM justifies.

## Cost

Phase-0 validation ≈ **$0 + $79 one-shot** (CMC UCID survivorship sweep, run once, cancel). Live signal book ≈ **~$150–200/mo**: Santiment Pro $49 + Nansen Pro $49 + SolanaTracker €50 + Laevitas $50 (or Coinglass Startup $79). Everything else free. Trivial against a 1% allocation.
