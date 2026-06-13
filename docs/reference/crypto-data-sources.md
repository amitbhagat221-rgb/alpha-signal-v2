# Crypto data sources — convex/lottery-ticket cockpit

> Companion to [0009-crypto-convex-cockpit.md](../plans/0009-crypto-convex-cockpit.md). Mirrors the equity [historical_data_sources.md] role for the crypto track.
> Researched 2026-06-09 via 6 parallel web-research agents (smart-money / social / derivatives / new-liquidity / token-safety / price-universe), each cross-verified against primary docs + pricing pages. **Prices change fast in crypto — re-verify the specific tier before subscribing.**

## The thesis this serves

A **1%-of-portfolio, maximum-convexity** book: hunt 10–100x tokens, accept −100% on the duds, capture the winners with a **signal-driven exit** (the GS-Doge-trader skill, systematized). Not Sharpe; **skew**. The data must let us (a) detect early accumulation, (b) call the euphoric top, (c) filter outright fraud — nothing else matters.

**Headline:** the entire stack is **free → ~$200/mo**, comfortably inside a 1% budget. Most of the edge (smart-money discovery, new-pool detection, funding, fraud-gate) has a credible **free** path; the paid tier buys backtestable history + convenience, not the only access.

---

## The chosen stack at a glance

| Layer | Role | Primary (free) | Paid upgrade | Verdict |
|---|---|---|---|---|
| **Price / OHLCV / universe** | foundation | CoinGecko Demo + CCXT/Binance + Binance Vision bulk | CoinGecko Analyst $129 (2013 hist) | free covers it |
| **Survivorship universe** | backtest integrity | CoinGecko `status=inactive` flag | CMC Startup $79 one-shot UCID sweep | $79 one-shot |
| **New-liquidity / early entry** | ENTRY | GeckoTerminal `/new_pools` + DexScreener boosts | SolanaTracker €50 (pump.fun graduation) | free + €50 |
| **Smart-money on-chain** | ENTRY (core edge) | Arkham free UI + Dune free (discover) → Helius free (watch, Solana) | Nansen Pro $49 + ~$0.05/call (netflows) | free discover, $49 signal |
| **Social / attention velocity** | ENTRY + EXIT | CoinGecko trending + DefiLlama narratives + Reddit/Telegram pollers | **Santiment Pro $49** (history to 2016) | Santiment is the anchor |
| **Derivatives funding / OI** | EXIT (euphoria) | Coinalyze (free, daily agg) + direct exchange APIs (funding hist) | Laevitas $50 / Coinglass $79 | free + $50 |
| **Token safety / fraud** | GATE-0 (defensive) | **GoPlus** (keyless) + Honeypot.is (EVM) + **RugCheck** (Solana) + Solana RPC holders | — | fully free |

**Cost ladder:** Phase-0 validation ≈ **$0 + $79 one-shot** · live signal book ≈ **~$150–200/mo** (Santiment $49 + Nansen $49 + SolanaTracker €50 + Laevitas/Coinglass $50–79).

---

## Layer 1 — Price / OHLCV / universe (foundation)

**Keepers**
- **CoinGecko** — best breadth (18K CEX + 37M DEX tokens, 250+ chains), cheapest path to history. Demo (free, key req'd): 10K calls/mo, 100/min, 1yr daily. Analyst $129/mo unlocks **2013 daily / 2018 hourly**. `pycoingecko`. Gotcha: OHLCV candle granularity is auto-selected by date-range (can't get hourly for a 90d window on low tiers); ~60s real-time lag on free.
- **CCXT + Binance/Bybit/OKX direct** — **free unlimited** public OHLCV (1m→1mo) for any CEX-listed token, back to listing (~2017 for majors). 1,200 weight/min. The free intraday workhorse. `pip install ccxt`.
- **Binance Vision** (`data.binance.vision`) — free static zip archives of klines/trades, all timeframes, back to 2017; **retains delisted pairs by direct URL** (partial survivorship). `pip install binance-historical-data`. Download once, store locally.

**Nice-to-have:** Coinpaprika Starter $99 (5yr daily, all assets — cross-validation); Tardis.dev Academic $350 (tick-level, only when sub-hourly signal construction is needed).

**Skip (this stage):** Kaiko (~$9.5K/yr+, institutional), CCData/CoinDesk (non-renewing 250K lifetime free tier = dead-end, opaque pricing), CoinAPI (billing complexity, non-renewing trial), Messari (intelligence layer not a data pipe), Coinmetrics community (30-day history too shallow).

## Layer 2 — Survivorship universe (the backtest-integrity problem)

Crypto survivorship bias inflates backtest returns **200–400%** (one cited strategy: +2,800% survivor-only → +680% reconstructed). **Non-negotiable** for the convex thesis — we're explicitly hunting in a population where ~90% go to zero.

