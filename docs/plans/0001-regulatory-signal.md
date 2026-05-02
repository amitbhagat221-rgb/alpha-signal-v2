---
Status: 
Created: 2026-04-10
Last updated: 2026-04-10
Owner: Amit Bhagat
Implementation: 
Related ADRs: 
---

# Regulatory Intelligence Signal — Design Plan

> The most powerful alpha in Indian markets isn't in the numbers.
> It's in the gazettes, circulars, and press releases that nobody reads
> until the stock has already moved 30%.
>
> Created: 2026-04-10 | Owner: Amit Bhagat

---

## Why This Matters

Examples of regulatory signals that moved sectors 20-50%:

| Event | Year | Sector Impact | Lead Time |
|-------|------|--------------|-----------|
| E20 ethanol blending mandate | 2023 | Sugar/ethanol stocks +40% | Months of policy signals before mandate |
| PLI for electronics | 2021 | Dixon, Amber +100% over 18mo | Draft → notification → disbursement |
| Import duty on gold | 2023 | Jewellery stocks -15% | Budget announcement |
| SEBI mutual fund TER cut | 2018 | AMC stocks -20% | Consultation paper → final order |
| RBI digital lending guidelines | 2022 | Fintech/NBFC -30% | Draft circular → enforcement |
| Defense offset policy tightening | 2020 | HAL, BEL, BDL +60% | Make in India push signals |
| Coal mine auction opening | 2020 | Coal India flat, pvt miners up | Policy announcement |
| Telecom AGR ruling | 2019 | Vodafone-Idea -70%, Bharti -30% | Supreme Court order |
| PLI for auto/EV | 2021 | Auto ancillaries +50% | Draft → approved → stock reaction |
| Steel import duty removal | 2022 | Steel stocks -15% | Budget/policy announcement |

**Common pattern:** Regulation follows a lifecycle:
```
Discussion/Leak → Draft/Consultation → Notification → Implementation → Enforcement
```
Each stage is investable. The earlier you catch it, the bigger the alpha.

---

## Data Sources for Regulatory Signals

### Tier 1: Already Available (enhance what we have)

| Source | What we have | What's missing |
|--------|-------------|---------------|
| **RSS news articles** | 2,972 articles in DB, 8 RSS feeds | No AI classification of regulatory vs non-regulatory |
| **Claude API** | Used for dossiers | Not used for news classification |

### Tier 2: New Sources (structured government data)

| Source | URL | Content | Frequency |
|--------|-----|---------|-----------|
| **PIB Press Releases** | pib.gov.in/allRel.aspx | Ministry-wise releases, policy announcements | Daily (5-20/day) |
| **RBI Circulars** | rbi.org.in/Scripts/NotificationUser.aspx | Monetary policy, banking regulations | Weekly |
| **SEBI Circulars** | sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=2 | Market regulations, MF rules, listing rules | Weekly |
| **Gazette of India** | egazette.gov.in | Official notifications, ordinances | Daily |
| **MCA (Company Affairs)** | mca.gov.in | Corporate law changes | Monthly |
| **DGFT** | dgft.gov.in | Export/import policy, trade notifications | Weekly |
| **CBIC (Customs)** | cbic.gov.in | Customs duty changes, GST council decisions | Monthly |
| **Ministry of Finance** | finmin.nic.in | Budget, fiscal policy, tax changes | Event-driven |

### Tier 3: Aggregators (curated regulatory news)

| Source | What it provides |
|--------|-----------------|
| **Moneycontrol Policy section** | Pre-digested regulatory news |
| **LiveMint Policy** | Policy analysis articles |
| **Economic Times Regulation** | Regulatory impact analysis |

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│                 DATA INGESTION                    │
│                                                   │
│  RSS News (existing) ──┐                          │
│  PIB Press Releases ───┤                          │
│  RBI Circulars ────────┼──→ regulatory_events     │
│  SEBI Circulars ───────┤     (new table)          │
│  Gazette of India ─────┘                          │
└──────────────────┬───────────────────────────────┘
                   │
