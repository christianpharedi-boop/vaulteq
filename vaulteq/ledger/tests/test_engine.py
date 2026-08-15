"""
VaultEq Ledger — comprehensive engine tests.
Covers balance rules, idempotency, reversals, audit chain, period close, FX.
"""

from __future__ import annotations

import pytest
from decimal import Decimal

from vaulteq.ledger import (
    AccountInactiveError,
    AccountNotFoundError,
    AccountType,
    AlreadyReversedError,
    CurrencyMismatchError,
    Direction,
    DuplicateIdempotencyError,
    InvalidJournalError,
    JournalLineInput,
    LedgerEngine,
    OrganizationNotFoundError,
    PeriodClosedError,
    PostRequest,
    UnbalancedJournalError,
)


@pytest.fixture
def engine():
    with LedgerEngine() as eng:
        yield eng


@pytest.fixture
def org(engine):
    oid = engine.create_organization("Test Org", "USD")
    engine.create_account(oid, "1001", "Cash", AccountType.ASSET, Direction.DEBIT)
    engine.create_account(oid, "4000", "Revenue", AccountType.REVENUE, Direction.CREDIT)
    engine.create_account(oid, "5000", "Expense", AccountType.EXPENSE, Direction.DEBIT)
    return oid


def _post(engine, org, key, debit_code, credit_code, amount, memo=None):
    return engine.post(
        PostRequest(
            organization_id=org,
            idempotency_key=key,
            memo=memo,
            lines=[
                JournalLineInput(debit_code, Direction.DEBIT, amount, "USD"),
                JournalLineInput(credit_code, Direction.CREDIT, amount, "USD"),
            ],
        )
    )


# ── Basic posting ─────────────────────────────────────────────────────────────

def test_balanced_journal_posts(engine, org):
    res = _post(engine, org, "k1", "1001", "4000", 10000)
    assert res.status == "posted"
    assert res.journal_entry_id
    assert res.cached is False
    assert res.trial_balance_delta["1001"] == 10000
    assert res.trial_balance_delta["4000"] == -10000


def test_trial_balance_accumulates(engine, org):
    _post(engine, org, "k1", "1001", "4000", 10000)
    _post(engine, org, "k2", "1001", "4000", 5000)
    tb = engine.get_trial_balance(org)
    assert tb["1001"] == 15000
    assert tb["4000"] == -15000


def test_unbalanced_rejected(engine, org):
    with pytest.raises(UnbalancedJournalError) as ei:
        engine.post(
            PostRequest(
                organization_id=org,
                idempotency_key="bad",
                lines=[
                    JournalLineInput("1001", Direction.DEBIT, 10000, "USD"),
                    JournalLineInput("4000", Direction.CREDIT, 9000, "USD"),
                ],
            )
        )
    assert ei.value.debit_total == 10000
    assert ei.value.credit_total == 9000
    assert engine.get_trial_balance(org).get("1001", 0) == 0


def test_fewer_than_two_lines_rejected(engine, org):
    with pytest.raises(InvalidJournalError):
        engine.post(
            PostRequest(
                organization_id=org,
                idempotency_key="one",
                lines=[JournalLineInput("1001", Direction.DEBIT, 100, "USD")],
            )
        )


def test_unknown_account_rejected(engine, org):
    with pytest.raises(AccountNotFoundError):
        engine.post(
            PostRequest(
                organization_id=org,
                idempotency_key="unk",
                lines=[
                    JournalLineInput("9999", Direction.DEBIT, 100, "USD"),
                    JournalLineInput("4000", Direction.CREDIT, 100, "USD"),
                ],
            )
        )


def test_unknown_org_rejected(engine):
    with pytest.raises(OrganizationNotFoundError):
        engine.post(
            PostRequest(
                organization_id="does_not_exist",
                idempotency_key="x",
                lines=[
                    JournalLineInput("1001", Direction.DEBIT, 100, "USD"),
                    JournalLineInput("4000", Direction.CREDIT, 100, "USD"),
                ],
            )
        )


# ── Idempotency ───────────────────────────────────────────────────────────────

def test_identical_retry_returns_cached(engine, org):
    r1 = _post(engine, org, "idem_1", "1001", "4000", 10000)
    r2 = _post(engine, org, "idem_1", "1001", "4000", 10000)
    assert r2.cached is True
    assert r2.journal_entry_id == r1.journal_entry_id
    assert engine.get_trial_balance(org)["1001"] == 10000  # not doubled


