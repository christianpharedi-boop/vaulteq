"""
VaultEq Identity MCP Server
===========================
Exposes the IdentityEngine as MCP tools for agent-native compliance workflows.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:
    raise ImportError(
        'The MCP server requires the optional "mcp" dependency. '
        'Install with: pip install "vaulteq[mcp]"'
    ) from e

from vaulteq.identity.engine import (
    IdentityEngine,
    CustomerType,
    KYCLevel,
    KYCStatus,
    DocumentType,
    IdentityError
)
from vaulteq.ledger.engine import LedgerEngine

DB_PATH = os.environ.get("VAULTEQ_DB_PATH", ":memory:")
# Identity needs a ledger for audit trail integration
ledger = LedgerEngine(db_path=DB_PATH)
mcp = FastMCP("vaulteq-identity")

# Global engine instances per org would be better, but for MCP we'll use a shared one for now
# or better, inject org_id into tools.
engines: Dict[str, IdentityEngine] = {}

def get_engine(org_id: str) -> IdentityEngine:
    if org_id not in engines:
        engines[org_id] = IdentityEngine(organization_id=org_id, ledger=ledger)
    return engines[org_id]

def _ok(data: Any) -> dict:
    if isinstance(data, dict):
        return {"status": "success", **data}
    return {"status": "success", "data": data}

def _err(e: IdentityError) -> dict:
    return e.to_dict()

@mcp.tool()
def vaulteq_create_customer(
    organization_id: str,
    legal_name: str,
    customer_type: str = "INDIVIDUAL",
    email: str = "",
    phone: str = "",
    address: str = "",
    country: str = "",
) -> dict:
    """Create a customer for KYC/AML screening."""
    try:
        eng = get_engine(organization_id)
        c = eng.create_customer(
            legal_name=legal_name,
            customer_type=CustomerType(customer_type.upper()),
            email=email,
            phone=phone,
            address=address,
            country=country,
        )
        return _ok({"customer": c.to_dict()})
    except (IdentityError, ValueError) as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def vaulteq_initiate_kyc(
    organization_id: str,
    customer_id: str,
    level: str = "L1"
) -> dict:
    """Initiate a KYC case for a customer (L1, L2, or L3)."""
    try:
        eng = get_engine(organization_id)
        case = eng.initiate_kyc(customer_id, level=KYCLevel(level.upper()))
        return _ok({"kyc_case": case.to_dict()})
    except (IdentityError, ValueError) as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def vaulteq_verify_kyc(
    organization_id: str,
    kyc_case_id: str,
    status: str,
    reason: str = ""
) -> dict:
    """Approve or Reject a KYC case (manual review tool)."""
    try:
        eng = get_engine(organization_id)
        case = eng.verify_kyc(kyc_case_id, KYCStatus(status.upper()), reason=reason)
        return _ok({"kyc_case": case.to_dict()})
    except (IdentityError, ValueError) as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def vaulteq_screen_aml(
    organization_id: str,
    customer_id: str
) -> dict:
    """Perform AML/Sanctions/PEP screening on a customer."""
    try:
        eng = get_engine(organization_id)
        s = eng.screen_aml(customer_id)
        return _ok({"screening": s.to_dict()})
    except IdentityError as e:
        return _err(e)

@mcp.tool()
def vaulteq_assess_risk(
    organization_id: str,
    customer_id: str
) -> dict:
    """Get the current risk assessment and transaction eligibility for a customer."""
    try:
        eng = get_engine(organization_id)
        r = eng.assess_risk(customer_id)
        return _ok({
            "assessment": r.to_dict(),
            "can_transact": eng.can_transact(customer_id)
        })
    except IdentityError as e:
        return _err(e)

def main() -> None:
    mcp.run()

if __name__ == "__main__":
    main()