- **CoinGecko `GET /coins/list?status=inactive`** (cheapest, partial) — delisted-coin IDs added since Apr 2024; `include_inactive_source` (Jan 2026) extends it. Works on any paid plan ($35+). Limitation: only coins CoinGecko tracked pre-death.
- **CoinMarketCap UCID sweep** (most complete, $79 one-shot) — CMC assigns permanent numeric IDs; dead coins keep theirs + their history. Batch-pull all ~40K UCIDs → ~23K real coins incl. dead, daily OHLCV to listing. Startup $79/mo for all-time; **run once (~22h), store in SQLite, cancel.** This is the gold-standard survivorship-free universe.
- **Binance Vision archives** — free intraday for delisted *Binance* pairs (need the symbol list first; cross-reference CMC).

## Layer 3 — New-liquidity / early-entry detection (ENTRY)

**Keepers**
- **GeckoTerminal API** (CoinGecko on-chain) — `/onchain/networks/{network}/new_pools` is the **most direct free "new DEX pools with creation timestamp + liquidity + volume" endpoint.** 200+ chains, no key, 30 req/min. `pip install geckoterminal-api`. **Primary new-liquidity feed.**
- **DexScreener API** — free, no key; WebSocket for new token profiles + `/token-boosts/latest/v1` (early-attention/promotion signal). No OHLCV history (discovery only). 60 req/min.
- **SolanaTracker** (€50/mo) — purpose-built pump.fun/PumpSwap: `/tokens/latest`, **bonding-curve graduation proximity** (catch at 80%+ before graduation), risk scores, OHLCV from first trade. Free tier 2,500 req/mo is a toy; €50 Advanced = 200K/mo. pump.fun has **no official API** — third-party indexers only.
- **The Graph (Uniswap V3 / PancakeSwap subgraphs)** — free 100K queries/mo; `PoolCreated` events = exact pool-creation moment + full trade history for **EVM backtesting**. ~12–24s indexing lag → backtest tool, not real-time.

**CEX-listing detection** (highest-conviction catalyst): **detect yes, anticipate no.** Poll Binance's undocumented JSON `…/cms/article/list/query?type=1&catalogId=48` at 30s (free, ~30s cache); CoinMarketCal API for the upcoming-listings calendar (community-sourced, noisy). Sub-second requires a paid feed (cryptolisting.ws) — out of scope for research/signal.

**Nice-to-have:** DexPaprika (free SSE streaming + creation-date filter, no auth — depth unverified); Birdeye (best Solana analytics depth but paywalled immediately).

**Critical landmine:** since **March 2025, 95%+ of pump.fun graduates migrate to PumpSwap, not Raydium.** Any pre-2025 code/tool watching Raydium for graduates is watching empty events — verify PumpSwap support.

## Layer 4 — Smart-money on-chain (ENTRY — the core differentiated edge)

**Key architecture insight:** *identifying* smart wallets ≠ *monitoring* them. The cheap path: discover a curated list of 100–300 known-good wallets quarterly (Arkham free UI + Dune SQL on historical PnL), then watch that static list cheaply (Helius webhooks / Moralis free). The expensive "query any token's smart-money netflow right now" is Nansen's core value.

**Keepers**
- **Nansen** (Pro $49/mo + ~$0.05/Smart-Money call via x402) — only production-grade smart-money labels + accumulation signals in one API (`smart-money/netflows`, `tgm/holders`). 19 chains incl. SOL/Base/BSC. Free tier's 10× credit penalty makes it unusable free → Pro is the anchor signal layer. **The "what are smart wallets accumulating now" engine.**
- **Arkham** — **free UI** for entity/whale discovery (deanonymized labels, 98% ETH/SOL labeled). API requires application (opaque pricing). Use the free UI for discovery.
- **Dune** (free: 2,500 credits/mo, API incl.) — SQL over decoded on-chain data; fork community "top profitable wallets" queries to **build your own smart-wallet list** from historical PnL. `dune-client`. Research/discovery layer, not real-time.
- **Helius** (Solana, free: 1M credits/mo, webhooks) — watch your curated 50–200 Solana smart wallets via webhooks; `getTokenLargestAccounts` for holder concentration. The Solana monitoring + low-latency execution layer.

**Nice-to-have:** Cielo Finance ($89/mo — cleanest real-time copy-trade feed: wallet bought X + PnL track record); Moralis (free 40K CU/day — cross-chain wallet watching on EVM); Birdeye `/top_traders` (fresh smart money per new token).

**Skip:** Bitquery (free = 10 rows/req toy; commercial opaque/expensive), Glassnode (BTC/ETH macro only, no SOL/Base/BSC, $999+ for API), Whale Alert ($500K threshold misses early accumulation; size ≠ smart), Allium/Footprint (enterprise).

## Layer 5 — Social / attention velocity (ENTRY acceleration + EXIT saturation)

