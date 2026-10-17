# Plan 0028 — The macro explainer: map, clock, pulse

Status: in progress (side plan) · 2026-10-17 · owner Amit · phase 1 (mockup) built 2026-10-17 · **live in the cockpit at /macro 2026-10-17** (ADR 0079)
Builds on: ADR 0078 (industry explainer, no numbers in prose), plan 0021 (news storylines)
Mockup: [docs/research/0014-macro-explainer-mockup.html](../research/0014-macro-explainer-mockup.html)

## Why bother

You already know what GDP is. You know FIIs sell when the dollar gets strong, and that the RBI cuts rates when inflation cools. What's missing is the thread that ties it together. Why did the rupee fall this week? Who decided that? What happens to steel, IT and banks next?

Most people pick this up from years of reading newspapers. We'd rather build the newspaper's brain once and let the cockpit feed it every day.

## Reader flow (v3, after Amit's review on 2026-10-17)

Amit's verdict on v2: "no idea where to start and what to do; the story should be simple and in Finshots style; a new investor should be able to read the basics first." The map, clock and pulse stay as the **data model** underneath; the page a reader sees is organised by what the reader needs, in this order:

1. **Start here.** Two doors: "I'm new to this → learn the basics" and "I know the basics → read today's brief", plus a three-step picture of how the page works and the whole course in three questions (oil, America, Indian money).
2. **The framework.** Twelve short chapters, read in order. *Pitch (v4, Amit: "too basic, I am not this much of a noob"): the reader knows the vocabulary; chapters open with a claim, not an anecdote, and spend their words on India-specific transmission, e.g. external-benchmark loan repricing, FX intervention as a liquidity operation, quasi-fiscal oil losses, the DII ownership shift, the India premium as a duration asset. Each ends with "where it stands now" and an indicators-to-track table marking live versus no feed.* Originally each chapter was a Finshots-style story: a hook, the idea in plain words, one simple picture, a "see it today" box with live numbers, "so what for your stocks", the words just learned, and a "next chapter" button. Progress is remembered in the browser. Chapters: why the economy matters · where India's money comes from · the five engines · inflation and food · the RBI as thermostat · why oil matters · foreign versus Indian money · why US rates matter · the government and politics · the four seasons · how a shock travels · how to read the daily brief.
3. **Today's brief.** Five minutes: a one-line verdict, the season, four warning lights (oil, America, Indian money, the RBI), what changed yesterday, who wins and loses, what's coming, the risk radar. Every item links back to the chapter that explains it.
4. **Go deeper.** The reference shelf: the plumbing, twin deficits, engines, referees, political economy, history, the world cards, the shock walk-through, the playbook, the data room, storylines, worked lessons, glossary. This is where the v2 map, clock, pulse and playbook content now lives.

