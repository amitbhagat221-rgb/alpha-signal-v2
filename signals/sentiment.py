"""
Alpha Signal v2 — News Sentiment Signal (VADER)

Scores news articles using VADER compound sentiment, then aggregates
per stock over 1-day, 7-day, and 30-day windows.

sentiment_momentum = sentiment_7d - sentiment_30d (trend detection)

Reads: news_articles, news_article_stocks
Writes: sentiment_scores

Usage:
    python -m signals.sentiment            # compute and save
    python -m signals.sentiment --dry-run  # compute but don't save
"""

import argparse
from datetime import date, timedelta

import pandas as pd
from nltk.sentiment.vader import SentimentIntensityAnalyzer

from db import read_sql, upsert_df

_sia = SentimentIntensityAnalyzer()


def _score_text(text):
    """VADER compound score for a text string."""
    if not text or pd.isna(text):
        return 0.0
    return _sia.polarity_scores(str(text))["compound"]


def _load_data():
    """Load articles and stock links."""
    articles = read_sql(
        "SELECT article_id, title, summary, published_at FROM news_articles"
    )
    links = read_sql(
        "SELECT article_id, sid FROM news_article_stocks"
    )
    stocks = read_sql("SELECT sid FROM stocks")
    return articles, links, stocks


def _compute_scores(articles, links, stocks):
    """Compute sentiment scores per stock."""
    today = date.today()

    # Score each article
    articles = articles.copy()
    articles["sentiment"] = articles.apply(
        lambda r: _score_text(f"{r['title']} {r.get('summary', '')}"), axis=1
    )
    articles["pub_date"] = pd.to_datetime(articles["published_at"], format="ISO8601").dt.date

    # Merge with stock links
    scored = links.merge(articles[["article_id", "sentiment", "pub_date"]], on="article_id")

    rows = []
    for sid in stocks["sid"]:
        row = {"sid": sid}
        stock_articles = scored[scored["sid"] == sid]

        if stock_articles.empty:
            rows.append(row)
            continue

        # Today
        today_mask = stock_articles["pub_date"] == today
        today_arts = stock_articles[today_mask]
        if len(today_arts) > 0:
            row["sentiment_today"] = round(today_arts["sentiment"].mean(), 4)
            row["articles_today"] = len(today_arts)

        # 7-day window
        d7 = today - timedelta(days=7)
        w7 = stock_articles[stock_articles["pub_date"] >= d7]
        if len(w7) > 0:
            row["sentiment_7d"] = round(w7["sentiment"].mean(), 4)
            row["articles_7d"] = len(w7)

        # 30-day window
        d30 = today - timedelta(days=30)
        w30 = stock_articles[stock_articles["pub_date"] >= d30]
        if len(w30) > 0:
            row["sentiment_30d"] = round(w30["sentiment"].mean(), 4)
            row["articles_30d"] = len(w30)

        # Momentum (trend)
        if row.get("sentiment_7d") is not None and row.get("sentiment_30d") is not None:
            row["sentiment_momentum"] = round(row["sentiment_7d"] - row["sentiment_30d"], 4)

        # Latest headline
        latest = stock_articles.sort_values("pub_date", ascending=False).iloc[0]
        row["latest_headline"] = str(latest.get("sentiment", ""))[:200]

        rows.append(row)

    df = pd.DataFrame(rows)

    out_cols = ["sid", "sentiment_today", "articles_today", "sentiment_7d",
                "articles_7d", "sentiment_30d", "articles_30d",
                "sentiment_momentum", "latest_headline"]
    for col in out_cols:
        if col not in df.columns:
            df[col] = None

    return df[out_cols]


def compute(dry_run=False):
    """Main entry point. Returns row count."""
    articles, links, stocks = _load_data()
    df = _compute_scores(articles, links, stocks)

    snapshot = date.today().isoformat()
    df["snapshot_date"] = snapshot

    has_7d = df["sentiment_7d"].notna().sum()
    has_30d = df["sentiment_30d"].notna().sum()

    print(f"Sentiment: {len(df)} stocks")
    print(f"  7-day coverage: {has_7d} stocks")
    print(f"  30-day coverage: {has_30d} stocks")
    if has_7d > 0:
        print(f"  7d mean={df['sentiment_7d'].dropna().mean():.3f}")

    if dry_run:
        print("\nDry run — not saving.")
        return len(df)

    rows = upsert_df(df, "sentiment_scores")
    print(f"Saved {rows} rows to sentiment_scores (snapshot={snapshot})")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
