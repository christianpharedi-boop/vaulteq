"""
VaultEq — Payments
====================
AI-native payments computation library.
"""

from .engine import PaymentsEngine
from .models import (
    PaymentIntent,
    PaymentIntentStatus,
    PaymentMethod,
    PaymentMethodType,
    PaymentRail,
    PaymentAttempt,
    AttemptStatus,
    Refund,
    RefundStatus,
    ReconciliationStatus
)

__version__ = "0.1.0"
