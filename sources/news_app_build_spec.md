# Personal News App — Solo Builder Spec

> A pragmatic build plan for one person. Optimized for shipping in 4–6 weekends, not for impressing investors.

---

## The honest scope cut

Before anything else: a solo builder cannot build "Bloomberg + Inshorts + TikTok." You will build **a daily personalized news brief with a shorts-style scrolling reader, powered by an LLM**. That's it. Everything else is Phase 2+.

What you are **not** building in MVP:
- Native mobile app (use a PWA — it works on iOS/Android, no app store hell)
- Audio briefs
- Bias toggles
- Generated infographics (use source images + simple charts only)
- Vector DB for memory (overkill for one user)
- Real-time push (the 10 AM brief IS the engagement loop)

What you ARE building:
1. A topic-configurable news ingestion pipeline
2. An LLM summarization + structuring layer with quality controls
3. A ranking engine personalized to you
4. A shorts-style scrollable feed with tap-to-expand
5. A daily 10 AM brief

---

## Architecture (boring, on purpose)

```
[Cron job, hourly]
   ↓
[Ingest from RSS/APIs] → [Dedupe] → [Importance score] → [LLM process] → [Postgres]
                                                                              ↓
                                                              [Next.js API routes]
                                                                              ↓
                                                                     [PWA frontend]
                                                                              ↓
                                                              [User taps/dwell time logged]
                                                                              ↓
                                                              [Feeds back into ranking]
```

Stack:
- **Frontend**: Next.js (PWA mode) + Tailwind. One codebase, works on phone.
- **Backend**: Next.js API routes. No separate backend.
- **DB**: Postgres (Supabase free tier).
- **Cron**: GitHub Actions or Vercel cron — free.
- **LLM**: Claude Haiku for bulk processing (cheap), Claude Sonnet for the daily brief synthesis (better). Don't mix providers in v1.
- **Hosting**: Vercel free tier.
- **Auth**: Skip it. It's just you. Add a password gate if you're paranoid.

Total monthly cost at your usage: ~$5–15 in LLM calls. Everything else free.

---

## Personalization + ranking — the deep dive

This is the part you said you care about, so this is where I'll spend the words.

### The core insight

For a single user, you don't need ML. You need a **scoring function with weights you can tune by hand**, plus an implicit feedback loop. ML is for when you have 10,000 users and can't hand-tune. You have one user (you), and you know what you like better than any model.

### The scoring function

Every news item gets a score. Top scores go to the top of the feed.

```
score = (topic_weight × topic_match)
      + (source_weight × source_trust)
      + (recency_weight × recency_decay)
      + (importance_weight × importance_signal)
      + (personal_weight × behavior_signal)
      - (penalty × already_seen_similar)
```

Each component, concretely:

