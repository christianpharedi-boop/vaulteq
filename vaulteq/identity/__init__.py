"""
VaultEq — Identity
==================
AI-native identity and compliance computation.
"""

from .engine import (
    CustomerNotFoundError,
    IdentityEngine,
    IdentityError,
    KYCCaseNotFoundError,
    Match,
    MockScreeningProvider,
    ScreeningProvider,
    ScreeningResult,
    TransactionBlockedError,
)
from .models import (
    AMLScreening,
    AMLStatus,
    Customer,
    CustomerType,
    DocumentStatus,
    DocumentType,
    KYCCase,
    KYCDocument,
    KYCLevel,
    KYCStatus,
    RiskAssessment,
    RiskLevel,
    ScreeningType,
)

__all__ = [
    "IdentityEngine",
    "MockScreeningProvider",
    "ScreeningProvider",
    "ScreeningResult",
    "Match",
    "IdentityError",
    "CustomerNotFoundError",
    "KYCCaseNotFoundError",
    "TransactionBlockedError",
    "Customer",
    "CustomerType",
    "KYCCase",
    "KYCStatus",
    "KYCLevel",
    "KYCDocument",
    "DocumentType",
    "DocumentStatus",
    "AMLScreening",
    "AMLStatus",
    "ScreeningType",
    "RiskAssessment",
    "RiskLevel",
]