**v5 (2026-10-17, Amit: "thinner on graphs, diagrams, illustrations; needs a separate Indian and geopolitical international framework; rich historical context").** The framework splits into a prologue, an **India framework** (balance sheet, growth engines, inflation, the RBI's three levers, oil and the rupee, flows and positioning, fiscal and political economy, a decade of drawdowns), a **global and geopolitical framework** (how six economies reach India, the dollar and US rates, oil and the Gulf's chokepoints, China, Europe and Japan, Russia and sanctions, conflict on India's borders) and a **synthesis** (regimes, the 2026 case study, the daily routine). Every chapter carries charts or diagrams from our data back to 2015 and a history block; episode statistics and event studies (Balakot, Galwan, Sindoor, the yuan devaluation, the Ukraine invasion, the carry unwind, the 2024 result) are computed, not written. Finding that changed the text: since 2022 a crowded foreign futures short has **not** been followed by better-than-normal Nifty months (crowded longs were followed by weaker ones), so the "short-covering fuel" line was removed everywhere.

**v5.1 (2026-10-17, Amit: "does this include South Korea's chips, AI innovation, the Ukraine and Iran wars and other global tensions?" → "yes please build those").** Two global chapters added: **technology, AI and the chip cycle** (the AI value chain and India's place in it, an India AI build-out basket against IT services from our own prices, Korea's record chip exports, debt-funded AI capex and early credit stress, export controls, India's semiconductor mission) and **hot spots** (a weekly heat matrix of six conflicts by channel into India, escalation ladders for the Iran war and the Taiwan Strait, one card each for Iran and Hormuz, Russia–Ukraine, Taiwan, the South China Sea, the Korean peninsula and India's borders). Facts were web-checked on 2026-10-17 and sourced on the page; web figures sit in a separate "external readings, not yet a feed" box. Correction: the 2026 shock is the **Iran war from 28 February**, not a July "Gulf disruption"; the episode window and every mention were fixed. **Update cadence** is now a table on the Start page: charts and brief daily, storylines weekly (the news desk's actual cadence), hot spots weekly plus same-day on a major escalation, regime and house view weekly, event studies and external readings monthly, chapter prose quarterly or on a trigger. New feeds needed: Korea monthly exports, a semiconductor index, memory-chip prices, AI credit spreads, Hormuz tanker transits, a geopolitical risk index.

## The idea in one line

Three layers that move at three speeds: a **map** of how the economy works, a **clock** that says where we are, and a **pulse** that says what changed today. Each one points back to the others. A fourth tab, the **playbook**, turns the three into decisions, and a fifth, **learn**, teaches you to read the raw releases yourself.

Think of it like learning cricket. The map is the rulebook and the history of great matches. The clock is the scoreboard: overs left, run rate, wickets down. The pulse is ball-by-ball commentary. The playbook is the captain's field setting for this pitch. Commentary without the rulebook is noise. The rulebook without the scoreboard is a textbook.

## Layer 1 — The map (written once, refreshed quarterly)

Same twelve-card style as the industry pages. Plain words, no numbers in prose.

**India**
- **The plumbing.** Household savings go into banks and markets. From there they become loans and government borrowing. The current account and foreign money close the loop. FII and DII flows sit inside this loop, not beside it.
- **The engines.** Consumption, government capex, private capex, services exports and goods exports. One card each: what drives it, what kills it, where it stands, and the live gauge from our feeds that tracks it.
- **The referees.** The RBI, the Finance Ministry and the Budget, the GST Council, SEBI and the states. For each: what they control, how they usually behave, and the next move written as a likelihood.
- **The political economy.** What this government says it wants and what it has actually done: capex-led growth, fiscal discipline, PLI and self-reliance, welfare transfers, coalition arithmetic since 2024, the state election calendar. Policy guesses are written as likelihoods with reasons. Neutral tone, no cheerleading.
- **History that still bites.** 1991, 2008, the 2013 taper tantrum, demonetisation, GST, IL&FS, Covid, the 2022 inflation spike. Each gets one line: "what it teaches for today".
- **The twin deficits and the rupee** *(added)*. Why India's oil bill, the current account and the rupee move together, and what the RBI can and cannot do about it. This is the single most useful chain for an Indian equity investor and it gets its own card.

**The world: one card per economy that moves India**
- **US.** The Fed, the dollar, Treasury yields, tariff politics. Channel into India: FII flows, IT demand, the rupee.
- **China.** The property bust, exported deflation, China+1, commodity demand. Channel: metals, chemicals, the import price ceiling.
- **Europe.** Energy prices and export demand.
- **Japan.** The yen carry trade. It explains the sudden "everything sells off at once" days.
- **The Gulf and Russia.** Oil, remittances, discounted crude, the shipping routes.

Each card carries the same fields: the leadership's political leaning, the policy guess, the channel into India, and the Indian industries exposed. The exposed industries are not written by hand: they come from the reverse dial index (layer 3).

## Layer 2 — The clock (weekly)

- **Two regime quadrants, one for India and one for the US.** Growth up or down against inflation up or down: goldilocks, reflation, stagflation, deflation. One dot shows where we are, and a faint trail shows where we've been. India uses the three-month change in IIP growth and CPI inflation; the US needs US CPI and industrial production (phase 5).
- **The rate cycle.** Hiking, on hold, or cutting, for the RBI and the Fed, with the stale-data flag when the feed lags a decision the news has already reported.
- **A liquidity gauge.** Money-market rate, bank credit, forex reserves.
- **Market gauges: what is priced in** *(added)*. The data says where the economy is; markets say where they think it is going. FII index-futures positioning (long share and its percentile since 2022), FII and DII cash flows, India VIX and its percentile, the rupee, the US 10-year yield, copper against gold. Later: the Indian yield curve, real rates and the gap between the Nifty earnings yield and the bond yield.
- **A nowcast panel** *(added, phase 5)*. GDP arrives two months late. High-frequency activity says it first: GST collections and e-way bills, power demand, auto sales, diesel sales, air traffic, PMIs.
- **A dated event calendar.** RBI policy meetings, the Fed, CPI, GDP, the Budget, elections. Exact dates load from the published schedules, never from the LLM.

The clock is computed from feeds. The LLM never writes a number here.

## Layer 3 — The pulse (daily)

- **What moved.** Daily change in every macro series we hold, ranked by how unusual the move is (today's change against a year of daily changes), not by raw size.
- **The latest monthly prints.** IIP, core sector, CPI and trade, each against its previous print.
- **Flows.** FII and DII net buying, the day and the last twenty sessions.
- **Storylines.** Plan 0021's news themes, grouped.
- **So what.** For each move: which industries care, in which direction, and which map card explains it.

The "which industries care" part is nearly free. All 38 industry explainers already list their macro dials. Flip that list around and every dial gets its own audience. When Brent jumps, the pulse can say to open Oil & Gas, Chemicals, Aviation, Paints and FMCG, and say which of them gain and which lose. The same index lists the dials no feed covers yet (monsoon, US tariffs, China producer prices), which is the feed backlog in priority order.

## The playbook (added)

The map, clock and pulse describe. A macro investor also has to decide.

- **What worked in each regime.** Sector index returns against the Nifty in the month after each regime, from our own price history (2016 onward, market-implied regime from copper against gold and Brent's momentum). Shown with the number of months and the t-statistic. It is in-sample and does not touch the model. Any tilt that wants to move a weight goes through the factor promotion rules first (|t| ≥ 2.5 plus the multiple-testing haircut).
- **The house view.** A base case, an upside and a downside, each with a likelihood in words, the trigger that would confirm it, and the industries that win and lose. Same shape as the industry pages' "call".
- **A risk radar.** A short checklist of tail risks with thresholds computed from feeds: an oil spike, a rupee slide, the US 10-year above a level, VIX in its top decile, FIIs at an extreme short. Each line is green, amber or red with the reading beside it.
- **An asset-class lens.** What each regime has usually meant for Indian equities, government bonds, gold and cash, for an investor who holds all four.
- **A call log.** Every weekly clock reading and house view is stored with its date and scored a quarter later. Calibration, not conviction, is the goal: grade the evidence and size by it, rather than wait for proof.

## Learn tab (the curriculum)

Twelve short lessons, each with a real exercise built on our own data:
1. Read an RBI policy statement: what changed, what the hawks and doves said.
2. Read a Fed statement and the dot plot.
3. Read a CPI release: headline, core, and food's role in India.
4. Read a GDP release: the expenditure split and the GVA-versus-GDP gap.
5. Read the balance of payments: current account, capital account, reserves.
6. Read the Budget: fiscal deficit, capex, borrowing, what's off-balance-sheet.
7. Read FII and DII flows without over-reading them.
8. Read a China data dump: PMI, PPI, credit.
9. Connect a global shock to an Indian sector, end to end.
10. *(added)* Read the oil price and the rupee together: the twin-deficit chain.
11. *(added)* Read the bond market: the yield curve, real rates, and what an inverted curve is telling you.
12. *(added)* Read derivatives positioning: FII index futures, put-call ratios, and why an extreme short is often a contrarian signal.

Each pulse item links to the lesson it leans on. You learn by meeting the concept when it matters.

## Data

**Already in the DB (checked 2026-10-17):** CPI by component (new base from 2025-01; the old series ends 2025-03, so year-on-year inflation has a gap from 2025-04 to 2025-12), IIP and core-sector indices from 2022, exports and imports, Brent, the rupee, the US 10-year yield, gold, silver, copper, aluminium, India VIX, Nifty sector indices from 2015, the money-market rate (monthly, last value July 2026), **FII and DII daily cash flows (from 2026-04-30)**, **FII, DII, pro and client derivatives positioning (from 2022-01-03)**, NSE broad indices, news themes, regulatory events.

**To add, each through the host door (`hosts.HOSTS`):**
- **Flows.** Backfill FII and DII cash flows before 2026-04-30 (nselib).
- **Policy.** Repo-rate decisions and the RBI and Fed meeting schedules (today the money-rate series is three months behind a reported rate rise).
- **Global gauges.** The dollar index, US CPI and industrial production (FRED), China PPI and PMI, European gas (TTF), container freight, global PMIs.
- **India fundamentals.** Quarterly GDP, the fiscal deficit, forex reserves, bank credit growth, the 10-year G-sec yield (we hold only an ETF price), Nifty PE and earnings yield.
- **Nowcast.** GST collections (ours stop in 2023-11), e-way bills, power demand, auto sales, diesel, air traffic, monsoon and reservoir levels.

## Refresh cadence and the archive (v5.2, 2026-10-17)

Amit: "what's the refresh cadence? Past data need not be lost but saved with a date filter in the cockpit." Rule: **nothing on the macro page is overwritten.** Every refresh appends a dated snapshot; the page has an "As of" date filter that opens any past date as it read on the day.

| Part | Cadence | Stored as |
|---|---|---|
| Charts and live numbers | daily, after the evening run | the data history itself; viewing a past date stops each chart at that date |
| Today's brief (lights, unusual moves, radar, verdict) | daily | one `brief` snapshot per day |
| News-desk storylines | weekly, smaller mid-week passes | already kept in `news_theme_history` (since 2026-09-06) |
| Hot spots (heat matrix, ladders, cards) | weekly, plus same day on a major escalation | one `hotspots` snapshot per refresh, with source links |
| Regime clock, house view, call log | weekly; data as released | `regime`, `house_view` snapshots; the call log scores each house view a quarter later |
| Event studies, playbooks | monthly | `playbook` snapshot with the computation version |
| External readings (web) | monthly until each becomes a feed | `external` snapshot with URL and check date |
| Chapter prose, history blocks | **monthly** (Amit 2026-10-17), sooner on a trigger | `chapter` versions, one per chapter |

**Storage (built on branch `desk-archive`, 2026-10-17).** An append-only table `desk_snapshots(snapshot_date, part, item, version, payload, sources, method, created_at, PRIMARY KEY (snapshot_date, part, item, version))`, written with `INSERT OR IGNORE`, declared in `schema.sql` and `tables.TABLES`, with a freshness check that fails if the daily `brief` snapshot is missing. The cockpit route takes `?as_of=YYYY-MM-DD`; the date picker lists the dates that exist; charts read the full history and truncate at `as_of`. The same principle should extend to the industry explainers, which today overwrite their row in `sector_metadata`.

**Point-in-time honesty.** A live snapshot records what the page said that day. The eight-date archive in the mockup was rebuilt retrospectively from data dated on or before each date, with the regime using only releases published by then; the verdict line and hot spots were not written for those dates and say so.

**Links.** Terms link once per chapter to the chapter that explains them, an authoritative source (RBI, MoSPI, NSE, AMFI, FRED, the Fed, GST Council, SEBI, DGTR, ISM, EU CBAM) or the cockpit's industry page; light readings link to their chart and source. Rule: a figure on the page is either from our feed (linked to its chart) or from the web (linked to its source and dated).

## Proposed: replace the Markets (news) page with this, one desk for both (2026-10-17, not yet approved)

Amit: "replace the news part with this … solve any duplication of effort … a unified way." Principle: **one desk, one store, many views.** Ingest is unchanged; one editorial pipeline writes dated objects; the Markets page, Today page, Sectors pages, morning email and MCP all read the same objects.

| Today | Unified |
|---|---|
| Markets › News today (`news_today`, daily) | Brief › "What changed": the same daily task, extended to read the four lights and unusual moves and to write the verdict |
| Markets › Sector call (`sector_briefs`, model) + `news_week` favour/careful | Brief › "Who wins, who loses": model column beside news column, labelled |
| Markets › The world in 7 themes (`news_themes`, weekly) | Kept as the "what is happening" layer; each theme links to its home chapter and any hot-spot card |
| Markets › On the radar (`news_week`) | "Emerging" inside the Hot spots tab |
| Plan 0021 E4 `news_explainer` (not built) | Dropped: the framework chapters and worked lessons are the learn layer |
| Today page › Market regime | Reads the same regime snapshot as the brief |
| `news_briefs` + `classify_news` per-article tagging | Retired as plan 0021 E5 already planned; MCP and the CIO desk read the brief |
| Morning email | Verdict, four lights and three changes from the same brief snapshot |

Producers after the change: `news_today` → brief (daily), `news_theme` unchanged (weekly), `news_week` → hot spots incl. radar and the news-side sector reading (weekly, with a web check), a framework-chapter kind (quarterly). Storage: the news tables are already dated (`news_today` by day, `news_theme_history`, `news_week` by date) and stay the archive; `desk_snapshots` holds every other part. Page: `/markets` keeps its URL and nav slot, tabs Today · Themes and hot spots · Framework · Archive · Deeper; `/news` redirects stay. Rollout as a side-by-side preview first (the cockpit-preview recipe), then swap.

**Decided 2026-10-17 (Amit: "framework chapters and history blocks should be monthly, rest I agree, but all these should be saved in a database and should have a filter for date").** Every part above is stored in `desk_snapshots` and every view takes the "As of" date. Branch `desk-archive`: `output/desk_archive.py` (`save` is append-only and versioned, `latest(part, item, as_of)`, `dates`, `summary`), table in `schema.sql` + `tables.TABLES`, reconcile exemption, `tools/sector_explainer.save_explainer` now archives every industry-explainer version, `tools/desk_archive_backfill.py` (idempotent, transactional `--dry-run`), 5 tests. Dry run against the live DB: 79 rows across 8 parts (8 briefs, 8 regime readings, 21 chapters, 38 industry explainers, hot spots, house view, playbook, external readings). Merged and backfilled 2026-10-17.

**Live 2026-10-17 (Amit: "go ahead and make things live in cockpit").** `/macro` in the Daily section renders every part from `desk_snapshots` for any As-of date (`cockpit/macro.py`, `macro_frame.html`, `_macro_brief.html`, `_macro_start.html`). `output/macro_desk.py` computes the brief point-in-time (lights, regime from published IIP/CPI, six unusual moves with the industries that read them, risk radar, the news desk's edition and storylines) and runs daily at 05:45 UTC (`run.sh macro_desk`; `desk_snapshots` is `freq: daily`, so a dead producer shows stale). Two written parts are dated rows set by hand: `brief_note` (title, verdict, winners/losers, what's coming; validated no figures; flagged after a week) and `rbi` (seeded from the news desk: on hold from 2026-09-06, hike decided 2026-10-07, currency rules 2026-10-11). The eight archived dates were rebuilt by the producer (method retrospective) so every date uses one logic; the mockup's RBI dict had the meeting on 10-05 and was dropped. gl-6 got version 2 for the US pause of the heavier Russian-oil tariffs. Markets stays as it is; retiring it is still Amit's call (section above).

Implementation notes:
- Chapters, hot spots and the Deeper shelf are stored as finished HTML from the v5.2 build; their charts refresh with each monthly version, not daily (the mockup's cadence table claimed daily chart refresh; the live Start page states what is real).
- Still by hand: the written note, the RBI stance, the weekly hot spots, the monthly chapter rebuild (the generator in `docs/research/0014-macro-mockup-src/` is not yet a module). Next: a `brief_note` LLM kind on the subscription worker, a hot-spots kind, then the monthly chapter rebuild as `run.sh`.

## Phases (each ships something visible the same session)

1. **Mockup.** India plus the US card, the clock, one day's pulse, the playbook and one worked lesson, as a standalone HTML page in `docs/research/`, on real data. Amit judges the format. **Built 2026-10-17.**
2. **Map.** India and five world cards written via `--print-prompt` → answer → `--ingest`, same validator, archived in the repo. Shown as a "Macro" page in the cockpit.
3. **Clock.** Weekly computation from the series we already hold, including the market gauges. Gaps show as "no feed", not as made-up values.
4. **Reverse dial index and pulse.** Daily movers plus storylines plus "which industries care". Linked from the industry pages, and the industry pages link back.
5. **Playbook.** Regime table, risk radar and house view; the call log starts.
6. **Feeds.** Add the missing series one at a time, smoke test first, each with a health check that can fail.
7. **Learn tab.** The twelve lessons, each linked from the pulse.
8. **Model hook** *(added)*. The industry macro score reads each industry's own explainer dials instead of its parent sector's map (today Chemicals is scored on steel, coal and cement). Shadow first, promotion review before it moves a rank.

## Rules carried over

- **No numbers in LLM prose.** Figures come only from feeds, with a date.
- **Political content is neutral.** Stated priorities, track record, likelihoods with reasons. Never a recommendation on who to vote for or which party is right.
- **Every external call goes through the host door.** A new table goes in `schema.sql` and `tables.TABLES`.
- **Silent failures are the enemy.** A feed that dies shows "no feed" on the page and fires a health check.
- **Regime tilts are research, not weights** *(added)*. Nothing on the playbook moves a pick until it has passed the factor promotion rules.

## Done when

- The cockpit has a Macro page with the map (India plus five economies), the clock and the daily pulse.
- Every pulse move names the industries that care and the map card that explains it.
- The Learn tab has at least six lessons, each linked from at least one pulse item.
- The playbook shows the regime table, the risk radar and a dated house view, and the call log has a quarter of scored entries.
- Amit can read a morning's pulse and explain in two minutes what moved, why, and which sectors it hits.
