"""
VaultEq — Payments Core Domain Models
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Optional, List

class PaymentRail(str, Enum):
    CARD = "CARD"
    ACH = "ACH"
    SEPA = "SEPA"
    SWIFT = "SWIFT"
    RTP = "RTP"
    FASTER_PAYMENTS = "FASTER_PAYMENTS"
    CRYPTO = "CRYPTO"
    INTERNAL = "INTERNAL"

class PaymentMethodType(str, Enum):
    CARD = "CARD"
    BANK_ACCOUNT = "BANK_ACCOUNT"
    CRYPTO_WALLET = "CRYPTO_WALLET"
    INTERNAL_ACCOUNT = "INTERNAL_ACCOUNT"

class PaymentIntentStatus(str, Enum):
    CREATED = "CREATED"
    REQUIRES_PAYMENT_METHOD = "REQUIRES_PAYMENT_METHOD"
    REQUIRES_CONFIRMATION = "REQUIRES_CONFIRMATION"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"

class AttemptStatus(str, Enum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"

class RefundStatus(str, Enum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"

class ReconciliationStatus(str, Enum):
    UNRECONCILED = "UNRECONCILED"
    MATCHED = "MATCHED"
    DISPUTED = "DISPUTED"

@dataclass
class FeeBreakdown:
    interchange_fee: Decimal = Decimal("0.00")
    processing_fee: Decimal = Decimal("0.00")
    network_fee: Decimal = Decimal("0.00")
    platform_fee: Decimal = Decimal("0.00")
    fx_fee: Decimal = Decimal("0.00")

    @property
    def total_fee(self) -> Decimal:
        return self.interchange_fee + self.processing_fee + self.network_fee + self.platform_fee + self.fx_fee

    def to_dict(self) -> dict:
        return {k: str(v) for k, v in self.__dict__.items() if isinstance(v, Decimal)}

@dataclass
class PaymentIntent:
    organization_id: str
    amount: Decimal
    currency: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: PaymentIntentStatus = PaymentIntentStatus.CREATED
    description: str = ""
    payment_method_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "amount": str(self.amount),
            "currency": self.currency,
            "status": self.status.value,
            "description": self.description,
            "payment_method_id": self.payment_method_id,
            "created_at": self.created_at.isoformat()
        }

@dataclass
class PaymentMethod:
    customer_id: str
    method_type: PaymentMethodType
    rail: PaymentRail
    token: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "method_type": self.method_type.value,
            "rail": self.rail.value,
            "token": self.token
        }

@dataclass
class PaymentAttempt:
    payment_intent_id: str
    payment_method_id: str
    rail: PaymentRail
    amount: Decimal
    currency: str
    fee_breakdown: FeeBreakdown
    status: AttemptStatus = AttemptStatus.PENDING
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    ledger_entry_id: Optional[str] = None
    captured_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "payment_intent_id": self.payment_intent_id,
            "payment_method_id": self.payment_method_id,
            "rail": self.rail.value,
            "amount": str(self.amount),
            "currency": self.currency,
            "fee_breakdown": self.fee_breakdown.to_dict(),
            "status": self.status.value,
            "ledger_entry_id": self.ledger_entry_id,
            "captured_at": self.captured_at.isoformat() if self.captured_at else None
        }

@dataclass
class Refund:
    payment_attempt_id: str
    amount: Decimal
    currency: str
    status: RefundStatus = RefundStatus.PENDING
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    ledger_entry_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "payment_attempt_id": self.payment_attempt_id,
            "amount": str(self.amount),
            "currency": self.currency,
            "status": self.status.value,
            "ledger_entry_id": self.ledger_entry_id
        }

def calculate_fees(
    amount: Decimal,
    rail: PaymentRail,
    currency: str = "USD",
    is_cross_currency: bool = False,
) -> FeeBreakdown:
    """Deterministic fee schedule. Amounts are major units."""
    amount = Decimal(amount)
    if rail == PaymentRail.CARD:
        interchange = (amount * Decimal("0.0175")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        processing = (amount * Decimal("0.0015")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        network = Decimal("0.05")
        platform = (amount * Decimal("0.0010")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    elif rail == PaymentRail.ACH:
        interchange = Decimal("0.00")
        processing = (amount * Decimal("0.0008")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        network = Decimal("0.25")
        platform = (amount * Decimal("0.0010")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    elif rail == PaymentRail.SWIFT:
        interchange = Decimal("0.00")
        processing = (amount * Decimal("0.0050")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        network = Decimal("15.00")
        platform = (amount * Decimal("0.0020")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        interchange = processing = network = platform = Decimal("0.00")

    fx_fee = (
        (amount * Decimal("0.01")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if is_cross_currency else Decimal("0.00")
    )
    return FeeBreakdown(
        interchange_fee=interchange,
        processing_fee=processing,
        network_fee=network,
        platform_fee=platform,
        fx_fee=fx_fee,
    )
