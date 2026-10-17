# Brief: rewrite macro framework chapters, Finshots style, as detailed as possible

## Why
The owner (an experienced investor: CFA, FRM, risk at a hedge fund) read the current chapters and said: "the prose is too
thin without good Finshots style explains; the frameworks should be as detailed as possible and strictly Finshots style;
the history is boring, should be interesting, relatable; people and incidents make it relatable; currently it is too
boring, dry and not helping understand anything at all." Earlier he also rejected a version that was "too basic, I am
not this much of a noob" (it opened with a grandmother at a tea stall). So: Finshots storytelling voice and depth, for a
smart professional who wants to truly understand the mechanism. Not childish, not dry.

## The exemplar: read it first, match it
`in-4.prose.json` in this folder (the RBI chapter) is the approved voice and depth. Read the whole file before writing.

## Voice (Finshots, for a professional)
- Conversational, second person, short paragraphs (2 to 5 sentences). Rhetorical questions. "Here's the thing." "So what
  changed?" A bit of wit. Analogies that clarify (cricket, a household budget, a shop), never cute for its own sake.
- Explain every mechanism step by step: what happens, then what that causes, then why it matters for prices and
  stocks. Define each piece of jargon in plain words the first time it appears.
- Concrete over abstract: name the company types, the sectors, the people, the year, what ordinary Indians felt.
- Each section heading is a plain-English claim or question, not a label ("Why a strong dollar drains Indian
  markets", not "Dollar channel").
- Neutral on politics. No buy or sell calls on single stocks; sector groups are fine in "so what".

## History: stories, not a table
5 to 7 story cards per chapter. Each: a year or period, a vivid title, a 2 to 3 paragraph story with NAMED people
(governors, finance ministers, Fed chairs, oil ministers, CEOs, traders) and incidents (the press conference, the
leaked memo, the queue at the bank, the tanker attack), what happened in markets and to ordinary people, and a
one-sentence lesson for an investor today. Make it a story someone would retell at dinner.

## Structure: write DIR/<id>.prose.json
{
 "title": "punchy title, keep the chapter's subject",
 "minutes": reading minutes (integer, about words / 200),
 "hook": "<p>..</p><p>..</p>",          2 to 4 paragraphs: a scene or story, then the question this chapter answers
 "short": ["...", ...],                 4 or 5 one-sentence takeaways ("The short version")
 "sections": [{"heading": "...", "html": "<p>..</p>[[fig:1]]<p>..</p>"}, ...],   5 to 8 sections, 250 to 500 words each
 "history_title": "short phrase",
 "history": [{"when": "2013", "title": "...", "story": "<p>..</p><p>..</p>", "lesson": "one sentence"}, ...],
 "today": "<p>..</p><p>..</p>",         where it stands now: use [[val:...]] tokens for readings; what to watch next
 "sowhat": "<p>..</p><ul><li><b>Prefer</b> ...</li>...</ul><p>what would flip it</p>"
}
Total 2,200 to 3,200 words per chapter (the validator requires at least 1,400; the exemplar has 2,650).

## Hard rules (the validator enforces most of them)
1. NO DIGITS anywhere in the prose except years (2013, 2025–26) and calendar tokens (Q1, FY27). No percentages, no
   amounts, no dates with day numbers ("in May 2022" is fine, "4 May 2022" is not). Words for quantities only for
   well-established facts and sparingly ("a third", "doubled", "tens of billions of dollars"). Never invent a statistic.
2. Current readings ONLY through tokens: run `python -m tools.macro_chapters values` to see them ([[val:brent]],
   [[val:usdinr]], [[val:cpi]], [[val:fii20]], ...). They render as live numbers.
3. Figures: the chapter's JSON (`<id>.json`) lists its figures (n, kind, caption, label). Place every one exactly once
   as [[fig:N]] between paragraphs where the text discusses it, and add a sentence or two telling the reader how to
   read it and what to notice. Do not describe numbers in the figure with digits.
4. Allowed tags: p b strong em i ul ol li blockquote br. No links (a linker adds them), no headings inside html.
   One or two <blockquote> pull lines per chapter, short and quotable.
5. Accuracy. Keep the substance of the old chapter (`<id>.json` → "old" and "sources"): extend and explain it, never
   contradict it. Events of 2025 and 2026 (the Iran war and Hormuz, the RBI's October 2026 hike, US tariffs, Korea's
   chip exports, etc.) may come ONLY from the old chapter text, its sources, or a web search you actually ran. Verify
   historical facts and quotes with WebSearch whenever you are not certain; if you cannot verify something, leave it
   out. Paraphrase quotes unless you verified the wording.
6. Do not touch anything outside this folder. Do not run `--save`. Do not edit other writers' chapters.

## Check your work
    source ~/alpha-signal/venv/bin/activate && cd /home/ubuntu/alpha-signal-v2
    python -m tools.macro_chapters assemble <this folder>
Each chapter prints ✓ with its word count or ✗ with the problems. Fix until all of yours are ✓.
Then reread each chapter once as the owner would: is every mechanism actually explained? Is the history fun to read?

## Report back
For each chapter: word count, the history stories you told, any fact you dropped because you could not verify it, and
any 2025–26 claim and where it came from.
