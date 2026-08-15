"""
VaultEq Ledger
==============
The double-entry ledger you pip install — not one you sign up for.

Deterministic. Hash-chained. Agent-native.
LLMs orchestrate. VaultEq computes.
"""

from .engine import (
    AccountType,
    AlreadyReversedError,
    Direction,
    DuplicateIdempotencyError,
    InvalidJournalError,
    JournalLineInput,
    LedgerEngine,
    OrganizationNotFoundError,
    AccountNotFoundError,
    AccountInactiveError,
    PeriodClosedError,
    PostRequest,
    PostResponse,
    UnbalancedJournalError,
    CurrencyMismatchError,
    VaultEqError,
)

__version__ = "0.2.0"

__all__ = [
    "LedgerEngine",
    "PostRequest",
    "PostResponse",
    "JournalLineInput",
    "Direction",
    "AccountType",
    "VaultEqError",
    "OrganizationNotFoundError",
    "AccountNotFoundError",
    "AccountInactiveError",
    "InvalidJournalError",
    "UnbalancedJournalError",
    "DuplicateIdempotencyError",
    "CurrencyMismatchError",
    "PeriodClosedError",
    "AlreadyReversedError",
]