We want the **second derivative** — acceleration in unique-author mentions — for entry, and euphoria saturation for exit. No API gives the 2nd derivative natively; compute it from the time series (7d rolling mean → 1d change → z-score; z>2 on Δ(unique_social_volume) is a clean entry trigger with academic precedent).

**Keepers**
- **Santiment Pro $49/mo** — **the anchor.** The deepest cheap *backtestable* social history: Twitter to **2018**, Reddit to **2016**, Telegram to **2016**. `social_volume_total` / `unique_social_volume_total` (deduped author-level) at 5m/1h/1d. `sanpy` SDK with backtest utilities. Pro has 30-day lag on restricted social metrics (fine for backtest); **Max $249 needed for real-time/live** signal.
- **CoinGecko trending + 500+ categories** (free Demo) — best free narrative/sector taxonomy; trending is snapshot-only (poll + log your own history from today).
- **DefiLlama** (free, `api.llama.fi/protocols`) — TVL by category = **capital-level narrative rotation**. When social acceleration (Santiment) AND TVL inflow (DefiLlama) align on the same narrative → conviction.
- **Reddit free** (subreddit subscriber growth) + **Telegram/Telethon** (channel member growth) — free community-growth pollers; both *lagging* (grow after the pump) → confirming/exit signals, log from today.

**Skip / out of scope:** **X/Twitter API is priced out** in 2026 — no historical for new accounts; full-archive = legacy Pro $5K/mo (closed to signups); pay-per-use is 7-day-recency only. Let Santiment carry Twitter social volume. The TIE (cleanest PIT Twitter to 2017, but institutional ~$1K+). Kaito (best narrative-mindshare concept but Yaps shut Jan 2026, no self-serve API). CryptoCompare social (follower *counts* = size, not velocity).

## Layer 6 — Token safety / fraud gate (GATE-0, defensive only)

Not a quality filter — we *want* low-quality high-convexity. Purely: will this **steal the money on entry** (honeypot / rug / malicious mint)? The one downside that still stings at 1%.

**Keepers (all free)**
- **GoPlus `token_security`** — **primary workhorse.** Keyless, 30 req/min, 43 chains incl. **Solana**. ~40 flags: `is_honeypot`, buy/sell tax, `is_mintable`, `hidden_owner`, `top10_holder_percent`, LP lock. Call this on every token.
- **Honeypot.is** (EVM: ETH/BSC/Base, keyless) — sharper live buy/sell *simulation* than GoPlus's flag. Run both; agree=trust, disagree=manual review.
- **RugCheck.xyz** (Solana, free key 60 req/min) — the Solana standard: riskLevel + mint/freeze authority + LP-lock % + top-holder concentration + creator history.
- **Solana RPC `getTokenLargestAccounts`** (free, via Helius/public) — top-20 holders → compute concentration independently.

**Gate logic (hard kill if ANY true):** honeypot (either source) · sell_tax >15% · mintable AND owner-not-renounced · top10 >50% · LP <5% locked/burned · RugCheck CRITICAL.

**Nice-to-have:** SolSniffer (Solana batch 100/call), Webacy Pro $10 (bundling/sniper detection EVM), Bubblemaps (holder-cluster graph — the "50 wallets, one funder" pattern; API beta/gated). **Skip:** Token Sniffer ($99 vs GoPlus free), Etherscan topholders ($199 Pro — GoPlus gives top10 free), StaySAFU (no API).

---

## Crypto-specific landmines (carry into the build)

1. **Survivorship is brutal** — always reconstruct the dead-token universe (Layer 2) before any backtest. 200–400% inflation otherwise.
2. **Wash trading inflates CEX volume** — Layer-1 liquidity must be wash-aware; trust on-chain DEX liquidity (GeckoTerminal) over reported CEX volume for the long tail.
3. **PumpSwap, not Raydium** (since Mar 2025) — verify any pump.fun tooling.
4. **24/7, no close** — pick a snapshot bar (likely hourly + a daily 00:00 UTC anchor); the equity batch-cadence assumptions don't transfer.
5. **On-chain PIT backfill is the hardest/weakest backtestable layer** — Nansen historical-holdings + Dune queries can reconstruct it, but it's costly and partial. The smart-money *entry* signal is the most exciting and the least cheaply-backtestable — flag this honestly in validation.
6. **X/Twitter is closed** — don't architect any dependency on direct X API; route social through Santiment.
7. **Reflexive signals are manipulable** — social can be botted; weight on-chain (smart-money, holder flows) over social where they conflict.
8. **Separate venv** — do NOT add ccxt/web3/solana-py/sanpy to v1's shared venv (CLAUDE.md: never touch `~/alpha-signal/`). New product → new venv + new SQLite DB.

---

_Full per-source detail (free-tier limits, endpoints, rate limits, Python access, ~16 sources per layer) lives in the 2026-06-09 research-agent transcripts; this doc is the distilled decision layer. Re-verify pricing at subscribe time._
