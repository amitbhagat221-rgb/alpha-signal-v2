# ADR 0092 — Paper books: six strategies, ₹10 L each, one page, the pre-registered rule as the default

**Status:** accepted 2026-11-01 (Tier B) · **Supersedes:** nothing; the SMALL paper sleeve (ADR 0073) and the multibagger forward books keep running

## Decision

1. `tools/paper_books.py` replays six strategies as paper books of ₹10 lakh each from the June 2026 anchor to the latest close, on the research score panels (`data/lh`) and the cockpit's own `daily_picks`: Mid slow, Mid fast, Small slow, Small fast, Multibagger best 10, and **Published picks (Mid 10 + Small 10)** as the sixth. The sixth is the only book with no hindsight at all: it holds what the cockpit showed that morning.
2. Every weight option is precomputed (3–4 per book) and the page switches client-side. **The default is the pre-registered rule** the sleeve runs (slow_v2, fast_select, best 10, 10+10), never the option that leads this window; each option's card quotes its 2022–26 book evidence (slow_select, not slow_v2, tested best among the slow scores: SMALL +19.7 %/yr, t 2.08). The page names the window's leader next to it.
3. Money, not IC: each book pays the calibrated cost model (`tools/lh_costs`, STT reported on its own), realised short-term gains are taxed at 20.8 %, and "if sold today" taxes the unrealised gain too. The benchmark is the tier's price index bought once; the published book takes half of each.
4. The trading cockpit's `/book` keeps **Zerodha + Track record** only; the sized HRP book, Ways to weight, Risk and Paper sleeve tabs are gone (the modules stay). Track record opens with a plain-words statement of what it measures. The strategies' money view lives on the Ops console at `/paper-books`.

## Why

Amit (2026-11-01): the Book page was "confusing and not testing any strategies"; the question is "the efficacy of the model and the strategy" in rupees, with rotations, STT, STCG and the right benchmark. The existing records were a daily-basket IC view (Track record), a sleeve started 2026-10-13, and multibagger books started 2026-10-16: none answered "₹10 L in June, what now".

The rules the books run are the sleeve's (ADR 0073): slow = top 20 by the 3-month average score, sold below rank 60 after 12 months; fast = top 20, sold below rank 40. The multibagger book uses the desk's ranking as it stood each month (the old score to September, the thesis rank from 2026-10-15), so a model change shows up as a rotation, not as a rewrite of June.

## Consequences

- Honesty labels on the page: the walk-forward options are out of sample; slow_v2 / fast_v1 were fixed in October 2026 and have seen these months; "as published" is the live record. Five months is one window, not a verdict; the card quotes what each backtest promised.
- `/book`'s dropped tabs are not redirected; `today.html`'s sleeve link now points at the Ops page. `views.paper_sleeve` still serves the stock page's long-hold rank.
- Monthly refresh after the sleeve's score refresh (`run.sh paper_books`, Tier A: crontab waits for Amit). Until then `python -m tools.paper_books` by hand; the page says "stale" after 40 days.
- First read on real money: when a book clears its index after costs and tax over 12 months, with the published-picks book agreeing in sign.
