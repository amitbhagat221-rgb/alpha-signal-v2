-- mf.db — mutual funds, a separate domain in a separate file (ADR 0054).
-- One owner (the MF code); stock code reads it only through views.py (ATTACH read-only).
CREATE TABLE IF NOT EXISTS funds (
    fund_id     INTEGER PRIMARY KEY,
    scheme_code TEXT NOT NULL UNIQUE,
    name        TEXT,
    amc         TEXT,
    category    TEXT,
    plan_type   TEXT,
    option_type TEXT,
    isin        TEXT,
    attrs       TEXT,                    -- every other scheme-master / mf_schemes column
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fund_nav (
    fund_id    INTEGER NOT NULL,
    date       TEXT NOT NULL,
    nav        REAL,
    fetched_at TEXT,
    PRIMARY KEY (fund_id, date)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS fund_holdings (
    fund_id      INTEGER NOT NULL,
    as_of        TEXT NOT NULL,
    available_at TEXT NOT NULL,
    holding_type TEXT NOT NULL,          -- security|sector
    holding_key  TEXT NOT NULL,          -- rank for securities, sector name for sectors
    sid          TEXT,
    isin         TEXT,
    name         TEXT,
    sector       TEXT,
    instrument   TEXT,
    weight       REAL,
    value        REAL,
    PRIMARY KEY (fund_id, as_of, holding_type, holding_key)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS fund_metrics (
    subject_kind TEXT NOT NULL,          -- fund|category
    subject      TEXT NOT NULL,          -- scheme_code | category_norm
    metric       TEXT NOT NULL,
    win          TEXT NOT NULL,          -- window ('' when the metric carries it in its name; the year for calendar returns)
    as_of        TEXT NOT NULL,
    value        REAL,
    text_value   TEXT,
    PRIMARY KEY (subject_kind, subject, metric, win, as_of)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS row_issues (
    issue_id    INTEGER PRIMARY KEY,
    dataset     TEXT NOT NULL,
    row_key     TEXT NOT NULL,
    rule        TEXT NOT NULL,
    severity    TEXT NOT NULL,
    payload     TEXT,
    detected_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution  TEXT,
    UNIQUE (dataset, row_key, rule, detected_at)
);
