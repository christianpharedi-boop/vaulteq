-- VaultEq Ledger Schema
-- Integer minor units only. Hash-chained audit. Real idempotency.

CREATE TABLE IF NOT EXISTS organization (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    base_currency   TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS account (
    id              TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organization(id),
    code            TEXT NOT NULL,
    name            TEXT NOT NULL,
    type            TEXT NOT NULL,               -- ASSET | LIABILITY | EQUITY | REVENUE | EXPENSE
    normal_balance  TEXT NOT NULL,               -- DEBIT | CREDIT
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (organization_id, code)
);

CREATE TABLE IF NOT EXISTS journal_entry (
    id              TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organization(id),
    idempotency_key TEXT NOT NULL,
    payload_hash    TEXT NOT NULL,
    posted_at       TEXT NOT NULL,
    memo            TEXT,
    reversed_by     TEXT REFERENCES journal_entry(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (organization_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS journal_line (
    id                  TEXT PRIMARY KEY,
    journal_entry_id    TEXT NOT NULL REFERENCES journal_entry(id),
    account_id          TEXT NOT NULL REFERENCES account(id),
    direction           TEXT NOT NULL,           -- DEBIT | CREDIT
    amount_minor        INTEGER NOT NULL CHECK (amount_minor > 0),
    currency            TEXT NOT NULL,
    fx_rate             TEXT,                    -- stored as string for exactness
    base_amount_minor   INTEGER NOT NULL,
    memo                TEXT
);

CREATE TABLE IF NOT EXISTS audit_event (
    id              TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organization(id),
    entity_type     TEXT NOT NULL,
    entity_id       TEXT NOT NULL,
    action          TEXT NOT NULL,
    payload         TEXT NOT NULL,
    payload_sha256  TEXT NOT NULL,              -- SHA-256 of the payload JSON
    prev_event_hash TEXT,                       -- previous payload_sha256 (hash chain)
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS closed_period (
    organization_id TEXT NOT NULL REFERENCES organization(id),
    period          TEXT NOT NULL,              -- YYYY-MM
    closed_at       TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (organization_id, period)
);

CREATE TABLE IF NOT EXISTS fx_rate (
    organization_id TEXT NOT NULL REFERENCES organization(id),
    from_currency   TEXT NOT NULL,
    to_currency     TEXT NOT NULL,
    rate            TEXT NOT NULL,              -- Decimal as string
    effective_at    TEXT NOT NULL,
    PRIMARY KEY (organization_id, from_currency, to_currency, effective_at)
);

-- Helpful indexes
CREATE INDEX IF NOT EXISTS idx_journal_entry_org_posted
    ON journal_entry (organization_id, posted_at);

CREATE INDEX IF NOT EXISTS idx_journal_line_entry
    ON journal_line (journal_entry_id);

CREATE INDEX IF NOT EXISTS idx_journal_line_account
    ON journal_line (account_id);

CREATE INDEX IF NOT EXISTS idx_audit_org_created
    ON audit_event (organization_id, created_at);

CREATE INDEX IF NOT EXISTS idx_fx_rate_lookup
    ON fx_rate (organization_id, from_currency, to_currency, effective_at DESC);
