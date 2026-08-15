"""
VaultEq — Payments Engine
=========================
AI-native payments computation library built on the VaultEq Ledger.

Fee waterfall, partial refunds, and reconciliation discrepancies
all produce balanced, idempotent, audited journal entries.

LLMs orchestrate. VaultEq computes.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from vaulteq.ledger import (
    AccountType,
    Direction,
    JournalLineInput,
    LedgerEngine,
    PostRequest,
    PostResponse,
)

from .models import (
    AttemptStatus,
    FeeBreakdown,
    FeeRecoveryPolicy,
    PaymentAttempt,
    PaymentIntent,
    PaymentIntentStatus,
    PaymentMethod,
    PaymentMethodType,
    PaymentRail,
    ReconciliationStatus,
    Refund,
    RefundStatus,
    calculate_fees,
)


class PaymentsError(Exception):
    def __init__(self, message: str, code: str = "PAYMENTS_ERROR"):
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict:
        return {"status": "error", "error_code": self.code, "message": self.message}


class PaymentIntentNotFoundError(PaymentsError):
    def __init__(self, intent_id: str):
        super().__init__(f"PaymentIntent '{intent_id}' not found.", code="INTENT_NOT_FOUND")


class AttemptNotFoundError(PaymentsError):
    def __init__(self, attempt_id: str):
        super().__init__(f"PaymentAttempt '{attempt_id}' not found.", code="ATTEMPT_NOT_FOUND")


class InvalidStateTransitionError(PaymentsError):
    def __init__(self, from_status: str, to_status: str):
        super().__init__(
            f"Cannot transition from {from_status} to {to_status}.",
            code="INVALID_STATE_TRANSITION",
        )


class RefundExceedsAmountError(PaymentsError):
    def __init__(self, requested: Decimal, available: Decimal):
        super().__init__(
            f"Refund amount {requested} exceeds available {available}.",
            code="REFUND_EXCEEDS_AMOUNT",
        )


_DEFAULT_ACCOUNTS = [
    ("1001", "PSP Settlement / Cash", AccountType.ASSET, Direction.DEBIT),
    ("1100", "Accounts Receivable", AccountType.ASSET, Direction.DEBIT),
    ("2000", "Customer Advances / Deferred Revenue", AccountType.LIABILITY, Direction.CREDIT),
    ("4000", "Payment Revenue", AccountType.REVENUE, Direction.CREDIT),
    ("5000", "Platform Fees", AccountType.EXPENSE, Direction.DEBIT),
    ("5100", "Interchange Fees", AccountType.EXPENSE, Direction.DEBIT),
    ("5200", "Network Fees", AccountType.EXPENSE, Direction.DEBIT),
    ("5300", "Processing Fees", AccountType.EXPENSE, Direction.DEBIT),
    ("5400", "FX Fees", AccountType.EXPENSE, Direction.DEBIT),
    ("9999", "Suspense / Reconciliation", AccountType.ASSET, Direction.DEBIT),
]


def _to_minor(amount: Decimal) -> int:
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class PaymentsEngine:
    """
    Payment state machine with strict ledger integration.

    Capture (fee waterfall):
        DR  1001  Cash (net)
        DR  5100/5200/5300/5000/5400  individual fees
        CR  4000  Revenue (gross)

    Full refund reverses the entire waterfall.
    Partial refund reverses revenue + cash only (fees stay incurred).
    Reconciliation discrepancies post to suspense.
    """

    def __init__(
        self,
        organization_id: str,
        db_path: str = ":memory:",
        base_currency: str = "USD",
        ledger: Optional[LedgerEngine] = None,
        identity_engine: Any = None,
    ):
        self.organization_id = organization_id
        self.base_currency = base_currency.upper()
        self.ledger = ledger or LedgerEngine(db_path=db_path)
        self.identity_engine = identity_engine  # optional IdentityEngine
        self._ensure_org_and_coa()
        self._intents: Dict[str, PaymentIntent] = {}
        self._methods: Dict[str, PaymentMethod] = {}
        self._attempts: Dict[str, PaymentAttempt] = {}
        self._refunds: Dict[str, Refund] = {}
        self._intent_customers: Dict[str, str] = {}  # intent_id -> customer_id

    def _ensure_org_and_coa(self) -> None:
        try:
            self.ledger.create_organization(
                "VaultEq Payments Org", self.base_currency, org_id=self.organization_id
            )
        except Exception:
            pass
        existing = {a["code"] for a in self.ledger.list_accounts(self.organization_id)}
        for code, name, acc_type, normal in _DEFAULT_ACCOUNTS:
            if code not in existing:
                try:
                    self.ledger.create_account(
                        self.organization_id, code, name, acc_type, normal
                    )
                except Exception:
                    pass

    def _transition(self, intent: PaymentIntent, to_status: PaymentIntentStatus) -> None:
        valid = {
            PaymentIntentStatus.CREATED: [PaymentIntentStatus.REQUIRES_PAYMENT_METHOD],
            PaymentIntentStatus.REQUIRES_PAYMENT_METHOD: [
                PaymentIntentStatus.REQUIRES_CONFIRMATION,
                PaymentIntentStatus.CANCELED,
            ],
            PaymentIntentStatus.REQUIRES_CONFIRMATION: [
                PaymentIntentStatus.PROCESSING,
                PaymentIntentStatus.CANCELED,
            ],
            PaymentIntentStatus.PROCESSING: [
                PaymentIntentStatus.SUCCEEDED,
                PaymentIntentStatus.REQUIRES_PAYMENT_METHOD,
                PaymentIntentStatus.CANCELED,
            ],
            PaymentIntentStatus.SUCCEEDED: [
                PaymentIntentStatus.REFUNDED,
                PaymentIntentStatus.PARTIALLY_REFUNDED,
            ],
            PaymentIntentStatus.PARTIALLY_REFUNDED: [
                PaymentIntentStatus.REFUNDED,
                PaymentIntentStatus.PARTIALLY_REFUNDED,
            ],
        }
        if to_status not in valid.get(intent.status, []):
            raise InvalidStateTransitionError(intent.status.value, to_status.value)
        intent.status = to_status

    def _fee_waterfall_lines(
        self, fees: FeeBreakdown, currency: str, reverse: bool = False
    ) -> List[JournalLineInput]:
        direction = Direction.CREDIT if reverse else Direction.DEBIT
        mapping = [
            ("5100", fees.interchange_fee),
            ("5200", fees.network_fee),
            ("5300", fees.processing_fee),
            ("5000", fees.platform_fee),
            ("5400", fees.fx_fee),
        ]
        lines: List[JournalLineInput] = []
        for code, amount in mapping:
            minor = _to_minor(amount)
            if minor > 0:
                lines.append(JournalLineInput(code, direction, minor, currency))
        return lines

    def create_intent(
        self,
        amount: str,
        currency: str,
        description: str = "",
        idempotency_key: Optional[str] = None,
        customer_id: Optional[str] = None,
    ) -> PaymentIntent:
        if customer_id and self.identity_engine is not None:
            self.identity_engine.assert_can_transact(customer_id)
        intent = PaymentIntent(
            organization_id=self.organization_id,
            amount=Decimal(amount),
            currency=currency.upper(),
            description=description,
            status=PaymentIntentStatus.CREATED,
            idempotency_key=idempotency_key or str(uuid.uuid4()),
        )
        self._transition(intent, PaymentIntentStatus.REQUIRES_PAYMENT_METHOD)
        self._intents[intent.id] = intent
        if customer_id:
            self._intent_customers[intent.id] = customer_id
        return intent

    def add_payment_method(
        self, customer_id: str, method_type: PaymentMethodType, rail: PaymentRail
    ) -> PaymentMethod:
        method = PaymentMethod(
            customer_id=customer_id,
            method_type=method_type,
            rail=rail,
            token=f"tok_{uuid.uuid4().hex[:8]}",
        )
        self._methods[method.id] = method
        return method

    def attach_payment_method(self, intent_id: str, method_id: str) -> PaymentIntent:
        if intent_id not in self._intents:
            raise PaymentIntentNotFoundError(intent_id)
        if method_id not in self._methods:
            raise PaymentsError(f"PaymentMethod '{method_id}' not found", code="METHOD_NOT_FOUND")
        intent = self._intents[intent_id]
        intent.payment_method_id = method_id
        self._transition(intent, PaymentIntentStatus.REQUIRES_CONFIRMATION)
        return intent

    def confirm_and_capture(self, intent_id: str) -> Dict[str, Any]:
        if intent_id not in self._intents:
            raise PaymentIntentNotFoundError(intent_id)
        intent = self._intents[intent_id]
        if not intent.payment_method_id:
            raise PaymentsError("No payment method attached", code="NO_PAYMENT_METHOD")

        # Compliance gate
        customer_id = self._intent_customers.get(intent_id)
        if customer_id and self.identity_engine is not None:
            self.identity_engine.assert_can_transact(customer_id)

        self._transition(intent, PaymentIntentStatus.PROCESSING)
        method = self._methods[intent.payment_method_id]
        is_cross = intent.currency != self.base_currency
        fees = calculate_fees(intent.amount, method.rail, intent.currency, is_cross_currency=is_cross)

        attempt = PaymentAttempt(
            payment_intent_id=intent_id,
            payment_method_id=intent.payment_method_id,
            rail=method.rail,
            amount=intent.amount,
            currency=intent.currency,
            fee_breakdown=fees,
            status=AttemptStatus.CAPTURED,
            captured_at=datetime.now(timezone.utc),
        )
        self._attempts[attempt.id] = attempt

        amount_minor = _to_minor(intent.amount)
        
        # Deterministic waterfall: sum of parts must equal total in minor units
        waterfall_lines = self._fee_waterfall_lines(fees, intent.currency, reverse=False)
        fee_minor = sum(line.amount_minor for line in waterfall_lines)
        
        net_minor = amount_minor - fee_minor
        if net_minor < 0:
            raise PaymentsError("Fees exceed payment amount", code="FEES_EXCEED_AMOUNT")
        if amount_minor <= 0:
            raise PaymentsError("Amount must be positive", code="INVALID_AMOUNT")

        lines: List[JournalLineInput] = [
            JournalLineInput("1001", Direction.DEBIT, net_minor, intent.currency),
        ]
        lines.extend(waterfall_lines)
        lines.append(JournalLineInput("4000", Direction.CREDIT, amount_minor, intent.currency))

        res: PostResponse = self.ledger.post(
            PostRequest(
                organization_id=self.organization_id,
                idempotency_key=f"cap_{attempt.id}",
                memo=f"Capture {intent_id} / attempt {attempt.id}",
                lines=lines,
            )
        )
        attempt.ledger_entry_id = res.journal_entry_id
        self._transition(intent, PaymentIntentStatus.SUCCEEDED)

        return {
            "status": "success",
            "intent": intent.to_dict(),
            "attempt": {
                "id": attempt.id,
                "amount": str(attempt.amount),
                "currency": attempt.currency,
                "status": attempt.status.value,
                "ledger_entry_id": attempt.ledger_entry_id,
                "fees": fees.to_dict(),
            },
            "ledger_entry_id": res.journal_entry_id,
            "audit_signature": res.audit_signature,
            "trial_balance_delta": res.trial_balance_delta,
            "fees": fees.to_dict(),
        }

    def refund(
        self, 
        attempt_id: str, 
        amount: Optional[str] = None, 
        fee_policy: FeeRecoveryPolicy = FeeRecoveryPolicy.KEEP_ALL
    ) -> Dict[str, Any]:
        """
        Processes a refund with an explicit fee recovery policy.
        """
        if attempt_id not in self._attempts:
            raise AttemptNotFoundError(attempt_id)
        attempt = self._attempts[attempt_id]
        intent = self._intents[attempt.payment_intent_id]

        refund_amount = Decimal(amount) if amount is not None else attempt.amount
        if refund_amount <= 0:
            raise PaymentsError("Refund amount must be positive", code="INVALID_AMOUNT")
        
        already_refunded = sum(
            (r.amount for r in self._refunds.values() if r.payment_attempt_id == attempt_id),
            Decimal("0"),
        )
        remaining = attempt.amount - already_refunded
        if refund_amount > remaining:
            raise RefundExceedsAmountError(refund_amount, remaining)

        refund = Refund(
            payment_attempt_id=attempt_id,
            amount=refund_amount,
            currency=attempt.currency,
            status=RefundStatus.SUCCEEDED,
        )
        self._refunds[refund.id] = refund

        is_full = (already_refunded + refund_amount) == attempt.amount
        amount_minor = _to_minor(refund_amount)

        # Calculate fee reversal based on policy
        lines: List[JournalLineInput] = [
            JournalLineInput("4000", Direction.DEBIT, amount_minor, attempt.currency),
        ]

        fee_to_reverse = FeeBreakdown()
        if fee_policy == FeeRecoveryPolicy.REFUND_ALL and is_full:
            fee_to_reverse = attempt.fee_breakdown
        elif fee_policy == FeeRecoveryPolicy.REFUND_PROPORTIONAL:
            ratio = refund_amount / attempt.amount
            fee_to_reverse = FeeBreakdown(
                interchange_fee=(attempt.fee_breakdown.interchange_fee * ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                processing_fee=(attempt.fee_breakdown.processing_fee * ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                network_fee=(attempt.fee_breakdown.network_fee * ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                platform_fee=(attempt.fee_breakdown.platform_fee * ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                fx_fee=(attempt.fee_breakdown.fx_fee * ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            )
        
        waterfall_reversal = self._fee_waterfall_lines(fee_to_reverse, attempt.currency, reverse=True)
        fee_minor_reversed = sum(line.amount_minor for line in waterfall_reversal)
        
        # Net credit to cash is the refund amount minus any recovered fees
        net_cash_minor = amount_minor - fee_minor_reversed
        lines.append(JournalLineInput("1001", Direction.CREDIT, net_cash_minor, attempt.currency))
        lines.extend(waterfall_reversal)

        res: PostResponse = self.ledger.post(
            PostRequest(
                organization_id=self.organization_id,
                idempotency_key=f"ref_{refund.id}",
                memo=f"{'Full' if is_full else 'Partial'} refund for attempt {attempt_id}",
                lines=lines,
            )
        )
        refund.ledger_entry_id = res.journal_entry_id
        new_status = (
            PaymentIntentStatus.REFUNDED if is_full else PaymentIntentStatus.PARTIALLY_REFUNDED
        )
        self._transition(intent, new_status)

        return {
            "status": "success",
            "refund": {
                "id": refund.id,
                "amount": str(refund.amount),
                "currency": refund.currency,
                "status": refund.status.value,
                "ledger_entry_id": refund.ledger_entry_id,
            },
            "ledger_entry_id": res.journal_entry_id,
            "audit_signature": res.audit_signature,
            "trial_balance_delta": res.trial_balance_delta,
            "is_full": is_full,
        }

    def reconcile(
        self,
        attempt_id: str,
        external_ref: str,
        external_amount: str,
        external_currency: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Reconciles the internal payment record against an external settlement amount.
        Compares against the NET amount (Gross - Fees) that should land in the Cash account.
        """
        if attempt_id not in self._attempts:
            raise AttemptNotFoundError(attempt_id)
        attempt = self._attempts[attempt_id]
        
        # Calculate expected net amount from the capture
        fee_minor = sum(_to_minor(getattr(attempt.fee_breakdown, f)) for f in [
            "interchange_fee", "processing_fee", "network_fee", "platform_fee", "fx_fee"
        ])
        expected_net = attempt.amount - (Decimal(fee_minor) / 100)
        
        ext_amt = Decimal(external_amount)
        diff = expected_net - ext_amt

        if diff == 0:
            return {
                "status": "success",
                "reconciliation_status": ReconciliationStatus.MATCHED.value,
                "discrepancy": "0",
                "external_reference": external_ref,
                "ledger_entry_id": None,
            }

        diff_minor = abs(_to_minor(diff))
        if diff > 0:
            # Short settlement: bank sent less than expected net
            memo = f"Recon: Short settlement ({diff}) for {attempt_id} vs {external_ref}"
            lines = [
                JournalLineInput("9999", Direction.DEBIT, diff_minor, attempt.currency, memo="Short settlement discrepancy"),
                JournalLineInput("1001", Direction.CREDIT, diff_minor, attempt.currency, memo=f"Adj for {external_ref}"),
            ]
        else:
            # Over settlement: bank sent more than expected net
            memo = f"Recon: Over settlement ({abs(diff)}) for {attempt_id} vs {external_ref}"
            lines = [
                JournalLineInput("1001", Direction.DEBIT, diff_minor, attempt.currency, memo=f"Adj for {external_ref}"),
                JournalLineInput("9999", Direction.CREDIT, diff_minor, attempt.currency, memo="Over settlement discrepancy"),
            ]

        res: PostResponse = self.ledger.post(
            PostRequest(
                organization_id=self.organization_id,
                idempotency_key=f"recon_{attempt_id}_{external_ref}",
                memo=memo,
                lines=lines,
            )
        )
        return {
            "status": "success",
            "reconciliation_status": ReconciliationStatus.DISPUTED.value,
            "discrepancy": str(diff),
            "external_reference": external_ref,
            "ledger_entry_id": res.journal_entry_id,
            "audit_signature": res.audit_signature,
            "trial_balance_delta": res.trial_balance_delta,
        }

    def trial_balance(self) -> Dict[str, Any]:
        return {
            "status": "success",
            "balances": self.ledger.get_trial_balance(self.organization_id),
        }

    def close(self) -> None:
        self.ledger.close()
