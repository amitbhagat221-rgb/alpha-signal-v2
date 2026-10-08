# Plan 0021 — News page redesign: an editor, not a feed

**Status:** approved 2026-10-05 in its second form ("yes this sounds much better go on"). E0–E2 live on the cockpit, E3 first feeds added, E4–E6 open.
**Asked for (Amit, 2026-10-04):** "there are 1031 stories, no one can read it … informed about latest, a view on future outlook, emerging and new, sectors to look out … understanding of geopolitics and tech and how it is shaping the future … engaging, simple, no unnecessary jargon." A busy day allows a few minutes, not 20 minutes a story.

## 0. Why the first design was dropped (same day)

The first version of this plan sorted every article into storylines that emerged from the articles. A 3-day smoke run worked mechanically and was rejected by Amit on sight (2026-10-05: "enriching ~1000 stories is a waste of time and effort … it does not fundamentally cover what I want"). He was right on three counts:
- **Bottom-up.** It tagged about 1,170 articles a week and hoped themes would appear. What appeared was a tidier market wire ("Busy Indian IPO market", "Tata Sons boardroom rift"), not an understanding of the world.
- **Wrong raw material.** Every article comes from Economic Times and Livemint market desks. Sorting stock-move headlines does not produce geopolitics or technology insight.
- **The per-article tagging only served a feed nobody reads.**

Kept from that build: the writing validators, the card shape, the page shell, the queue-kind pattern. Removed: `sources/news_storylines.py`, its three tables, its two kinds.

## 1. The idea

Work top-down. Decide what the reader needs to understand, then let one pass a day read the raw headlines and write the page.

**The world in 7 themes** — a fixed map in `config.NEWS_THEMES`, chosen by Amit, not discovered:
1. Interest rates, the dollar and the rupee
2. Oil, energy and the Middle East
3. US–China rivalry, tariffs and supply chains
4. AI and the chip build-out
5. India policy, capex and reforms
6. Energy transition and critical minerals
7. Consumer and credit health in India

Each theme is one living note: where it stands, what changed, what could happen next, which Indian sectors gain or lose. Rewritten about weekly.

## 2. The page

| Section | Reading time | Refreshed | What it is |
|---|---|---|---|
| Today | 2 min | daily | Three things that matter: what happened, so what |
| The world in 7 themes | 1 min each | weekly | The living notes; the ones that moved this week are marked |
| On the radar | 1 min | weekly | Two or three new, early things that fit no theme yet |
| Sectors to watch | 1 min | weekly | Three sectors the news helps, three to be careful with, each with a reason |
| Learn | 3 min | weekly | One explainer, alternating geopolitics and tech (E4) |

About 3 minutes on a busy day; 15 minutes once a week for the whole picture. A theme opens to a deep read (story so far, the two "what could happen next" branches, timeline, sources) at `/news/theme/{id}`. The old feed stays at `/news/all`.

## 3. Rules for every word (validator-enforced)

- Plain words; an unfamiliar term is explained in the same sentence.
- Average sentence at most 20 words; a word cap per field.
- No numbers in any text (same rule and scanner as the dossiers).
- Sector names only from our own sector list. Stocks shown on a theme are counted from `news_article_stocks`, never named by the model.
- No advice. "Sectors to watch" is labelled as a reading of the news, not a recommendation.
- Only what the headlines support: no background from the model's memory.

## 4. How it is built

`sources/news_editor.py` + three `llm_tasks` kinds on the subscription worker, one pipeline step `news_desk` after `news_brief`:

| Kind | When | Reads | Writes |
|---|---|---|---|
| `news_today` | daily, one task | the day's raw headlines (title + RSS summary), unread ones only | `news_today` (3 items) and `news_theme_articles` (each relevant headline filed under a theme) |
| `news_theme` | per theme, when its note is 7 days old and new headlines are filed | the headlines filed under the theme since the last note | `news_themes` (the note), `news_theme_history` (timeline) |
| `news_week` | weekly, one task | the theme notes, the week's unfiled headlines, news flow per sector | `news_week` (radar, favour, careful) |

Cost: about 7 daily tasks and 8 weekly tasks a week, against about 1,170 article tags before. Thresholds live in `config.NEWS_EDITOR`. Heat and "moved this week" are arithmetic on read.

## 5. Phases