┌──────────────────▼───────────────────────────────┐
│              AI CLASSIFICATION                    │
│                                                   │
│  For each event, Claude classifies:               │
│   • Is this regulatory? (yes/no)                  │
│   • Regulatory stage: draft/notification/         │
│     implementation/enforcement                    │
│   • Affected sectors (list)                       │
│   • Direction per sector (+1/-1)                  │
│   • Magnitude: minor/moderate/major               │
│   • Time horizon: immediate/3mo/6mo/12mo          │
│   • Confidence: high/medium/low                   │
│                                                   │
│  Output → regulatory_signals (new table)          │
└──────────────────┬───────────────────────────────┘
                   │
┌──────────────────▼───────────────────────────────┐
│            SECTOR SIGNAL AGGREGATION              │
│                                                   │
│  Per sector, rolling 30/90/180 day windows:       │
│   • Count of positive vs negative events          │
│   • Weighted by magnitude × confidence            │
│   • Decay: recent events weighted more            │
│                                                   │
│  Output → sector regulatory_score (0-100)         │
│           merged into macro_sector_signals        │
└──────────────────────────────────────────────────┘
```

---

## Database Schema

### `regulatory_events` — raw ingested events

```sql
CREATE TABLE IF NOT EXISTS regulatory_events (
    event_id        TEXT PRIMARY KEY,    -- hash of source+date+title
    title           TEXT NOT NULL,
    summary         TEXT,
    full_text       TEXT,               -- for AI context
    source          TEXT NOT NULL,       -- 'pib', 'rbi', 'sebi', 'gazette', 'news'
    source_url      TEXT,
    published_at    TEXT NOT NULL,
    ministry        TEXT,               -- 'Finance', 'Commerce', 'Heavy Industries'
    fetched_at      TEXT DEFAULT (datetime('now'))
);
```

### `regulatory_signals` — AI-classified impact

```sql
CREATE TABLE IF NOT EXISTS regulatory_signals (
    event_id        TEXT NOT NULL REFERENCES regulatory_events(event_id),
    sector          TEXT NOT NULL,
    is_regulatory   INTEGER NOT NULL,    -- 1 = yes, 0 = not regulatory
    stage           TEXT,               -- 'discussion', 'draft', 'notification', 'implementation'
    direction       INTEGER,            -- +1 = positive for sector, -1 = negative
    magnitude       TEXT,               -- 'minor', 'moderate', 'major'
    time_horizon    TEXT,               -- 'immediate', '3mo', '6mo', '12mo'
    confidence      TEXT,               -- 'high', 'medium', 'low'
    ai_reasoning    TEXT,               -- Claude's reasoning
    classified_at   TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (event_id, sector)
);

CREATE INDEX IF NOT EXISTS idx_reg_signals_sector ON regulatory_signals(sector);
CREATE INDEX IF NOT EXISTS idx_reg_signals_date 
    ON regulatory_signals(classified_at);
```

---

## AI Classification Prompt (per event)

```
You are an expert Indian regulatory analyst. Classify this government/regulatory
event for its impact on Indian equity sectors.

EVENT:
Title: {title}
Source: {source} ({ministry})
Date: {published_at}
Text: {summary or full_text[:2000]}

Respond in JSON:
{
  "is_regulatory": true/false,
  "sectors_affected": [
    {
      "sector": "Sugar",
      "direction": +1,
      "magnitude": "major",
      "time_horizon": "6mo",
      "confidence": "high",
      "reasoning": "E20 mandate increases ethanol demand, benefiting sugar mills with distillery capacity"
    }
  ],
  "stage": "notification",
  "policy_area": "energy/environment/trade/finance/agriculture/..."
}

Rules:
- Only classify as regulatory if it involves government policy, regulation, court orders,
  or regulatory body decisions (RBI/SEBI/TRAI/etc.)
- Map to actual BSE/NSE sectors: Financial Services, IT, Materials, Energy, etc.
- "major" = >10% sector impact potential. "moderate" = 5-10%. "minor" = <5%.
- Be specific about WHY — generic "positive for economy" is useless.
```

---

## Sector Signal Formula

For sector S on date D, looking back W days:

```
reg_score(S, D, W) = Σ(direction_i × mag_weight_i × conf_weight_i × decay_i)
                     / max(1, count_events)
```
