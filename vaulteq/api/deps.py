"""Shared dependencies — single in-process engines for the API process."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from vaulteq.identity import IdentityEngine
from vaulteq.ledger import LedgerEngine
from vaulteq.payments.engine import PaymentsEngine

_DB_PATH = os.environ.get("VAULTEQ_DB_PATH", ":memory:")
_ORG_ID = os.environ.get("VAULTEQ_ORG_ID", "api_org_default")


@lru_cache(maxsize=1)
def get_ledger() -> LedgerEngine:
    return LedgerEngine(db_path=_DB_PATH)


@lru_cache(maxsize=1)
def get_identity() -> IdentityEngine:
    return IdentityEngine(organization_id=_ORG_ID, ledger=get_ledger())


@lru_cache(maxsize=1)
def get_payments() -> PaymentsEngine:
    return PaymentsEngine(
        organization_id=_ORG_ID,
        ledger=get_ledger(),
        identity_engine=get_identity(),
    )


def reset_engines() -> None:
    """Test helper — clear cached engines."""
    get_ledger.cache_clear()
    get_identity.cache_clear()
    get_payments.cache_clear()
