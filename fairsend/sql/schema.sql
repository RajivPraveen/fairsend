-- FairSend storage (SQLite). Safe to run repeatedly.

PRAGMA foreign_keys = ON;

-- One row per pipeline execution, so every price row can be traced to the file it came from.
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id          TEXT PRIMARY KEY,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    source_file     TEXT,
    source_sha256   TEXT,
    status          TEXT NOT NULL DEFAULT 'running',   -- running | success | failed | skipped
    rows_in         INTEGER,
    rows_valid      INTEGER,
    rows_flagged    INTEGER,
    notes           TEXT
);

-- Cleaned World Bank Remittance Prices Worldwide observations (full history, 2011 onward).
-- Each row is one product of one provider on one corridor in one survey period.
-- Amounts are in the sending currency; *_fx_rate and interbank_fx are receive units per send unit.
CREATE TABLE IF NOT EXISTS rpw_prices (
    obs_id              TEXT PRIMARY KEY,      -- stable key: "<sheet>:<world bank id>"
    rpw_id              INTEGER,
    period              TEXT NOT NULL,         -- e.g. 2025_3Q
    period_date         TEXT NOT NULL,         -- first day of the quarter, ISO date
    collected_date      TEXT,                  -- day the price was collected
    source_code         TEXT NOT NULL,
    source_name         TEXT,
    source_region       TEXT,
    source_income       TEXT,
    dest_code           TEXT NOT NULL,
    dest_name           TEXT,
    dest_region         TEXT,
    dest_income         TEXT,
    corridor            TEXT NOT NULL,
    firm_raw            TEXT,
    provider            TEXT NOT NULL,         -- standardized provider name
    network             TEXT,                  -- e.g. 'Western Union' for "La Poste via Western Union"
    firm_type           TEXT,                  -- Bank | Money Transfer Operator | Post office | Mobile Operator | Other
    payment_instrument  TEXT,
    access_point        TEXT,
    payout_method       TEXT,                  -- standardized: Cash pickup | Bank account | Mobile wallet | Card | Home delivery
    speed_label         TEXT,
    speed_days_max      REAL,                  -- upper bound on delivery time in days
    send_currency       TEXT NOT NULL,
    receive_currency    TEXT,                  -- currency the product pays out in (inferred; see pipeline/currency.py)
    country_currency    TEXT,                  -- receiving country's own currency on the collection date
    payout_currency_basis TEXT,                -- how receive_currency was determined
    ecb_mid_rate        REAL,                  -- ECB reference rate on the collection date, where published
    amt200_lcu          REAL, fee200_lcu REAL, fx_rate200 REAL, margin200_pct REAL, total200_pct REAL,
    amt500_lcu          REAL, fee500_lcu REAL, fx_rate500 REAL, margin500_pct REAL, total500_pct REAL,
    interbank_fx        REAL,
    transparent         INTEGER,               -- 1 = provider disclosed the rate it applied
    note                TEXT,
    quality_flags       TEXT NOT NULL DEFAULT '',
    is_valid            INTEGER NOT NULL DEFAULT 1,
    first_seen_run      TEXT,
    last_seen_run       TEXT
);
CREATE INDEX IF NOT EXISTS ix_prices_corridor ON rpw_prices (source_code, dest_code, period);
CREATE INDEX IF NOT EXISTS ix_prices_period ON rpw_prices (period);
CREATE INDEX IF NOT EXISTS ix_prices_provider ON rpw_prices (provider);

-- Results of every data quality check on every run.
CREATE TABLE IF NOT EXISTS quality_results (
    run_id        TEXT NOT NULL REFERENCES pipeline_runs(run_id),
    check_name    TEXT NOT NULL,
    severity      TEXT NOT NULL,           -- error (row excluded) | warning (row kept, flagged)
    rows_checked  INTEGER NOT NULL,
    rows_failed   INTEGER NOT NULL,
    pass_rate     REAL NOT NULL,
    description   TEXT,
    PRIMARY KEY (run_id, check_name)
);

-- Daily mid-market reference rates (ECB via Frankfurter, with a fallback source for other currencies).
CREATE TABLE IF NOT EXISTS fx_rates (
    rate_date   TEXT NOT NULL,
    base        TEXT NOT NULL,
    quote       TEXT NOT NULL,
    rate        REAL NOT NULL,
    source      TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (rate_date, base, quote)
);

-- Rate alerts. Only what is needed to deliver the alert is stored: a contact, a route and a target.
CREATE TABLE IF NOT EXISTS alerts (
    alert_id           TEXT PRIMARY KEY,
    manage_token       TEXT NOT NULL,          -- secret the user needs to edit or delete the alert
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    channel            TEXT NOT NULL,          -- email | telegram | outbox
    contact            TEXT NOT NULL,          -- email address or Telegram chat id
    send_currency      TEXT NOT NULL,
    receive_currency   TEXT NOT NULL,
    source_code        TEXT,                   -- optional: lets the alert link to the best provider
    dest_code          TEXT,
    target_rate        REAL NOT NULL,
    direction          TEXT NOT NULL DEFAULT 'at_least',  -- at_least | at_most
    cooldown_days      INTEGER NOT NULL DEFAULT 7,
    active             INTEGER NOT NULL DEFAULT 1,
    last_checked_at    TEXT,
    last_triggered_at  TEXT
);

-- Every alert delivery attempt. Used for reliability testing and retention tracking.
CREATE TABLE IF NOT EXISTS alert_events (
    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id    TEXT NOT NULL,
    fired_at    TEXT NOT NULL,
    rate        REAL NOT NULL,
    rate_date   TEXT NOT NULL,
    channel     TEXT NOT NULL,
    status      TEXT NOT NULL,           -- sent | failed
    detail      TEXT
);

-- Daily snapshot of alert counts, for retention analysis without keeping deleted alerts' contacts.
CREATE TABLE IF NOT EXISTS alert_daily_stats (
    stat_date        TEXT PRIMARY KEY,
    active_alerts    INTEGER NOT NULL,
    total_created    INTEGER NOT NULL,
    fired_today      INTEGER NOT NULL
);