**topic_match (0 to 1)**
You define topics in a config file (yes, a JSON file — you're the only user). Each topic has keywords and a weight. A piece of news scores higher if its tags/entities overlap with your declared interests.

```json
{
  "topics": {
    "ai_industry": { "weight": 1.0, "keywords": ["openai", "anthropic", "llm", "gpu", "nvidia"] },
    "indian_markets": { "weight": 0.9, "keywords": ["nifty", "sensex", "rbi", "sebi"] },
    "geopolitics": { "weight": 0.7, "keywords": ["china", "us", "trade", "tariff"] },
    "celebrity_gossip": { "weight": 0.0, "keywords": [...] }
  }
}
```

You can tune weights weekly based on what you actually read.

**source_trust (0 to 1)**
A static tier list. This is the missing piece in most aggregators.

- Tier 1 (1.0): Reuters, AP, Bloomberg, FT, WSJ, The Hindu (BusinessLine), Mint
- Tier 2 (0.7): Mainstream outlets (NYT, Guardian, Indian Express, Economic Times)
- Tier 3 (0.4): Tech blogs (TechCrunch, The Verge, Stratechery)
- Tier 4 (0.2): Aggregators, secondary commentary
- Tier 5 (0.0 or excluded): Anything you don't trust

Hand-curate this once. Update quarterly.

**recency_decay**
Exponential decay with a half-life. For most topics, 12–24 hours. For markets, 2–4 hours. For long-running stories (war, elections), 48 hours. Configure per topic.

```
recency_decay = 0.5 ^ (hours_old / half_life)
```

**importance_signal**
The hardest one. Cheap proxies:
- How many sources are covering the same story (cluster size after dedupe)
- Whether Tier 1 sources picked it up
- Whether numbers/named entities you care about appear (e.g., "Nvidia", "$10B")

Don't ask the LLM to score importance. It's slow and inconsistent. Use the cluster-size + source-tier proxy.

**behavior_signal (this is the personalization payoff)**
Track three things per article you interact with:
- Did you tap to expand? (binary)
- How long did you dwell on the deep view? (seconds)
- Did you swipe past quickly in the feed? (negative signal)

Then, at the end of each week, recompute topic weights:

```
new_topic_weight = old_weight × (1 + 0.1 × normalized_engagement_for_that_topic)
```

Small adjustments. You don't want runaway feedback loops where one viral story permanently inflates a topic.

**already_seen_similar (the penalty)**
Use simple cosine similarity on article embeddings (one-time embedding via a cheap model — `text-embedding-3-small` or similar). If you've already read something with cosine > 0.85 to a new article, penalize it heavily. This kills the "same story repeated 12 times" problem that ruins most aggregators.

### Cold start (Day 1)

You don't have behavior data on day 1. Solution: an onboarding screen where you rank ~15 sample headlines from "definitely interested" to "couldn't care less." This seeds your topic weights. Takes 2 minutes. You only do it once.

### The dedup step (do this BEFORE scoring)

Run incoming articles through a clustering step:
1. Embed every article's title + first paragraph
2. Cluster articles published within a 24-hour window using cosine similarity threshold ~0.75
3. From each cluster, pick the highest source-tier article as the "canonical" version
4. Use the cluster size as the importance_signal feed-in

Without this step, your feed will be 60% duplicates.

### Ranking loop, in plain English

Hourly cron:
1. Pull new articles from RSS + APIs
2. Embed them
3. Cluster against last 24h of articles → pick canonicals
4. Score each canonical
5. Store in DB with score + cluster metadata

When you open the app:
1. Pull top N scored articles from the last 24h
2. Apply the "already seen" penalty against your read history
3. Re-sort
4. Render

That's it. No ML model training. No vector DB infra. Just Postgres + a few Python/JS functions.

---

## The LLM layer — quality is everything

This is where most builders fail. They ship slop summaries and wonder why retention dies.

### The prompt structure (use this as a template)

For each article, generate ONE structured object via a single LLM call:

```
You are a news explainer. Given the article below, output JSON with these exact fields:

- headline: max 10 words, factual, no clickbait
- one_liner: max 20 words, what happened
- why_it_matters: max 40 words, the actual implication
- key_numbers: array of {label, value} pairs, max 3 items, only if numbers are central to the story
- analogy: max 25 words, ONLY if a genuinely useful analogy exists. Return null otherwise.
- what_to_watch: max 30 words, the next thing to look for
- confidence: "high" | "medium" | "low" — your confidence in the source's accuracy

Rules:
- Never speculate beyond what's in the article
- If a fact isn't in the source, don't include it
- If the article is opinion/editorial, set confidence to "low" and say so in why_it_matters

Article: <text>
```

Critical: **make analogy optional and return null when forced**. The biggest mistake is generating bad analogies because the prompt demands one. Bad analogies are worse than no analogies.

### Hallucination control

Three cheap guardrails that catch ~90% of issues:

1. **Number check**: regex-extract all numbers from the LLM output. Verify each appears verbatim in the source article. If not, drop the article from the brief.
2. **Entity check**: extract named entities (people, companies). Verify each appears in the source. Same drop rule.
3. **Confidence flag**: surface the LLM's self-reported confidence in the UI. Low-confidence items get a small icon. Don't hide them — let yourself decide.

Skip RAG, skip fine-tuning, skip eval frameworks. For a personal product, you ARE the eval framework. Read 20 outputs a day for the first week. Adjust the prompt based on what annoyed you.

### Cost math

- ~200 articles/day after dedup
- ~800 input tokens + 300 output tokens per article via Haiku
- ~$0.02 per day for processing
- Daily brief synthesis via Sonnet: ~$0.05/day
- Monthly: ~$2–3 in LLM costs

You can run this on lunch money.

---

## The 10 AM brief — the actual product

Everything else is in service of this. The feed is nice-to-have. The brief is why you'll open the app.

### Generation logic

At 9:55 AM each day, a cron job:

1. Pulls the top 30 articles from the last 24h (post-dedup, post-scoring)
2. Groups them by your top 5 topics
3. Sends them to Sonnet with this prompt:

```
You are writing the daily intelligence brief for one person. Their top topics 
this week (by engagement) are: [topic list].

From the articles below, produce a brief with this structure:
1. THE BIG ONE — the single most important story (60 words)
2. FIVE FAST — five other things they need to know (20 words each)
3. ONE TO WATCH — something forming, not yet a story (40 words)
4. ZOOM OUT — one paragraph connecting today to a larger pattern (50 words)

Constraints:
- Only use facts from the provided articles
- If two articles contradict, surface the contradiction
- Skip anything trivial — if there are only 4 things worth knowing, give 4
- Write in a calm, smart-friend voice. No "shocking", no "you won't believe"
```

4. Stores the brief in DB. Send yourself a push notification (or just a calendar reminder for v1) at 10 AM.

### Why "smart-friend voice" matters

The single most important UX choice in this app is tone. Most AI summarizers default to a kind of mid-corporate-Reuters voice. Your differentiator (since you're building for yourself) is voice. Iterate on the system prompt until it sounds like a brilliant friend explaining the day to you over coffee. This takes ~20 prompt iterations. Worth every one.

---

## UX — the minimum that works

Three screens. That's it.

**1. Feed (home)**
- Vertical scroll, one card per article
- Card shows: small image (left), headline, one-liner, source tier dot
- Tap → opens deep view
- Pull-to-refresh re-runs scoring against latest data

**2. Deep view**
- Full screen takeover (not inline expansion — inline kills focus)
- Renders the structured fields: what happened, why it matters, key numbers, analogy (if present), what to watch
- "Read source" link at bottom (always show — trust builder)
- Swipe left/right for prev/next article
- Time-on-screen logged for the ranking signal

**3. Daily brief**
- Static page rendered from the 10 AM generation
- Hero card for THE BIG ONE
- List for FIVE FAST
- "Yesterday's brief" archive at the bottom

No settings screen in v1. Edit the JSON config file directly. You're the only user.

---

## Build sequence (4–6 weekends)

**Weekend 1: ingestion + storage**
- Set up Next.js + Supabase
- Write RSS pullers for ~10 sources you trust
- Dedup via embedding clustering
- Verify articles land in DB cleanly

**Weekend 2: LLM processing**
- Build the per-article prompt
- Wire up Claude API calls in the cron job
- Add the hallucination guardrails (number + entity check)
- Eyeball 50 outputs, tune prompt

**Weekend 3: ranking**
- Implement the scoring function
- Build the topic config file
- Add cold-start onboarding (15-headline ranker)
- Implement the "already seen" penalty

**Weekend 4: feed UI**
- Shorts-style scroll
- Deep view screen
- Behavior tracking (taps, dwell time)
- Deploy as PWA, install on your phone

**Weekend 5: daily brief**
- Brief generation prompt
- 9:55 AM cron job
- Brief render screen
- Push notification or email at 10 AM

**Weekend 6: polish + behavior loop**
- Wire behavior signals back into weekly weight updates
- Add source trust badges in UI
- Fix the 30 things that annoy you after a week of use

---

## Things to deliberately skip in v1 (and why)

- **Audio briefs** — TTS is good now but adds infra complexity. Add when you have v1 working and you actually miss it.
- **Bias toggle** — Not useful for a personal app. Useful for a public product. Different problem.
- **Generated infographics** — AI-generated infographics are uniformly bad in 2026. Use source images + a simple bar/line chart library (Recharts) for numerical data only.
- **Vector DB** — Postgres with pgvector handles your scale (one user, ~6,000 articles/month) trivially. Don't add infra.
- **Reinforcement learning ranker** — You don't have the data volume. Hand-tuned weights win at this scale.
- **Auth/multi-user** — You're the only user. If you ever want to share, add later.

---

## The single highest-leverage thing

Spend 30% of your build time on the LLM prompts. Not the architecture. Not the UI. The prompts.

The product's quality is exactly equal to the quality of the structured output. A clean feed full of well-explained articles in your voice will feel magical. A clean feed of generic AI slop will feel like every other aggregator.

Iterate the prompts daily for the first month after launch. Read every brief. Note what feels off. Adjust. This is the work.

---

## Open questions for you to decide before you start

1. Which ~10 sources do you actually trust enough to seed Tier 1 + Tier 2? (Make this list before coding.)
2. What are your top 5 topics, in plain English? (Write them out before turning them into keywords.)
3. iOS or Android primary? (Affects PWA install flow specifics.)
4. Are you okay reading the brief on a phone screen, or do you want it emailed too? (Trivial to add email — worth deciding upfront.)