- **E0 — done 2026-10-05.** Dead Moneycontrol RSS retired; an empty or failing feed now writes a `run_events` row. The 941 queued article-tagging tasks cancelled (`status='expired'`).
- **E1 — engine: built 2026-10-05.** Module, 5 tables, 3 kinds, step, 6 tests. Smoke on 4–6 Sep: 383 headlines read in 3 tasks, 89 filed, 7 notes, one weekly edition, every task accepted within 2 attempts. Replay of 31 days: `python -m sources.news_editor bootstrap --days 31`.
- **E2 — page.** `/news` as §2 (without Learn), `/news/theme/{id}`, `/news/all`. Design review at three widths. Done when Amit reads the daily part in 3 minutes.
- **E3 — sources for geopolitics and tech.** The smoke shows the gap: themes 3 and 4 got 6 headlines each in 3 days against 32 for rates. Candidate feeds through the host door, canary on 3 items each: first more sections of hosts already declared (ET and Livemint world / technology), then one world-news and one technology feed. Done when themes 3, 4 and 6 each get at least 25 headlines a week.
- **E4 — Learn.** `news_explainer` weekly kind (what it is → why now → who it helps or hurts in India → what would change the view), library at `/news/learn`. Needs E3: an explainer written without sources would be written from memory.
- **E5 — retire per-article tagging.** After `news_desk` has run clean for two mornings: move the readers of `news_briefs` (CIO desk brief in `alpha_mcp/org_kinds.py`, MCP `news_brief`) to `news_today`, drop the steps `classify_news` and `news_brief`, turn `/news/all` into a plain searchable headline list. Until then the daily tagging still runs (about 170 articles a day).
- **E6 — review after two weeks.** Are the 7 themes the right 7; note quality; add our own sector model data to "Sectors to watch" (today it reads the theme notes and news flow only); morning email gets "Today"; reference page `docs/reference/news.md`; ADR "the news page is edited top-down from fixed themes".

## 6. Not in this plan

- No news factor: nothing here feeds ranking.
- No full-article scraping (title and RSS summary only), no paid sources.
- No change to `sentiment_scores` or the per-stock news on the stock page.

## Implementation notes

- **Changing the themes:** edit `config.NEWS_THEMES`. A removed theme is retired (note and history kept); a new one gets its first note once 3 headlines are filed under it.
- **The replay continues from the smoke run** rather than starting clean: a daily task for an already-read day has the same input, so the queue would not run it twice.
- **"Sectors to watch" does not yet use our own sector data** beyond news flow per sector (E6).
- **Today's items carry their source article ids**, so each item can link to its sources; this is the link the first design could not make.
- Tables are declared "kept as-is" in `datamodel/reconcile.py` until news moves into the plan-0017 model.
- **Replay result (2026-10-05):** 32 daily editions (4 Sep → 5 Oct), 5,152 headlines read, 1,368 filed under a theme, 30 note rewrites, weekly edition as of 5 Oct.
- **A claim above about 50 KB cannot be read by the worker** (the tool result is spilled to a file and the worker has no file tool; `MAX_MCP_OUTPUT_TOKENS` did not lift it). So a day's headlines go as one text block capped by `today_max_chars` (summaries shrink first, the oldest headlines overflow to a second task that files them without replacing the edition), and `news_theme` claims one theme at a time. A 4-theme batch left 16 tasks claimed and never submitted during the replay; `bootstrap` now fails on claimed-but-unsubmitted tasks, and a theme task older than the note it would overwrite is rejected as stale.
- **E3 so far:** `et_tech`, `livemint_ai` and three Google News theme searches (`gnews_trade`, `gnews_chips`, `gnews_transition`, top 30 results each) added to `sources/rss.FEEDS`; first fetch 175 headlines. General "world" feeds (ET international, Livemint news, Google News WORLD topic) were probed and rejected: celebrity and incident noise. Open: the weekly "on the radar" picked items that belong to themes 4 and 6 on the first day of the new feeds; watch whether the daily filing catches them once the feeds have run a week.
- **E2 as built:** page about 1,400 words (Today about 340, theme cards about 110 each) against a 900 target; "Stocks in the news" hidden on the theme page because `news_article_stocks` links on common words (OIL, GLOBAL, ROUTE).
- **Mistake to not repeat:** the old storyline tables were dropped while production still ran the old page code, so `/news` returned a 500 until the restart. Switch the page first, then drop.