def test_different_payload_conflicts(engine, org):
    _post(engine, org, "idem_2", "1001", "4000", 10000)
    with pytest.raises(DuplicateIdempotencyError):
        _post(engine, org, "idem_2", "1001", "4000", 20000)


# ── Reversals ─────────────────────────────────────────────────────────────────

def test_reverse_zeros_balances(engine, org):
    r = _post(engine, org, "rev1", "1001", "4000", 25000)
    rev = engine.reverse(org, r.journal_entry_id)
    assert rev.journal_entry_id != r.journal_entry_id
    tb = engine.get_trial_balance(org)
    assert tb["1001"] == 0
    assert tb["4000"] == 0


def test_reverse_is_idempotent_via_key(engine, org):
    r = _post(engine, org, "rev2", "1001", "4000", 10000)
    rev1 = engine.reverse(org, r.journal_entry_id)
    # Second reverse of same entry should fail (already reversed)
    with pytest.raises(AlreadyReversedError):
        engine.reverse(org, r.journal_entry_id)


def test_original_linked_to_reversal(engine, org):
    r = _post(engine, org, "rev3", "1001", "4000", 10000)
    rev = engine.reverse(org, r.journal_entry_id)
    entry = engine.get_journal_entry(org, r.journal_entry_id)
    assert entry["reversed_by"] == rev.journal_entry_id


# ── Audit chain ───────────────────────────────────────────────────────────────

def test_audit_chain_valid_after_posts(engine, org):
    _post(engine, org, "a1", "1001", "4000", 1000)
    _post(engine, org, "a2", "1001", "4000", 2000)
    assert engine.verify_audit_chain(org) is True


def test_audit_trail_records_events(engine, org):
    _post(engine, org, "a3", "1001", "4000", 1000)
    trail = engine.get_audit_trail(org)
    assert len(trail) >= 1
    assert trail[0]["entity_type"] == "journal_entry"


# ── Period close ──────────────────────────────────────────────────────────────

def test_closed_period_rejects_posts(engine, org):
    from datetime import date
    engine.close_period(org, "2026-08")
    with pytest.raises(PeriodClosedError):
        engine.post(
            PostRequest(
                organization_id=org,
                idempotency_key="closed",
                posting_date=date(2026, 8, 15),
                lines=[
                    JournalLineInput("1001", Direction.DEBIT, 100, "USD"),
                    JournalLineInput("4000", Direction.CREDIT, 100, "USD"),
                ],
            )
        )


# ── Multi-currency ────────────────────────────────────────────────────────────

def test_fx_required_for_foreign_currency(engine, org):
    with pytest.raises(CurrencyMismatchError):
        engine.post(
            PostRequest(
                organization_id=org,
                idempotency_key="fx1",
                lines=[
                    JournalLineInput("1001", Direction.DEBIT, 10000, "EUR"),
                    JournalLineInput("4000", Direction.CREDIT, 10000, "EUR"),
                ],
            )
        )


def test_fx_rate_allows_foreign_post(engine, org):
    engine.set_exchange_rate(org, "EUR", "USD", Decimal("1.10"))
    res = engine.post(
        PostRequest(
            organization_id=org,
            idempotency_key="fx2",
            lines=[
                JournalLineInput("1001", Direction.DEBIT, 10000, "EUR"),
                JournalLineInput("4000", Direction.CREDIT, 10000, "EUR"),
            ],
        )
    )
    assert res.status == "posted"
    # 10000 EUR * 1.10 = 11000 USD minor
    assert res.trial_balance_delta["1001"] == 11000


# ── Queries ───────────────────────────────────────────────────────────────────

def test_list_accounts(engine, org):
    accts = engine.list_accounts(org)
    codes = {a["code"] for a in accts}
    assert "1001" in codes
    assert "4000" in codes


def test_get_account_balance(engine, org):
    _post(engine, org, "bal1", "1001", "4000", 4200)
    assert engine.get_account_balance(org, "1001") == 4200
    assert engine.get_account_balance(org, "4000") == -4200


def test_list_journal_entries(engine, org):
    _post(engine, org, "lj1", "1001", "4000", 100)
    _post(engine, org, "lj2", "1001", "4000", 200)
    entries = engine.list_journal_entries(org, limit=10)
    assert len(entries) >= 2
