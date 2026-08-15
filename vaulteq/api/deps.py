"""Shared dependencies — multi-tenant engine providers for the API."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Dict, Optional

from vaulteq.identity import IdentityEngine
from vaulteq.ledger import LedgerEngine
from vaulteq.payments.engine import PaymentsEngine

_DB_PATH = os.environ.get("VAULTEQ_DB_PATH", ":memory:")

# Singleton for the underlying shared Ledger storage
@lru_cache(maxsize=1)
def get_ledger() -> LedgerEngine:
    return LedgerEngine(db_path=_DB_PATH)

# In-memory cache for per-org engines to avoid constant re-initialization
_identity_engines: Dict[str, IdentityEngine] = {}
_payments_engines: Dict[str, PaymentsEngine] = {}

def get_identity_for_org(organization_id: str) -> IdentityEngine:
    """Provides a multi-tenant IdentityEngine bound to a specific organization."""
    if organization_id not in _identity_engines:
        _identity_engines[organization_id] = IdentityEngine(
            organization_id=organization_id, 
            ledger=get_ledger()
        )
    return _identity_engines[organization_id]

def get_payments_for_org(organization_id: str) -> PaymentsEngine:
    """Provides a multi-tenant PaymentsEngine bound to a specific organization."""
    if organization_id not in _payments_engines:
        _payments_engines[organization_id] = PaymentsEngine(
            organization_id=organization_id,
            ledger=get_ledger(),
            identity_engine=get_identity_for_org(organization_id),
        )
    return _payments_engines[organization_id]

# Compatibility helpers for existing routes (using default org)
_DEFAULT_ORG = os.environ.get("VAULTEQ_ORG_ID", "api_org_default")

def get_identity() -> IdentityEngine:
    return get_identity_for_org(_DEFAULT_ORG)

def get_payments() -> PaymentsEngine:
    return get_payments_for_org(_DEFAULT_ORG)

def reset_engines() -> None:
    """Test helper — clear cached engines."""
    get_ledger.cache_clear()
    _identity_engines.clear()
    _payments_engines.clear()
