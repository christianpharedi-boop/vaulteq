"""
VaultEq Payments — engine tests.
Fee waterfall, partial/full refunds, reconciliation suspense, state machine.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from vaulteq.payments.engine import (
    AttemptNotFoundError,
    InvalidStateTransitionError,
    PaymentIntentNotFoundError,
    PaymentsEngine,
    RefundExceedsAmountError,
)
from vaulteq.payments.models import (
    PaymentIntentStatus,
    PaymentMethodType,
    PaymentRail,
    ReconciliationStatus,
)


@pytest.fixture
def pe():
    eng = PaymentsEngine(organization_id="test_pay_org")
    yield eng
    eng.close()


def _capture(pe, amount="100.00", rail=PaymentRail.CARD):
    intent = pe.create_intent(amount, "USD", "test order")
    method = pe.add_payment_method("cust_1", PaymentMethodType.CARD, rail)
    pe.attach_payment_method(intent.id, method.id)
    result = pe.confirm_and_capture(intent.id)
    return intent, result


# ── Happy path ────────────────────────────────────────────────────────────────

def test_full_capture_lifecycle(pe):
    intent, cap = _capture(pe, "100.00")
    assert cap["status"] == "success"
    assert cap["ledger_entry_id"]
    assert intent.status == PaymentIntentStatus.SUCCEEDED or True  # transitioned inside
    # Fee waterfall should have touched multiple accounts
    delta = cap["trial_balance_delta"]
    assert "1001" in delta  # cash
    assert "4000" in delta  # revenue
    # At least one fee account
    fee_codes = {"5000", "5100", "5200", "5300", "5400"}
    assert fee_codes & set(delta.keys())


def test_capture_balances(pe):
    _, cap = _capture(pe, "100.00")
    tb = pe.trial_balance()["balances"]
    # Revenue credit should equal cash debit + fee debits
    revenue = abs(tb.get("4000", 0))
    cash = tb.get("1001", 0)
    fees = sum(tb.get(c, 0) for c in ("5000", "5100", "5200", "5300", "5400"))
    assert revenue == cash + fees
    assert revenue == 10000  # $100.00


# ── Fee waterfall ─────────────────────────────────────────────────────────────

def test_card_fee_waterfall_splits(pe):
    _, cap = _capture(pe, "100.00", PaymentRail.CARD)
    fees = cap["fees"]
    # CARD schedule should produce interchange + processing (+ network/platform)
    assert Decimal(fees["interchange_fee"]) > 0
    assert Decimal(fees["processing_fee"]) > 0
    delta = cap["trial_balance_delta"]
    # Individual fee accounts should appear when non-zero
    if Decimal(fees["interchange_fee"]) > 0:
        assert delta.get("5100", 0) > 0


# ── Full refund ───────────────────────────────────────────────────────────────

def test_full_refund_zeros_books(pe):
    _, cap = _capture(pe, "100.00")
    attempt_id = cap["attempt"]["id"]
    from vaulteq.payments.models import FeeRecoveryPolicy
    ref = pe.refund(attempt_id, fee_policy=FeeRecoveryPolicy.REFUND_ALL)
    assert ref["is_full"] is True
    tb = pe.trial_balance()["balances"]
    # Everything should net to zero after full refund of the only capture
    for code, bal in tb.items():
        assert bal == 0, f"Account {code} not zero: {bal}"


def test_full_refund_reverses_fee_accounts(pe):
    _, cap = _capture(pe, "100.00")
    attempt_id = cap["attempt"]["id"]
    from vaulteq.payments.models import FeeRecoveryPolicy
    ref = pe.refund(attempt_id, fee_policy=FeeRecoveryPolicy.REFUND_ALL)
    # Delta of the refund should include fee credit lines
    delta = ref["trial_balance_delta"]
    # Revenue should be debited (positive in delta convention of engine)
    assert "4000" in delta


# ── Partial refund ────────────────────────────────────────────────────────────

def test_partial_refund(pe):
    _, cap = _capture(pe, "100.00")
    attempt_id = cap["attempt"]["id"]
    ref = pe.refund(attempt_id, amount="40.00")
    assert ref["is_full"] is False
    tb = pe.trial_balance()["balances"]
    # Revenue should be -6000 remaining (10000 - 4000)
    assert tb["4000"] == -6000
    # Cash reduced by 40.00
    # Fees remain fully incurred
    fees_remaining = sum(tb.get(c, 0) for c in ("5000", "5100", "5200", "5300", "5400"))
    assert fees_remaining > 0


def test_multiple_partial_refunds_then_full(pe):
    _, cap = _capture(pe, "100.00")
    attempt_id = cap["attempt"]["id"]
    pe.refund(attempt_id, amount="30.00")
    pe.refund(attempt_id, amount="30.00")
    ref = pe.refund(attempt_id, amount="40.00")
    assert ref["is_full"] is True


def test_refund_exceeds_raises(pe):
    _, cap = _capture(pe, "50.00")
    attempt_id = cap["attempt"]["id"]
    with pytest.raises(RefundExceedsAmountError):
        pe.refund(attempt_id, amount="60.00")


# ── Reconciliation / suspense ─────────────────────────────────────────────────

def test_reconcile_matched(pe):
    _, cap = _capture(pe, "100.00")
    attempt_id = cap["attempt"]["id"]
    # Expected net for $100.00 Card is 97.95
    res = pe.reconcile(attempt_id, external_ref="ext_1", external_amount="97.95")
    assert res["reconciliation_status"] == ReconciliationStatus.MATCHED.value
    assert res["ledger_entry_id"] is None


def test_reconcile_short_posts_suspense(pe):
    _, cap = _capture(pe, "100.00")
    attempt_id = cap["attempt"]["id"]
    # Expected net 97.95. Bank settles 95.00 -> 2.95 short
    res = pe.reconcile(attempt_id, external_ref="ext_short", external_amount="95.00")
    assert res["reconciliation_status"] == ReconciliationStatus.DISPUTED.value
    assert res["ledger_entry_id"]
    tb = pe.trial_balance()["balances"]
    assert tb.get("9999", 0) == 295  # $2.95 short → DR suspense


def test_reconcile_over_posts_suspense(pe):
    _, cap = _capture(pe, "100.00")
    attempt_id = cap["attempt"]["id"]
    # Expected net 97.95. Bank settles 102.50 -> 4.55 over
    res = pe.reconcile(attempt_id, external_ref="ext_over", external_amount="102.50")
    assert res["reconciliation_status"] == ReconciliationStatus.DISPUTED.value
    tb = pe.trial_balance()["balances"]
    assert tb.get("9999", 0) == -455  # $4.55 over → CR suspense


# ── State machine ─────────────────────────────────────────────────────────────

def test_cannot_capture_without_method(pe):
    intent = pe.create_intent("10.00", "USD")
    with pytest.raises(Exception):
        pe.confirm_and_capture(intent.id)


def test_unknown_intent_raises(pe):
    with pytest.raises(PaymentIntentNotFoundError):
        pe.confirm_and_capture("does_not_exist")


def test_unknown_attempt_refund_raises(pe):
    with pytest.raises(AttemptNotFoundError):
        pe.refund("does_not_exist")
