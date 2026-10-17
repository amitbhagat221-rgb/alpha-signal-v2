# Brief: the long-form layer of an industry explainer, Finshots style, very detailed and fun

## Why
The cockpit's Sectors › Industry Detail page explains each Indian industry in twelve cards (doors, kitchen, who buys,
rupee to profit, the cycle clock, the wiring diagram, bottlenecks, rulebook, five forces, cheat sheet,
cross-intelligence and the call, tell a friend). The owner, an experienced investor (CFA, FRM, hedge-fund risk), said:
"the content and structure is already gold, don't change that; however the prose that explains each is too thin and
gets boring; the diagrams and illustrations should be explained in a very detailed way; Finshots style but very very
detailed and fun to read." He has also rejected anything childish ("I am not this much of a noob").

So you DO NOT change the explainer. You ADD, for cards c1 to c11, two blocks:
- "story": the narrative for that card, for THIS industry: several paragraphs that make the idea vivid and explain it
  step by step, with real Indian companies, episodes, people and numbers-free examples.
- "read": "How to read this": a detailed walk-through of that card's diagram or table AS IT IS DRAWN FOR THIS INDUSTRY
  (use the explainer's own data: the doors and their profit bars, the kitchen stations and bands, the ₹100 walk shapes,
  the clock position, phases and hands, the dial rows and weights, the radar shapes, the cheat-sheet rows, the
  lead-time dots, the rule's ticks). Tell the reader what each element means, where to look first, what to notice for
  this industry, and how to use it.

## The exemplar: read it first, match it
`chemicals-specialty.deep.json` (written for Chemicals & Specialty, from `chemicals-specialty.json`) is the approved
voice, depth and format. Read it fully, and read `chemicals-specialty.json` to see how the read blocks use the data.

## What each card's diagram is (the same layout for every industry)
- c1 doors: two to four tiles, each with name, how it sells, example tickers (clickable), a "profit the company keeps"
  bar (low / medium / high), and a one-line bet. Below: an analogy and a so-what line.
- c2 kitchen: five station boxes left to right (upstream → final customer) with what happens and who stands there;
  under them a row of five bands saying who holds each station (Indian listed names coloured), and, if a foreign rival
  is named, a second band row showing where the rival stands. A note on geography and a so-what follow.
- c3 who buys: six to eight tiles: customer, what it buys, what moves it.
- c4 rupee to profit: two bar charts walking ₹100 of sales down for door A and door B: input cost, opex, depreciation
  and interest, what is left (illustrative mid-cycle shapes; hover for amounts). Then a list of P&L lines marked
  yes / sometimes / no with a reason, an analogy and a so-what.
- c5 the clock: a circular clock with four arcs (boom, peak, bust, bottom, clockwise from the top) labelled with the last
  cycle's years, an arrow pointing at today's position; beside it a coloured timeline from 2019 to now; below it four
  "hands" to watch, each with a reading and an up/down/flat arrow.
- c6 wiring diagram: a table, one row per macro dial: dial, channel, what a rise does (green up arrow helps, red down
  hurts, diamond mixed), weight as one to three dots, and today's reading where the dial maps to a series we track.
- c7 bottlenecks: a table: bottleneck, why it bites, severity (structural, recurring, cyclical, two-sided, slow).
- c8 rulebook: a table: regulator or rule, what it does, why you care, status (always, live, new, coming).
- c9 five forces: a radar with five spokes for door A and door B (bigger shape = more pressure = worse business), and a
  table of scores zero to three with a reason each.
- c10 cheat sheet (Numbers tab): a table of eight numbers: what it tells you, what good looks like, and today's
  industry median from listed companies' filings.
- c11 cross-intelligence (Picks & signals tab): a chart placing outside signals by lead time (same quarter, one, two,
  three or more quarters ahead; further right = earlier warning), then the three-sign rule with ticks and crosses,
  then the call box with points and "what would change the call".

## Voice (Finshots, for a professional)
Conversational, second person, short paragraphs, a rhetorical question now and then, analogies that clarify, a bit of
wit, real Indian companies and episodes (name the company, the year, the policy, the person where it helps).
Explain every mechanism step by step: what happens, what it causes, why it matters for the stock. Define jargon the
first time. One <blockquote> pull line in a few of the stories, short and quotable. Never childish, never a list of
facts with no story.

## Format: write DIR/<slug>.deep.json
{"c1": {"story": "<p>..</p>...", "read": "<p>..</p><ul><li><b>..</b> ..</li></ul>..."}, ... "c11": {...}}
Length per card: story 250 to 450 words, read 150 to 300 words (the validator requires at least 180 and 110).
Total about 4,500 to 6,500 words per industry.

## Hard rules (validated)
1. NO DIGITS anywhere except years (2019) and calendar tokens (FY25, Q1). Say "roughly seven of every ten rupees",
   "a third", "doubled", "high twenties". Never invent a statistic; prefer shapes and comparisons you can see in the
   explainer data. The ₹ sign is fine; digits are not.
2. Allowed tags only: p b strong em i ul ol li blockquote br. No links, no headings.
3. Stay consistent with the explainer. Do not contradict its doors, stations, cycle position, dials, scores or call;
   explain and enrich them. Facts beyond the explainer (episodes, policies, people, 2025–26 events) must be ones you
   are sure of or verified with WebSearch; if unsure, leave them out. No buy or sell calls on single stocks.
4. Write only your own industries' .deep.json files in this folder. Never run --ingest-deep.

## Check your work
    source ~/alpha-signal/venv/bin/activate && cd /home/ubuntu/alpha-signal-v2
    python -m tools.sector_explainer --check-deep <folder>/<slug>.deep.json
Fix until it prints ✓. Then reread one card as the owner would: is the diagram now obvious? Is it fun?

## Report back
Per industry: total words, any fact you dropped for lack of verification, any 2025–26 claim and its source.
