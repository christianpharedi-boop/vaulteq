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

-- Identity & Compliance Durability Tables
CREATE TABLE IF NOT EXISTS identity_customer (
    id              TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organization(id),
    legal_name      TEXT NOT NULL,
    customer_type   TEXT NOT NULL,
    email           TEXT,
    phone           TEXT,
    address         TEXT,
    country         TEXT,
    metadata        TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS identity_kyc_case (
    id              TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL REFERENCES identity_customer(id),
    status          TEXT NOT NULL,
    level           TEXT NOT NULL,
    reason          TEXT DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS identity_document (
    id              TEXT PRIMARY KEY,
    case_id         TEXT NOT NULL REFERENCES identity_kyc_case(id),
    document_type   TEXT NOT NULL,
    document_number TEXT NOT NULL,
    status          TEXT NOT NULL,
    uploaded_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS identity_screening (
    id              TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL REFERENCES identity_customer(id),
    provider        TEXT NOT NULL,
    hit             INTEGER NOT NULL,
    matches         TEXT NOT NULL,
    screened_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS identity_risk_assessment (
    id              TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL REFERENCES identity_customer(id),
    risk_level      TEXT NOT NULL,
    factors         TEXT NOT NULL,
    assessed_at     TEXT NOT NULL
);

-- Payments Durability Tables
CREATE TABLE IF NOT EXISTS payment_intent (
    id                  TEXT PRIMARY KEY,
    organization_id     TEXT NOT NULL REFERENCES organization(id),
    customer_id         TEXT,
    amount_minor        INTEGER NOT NULL,
    currency            TEXT NOT NULL,
    description         TEXT,
    status              TEXT NOT NULL,
    idempotency_key     TEXT NOT NULL,
    payment_method_id   TEXT,
    metadata            TEXT,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payment_method (
    id                  TEXT PRIMARY KEY,
    organization_id     TEXT NOT NULL REFERENCES organization(id),
    customer_id         TEXT NOT NULL,
    method_type         TEXT NOT NULL,
    rail                TEXT NOT NULL,
    token               TEXT NOT NULL,
    is_default          INTEGER NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payment_attempt (
    id                  TEXT PRIMARY KEY,
    payment_intent_id   TEXT NOT NULL REFERENCES payment_intent(id),
    payment_method_id   TEXT NOT NULL REFERENCES payment_method(id),
    rail                TEXT NOT NULL,
    amount_minor        INTEGER NOT NULL,
    currency            TEXT NOT NULL,
    fee_breakdown_json  TEXT NOT NULL,
    status              TEXT NOT NULL,
    captured_at         TEXT,
    ledger_entry_id     TEXT
);

CREATE TABLE IF NOT EXISTS payment_refund (
    id                  TEXT PRIMARY KEY,
    payment_attempt_id  TEXT NOT NULL REFERENCES payment_attempt(id),
    amount_minor        INTEGER NOT NULL,
    currency            TEXT NOT NULL,
    status              TEXT NOT NULL,
    fee_policy          TEXT NOT NULL,
    ledger_entry_id     TEXT,
    refunded_at         TEXT NOT NULL
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
