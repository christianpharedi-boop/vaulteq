"""
VaultEq Ledger MCP Server
=========================
Exposes the LedgerEngine as MCP tools so any MCP-compatible agent
can post balanced journal entries without doing the arithmetic itself.

Run:
    vaulteq-mcp                          # in-memory (ephemeral)
    VAULTEQ_DB_PATH=./ledger.db vaulteq-mcp   # persistent

Requires: pip install "vaulteq[mcp]"
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any, Dict, List, Optional

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:
    raise ImportError(
        'The MCP server requires the optional "mcp" dependency. '
        'Install with: pip install "vaulteq[mcp]"'
    ) from e

from vaulteq.ledger.engine import (
    AccountType,
    Direction,
    JournalLineInput,
    LedgerEngine,
    PostRequest,
    VaultEqError,
)

DB_PATH = os.environ.get("VAULTEQ_DB_PATH", ":memory:")
engine = LedgerEngine(db_path=DB_PATH)
mcp = FastMCP("vaulteq-ledger")


def _ok(data: Any) -> dict:
    if isinstance(data, dict):
        return {"status": "success", **data}
    return {"status": "success", "data": data}


def _err(e: VaultEqError) -> dict:
    return e.to_dict()


@mcp.tool()
def vaulteq_create_organization(name: str, base_currency: str = "USD") -> dict:
    """Create an organization. Every account and journal entry belongs to one."""
    try:
        org_id = engine.create_organization(name=name, base_currency=base_currency)
        return _ok(
            {
                "organization_id": org_id,
                "name": name,
                "base_currency": base_currency.upper(),
            }
        )
    except VaultEqError as e:
        return _err(e)


@mcp.tool()
def vaulteq_create_account(
    organization_id: str,
    code: str,
    name: str,
    type: str,
    normal_balance: str,
) -> dict:
    """
    Create an account in the chart of accounts.
    type: ASSET | LIABILITY | EQUITY | REVENUE | EXPENSE
    normal_balance: DEBIT | CREDIT
    """
    try:
        acc_id = engine.create_account(
            organization_id,
            code,
            name,
            AccountType(type.upper()),
            Direction(normal_balance.upper()),
        )
        return _ok({"account_id": acc_id, "code": code, "name": name})
    except VaultEqError as e:
        return _err(e)
    except ValueError as e:
        return {
            "status": "error",
            "error_code": "INVALID_ARGUMENT",
            "message": str(e),
        }


@mcp.tool()
def vaulteq_post(
    organization_id: str,
    idempotency_key: str,
    lines: list,
    memo: Optional[str] = None,
) -> dict:
    """
    Post a double-entry journal entry. Rejected if debits != credits.
    lines: list of {
        "account_code": str,
        "direction": "DEBIT"|"CREDIT",
        "amount_minor": int,          # integer minor units (cents)
        "currency": str,
        "memo": str (optional)
    }
    Always pass a stable idempotency_key. Retrying the same key + same lines is safe.
    """
    try:
        req_lines = []
        for l in lines:
            req_lines.append(
                JournalLineInput(
                    account_code=l["account_code"],
                    direction=Direction(l["direction"].upper()),
                    amount_minor=int(l["amount_minor"]),
                    currency=l["currency"],
                    memo=l.get("memo"),
                )
            )
        resp = engine.post(
            PostRequest(
                organization_id=organization_id,
                idempotency_key=idempotency_key,
                memo=memo,
                lines=req_lines,
            )
        )
        # Convert dataclass to plain dict for MCP
        return {
            "status": resp.status,
            "journal_entry_id": resp.journal_entry_id,
            "audit_event_id": resp.audit_event_id,
            "audit_signature": resp.audit_signature,
            "trial_balance_delta": resp.trial_balance_delta,
            "cached": resp.cached,
            "execution_time_ms": resp.execution_time_ms,
            "affected_accounts": resp.affected_accounts,
        }
    except VaultEqError as e:
        return _err(e)
    except (KeyError, ValueError, TypeError) as e:
        return {
            "status": "error",
            "error_code": "INVALID_ARGUMENT",
            "message": str(e),
        }


@mcp.tool()
def vaulteq_reverse(
    organization_id: str,
    entry_id: str,
    memo: Optional[str] = None,
) -> dict:
    """Create an automatic reversal of a posted journal entry (exact opposite lines)."""
    try:
        resp = engine.reverse(organization_id, entry_id, memo=memo)
        return {
            "status": "success",
            "reversal_entry_id": resp.journal_entry_id,
            "audit_event_id": resp.audit_event_id,
            "audit_signature": resp.audit_signature,
            "trial_balance_delta": resp.trial_balance_delta,
        }
    except VaultEqError as e:
        return _err(e)


@mcp.tool()
def vaulteq_list_accounts(organization_id: str) -> dict:
    """List all accounts in the Chart of Accounts for an organization."""
    try:
        accounts = engine.list_accounts(organization_id)
        return _ok({"accounts": accounts})
    except VaultEqError as e:
        return _err(e)


@mcp.tool()
def vaulteq_get_account_balance(organization_id: str, account_code: str) -> dict:
    """Get the current net balance of a specific account (reversed entries excluded)."""
    try:
        balance = engine.get_account_balance(organization_id, account_code)
        return _ok({"account_code": account_code, "balance": balance})
    except VaultEqError as e:
        return _err(e)


@mcp.tool()
def vaulteq_get_trial_balance(organization_id: str) -> dict:
    """Retrieve the trial balance for an organization (reversed entries excluded)."""
    try:
        balances = engine.get_trial_balance(organization_id)
        return _ok({"balances": balances})
    except VaultEqError as e:
        return _err(e)


@mcp.tool()
def vaulteq_get_journal_entry(organization_id: str, entry_id: str) -> dict:
    """Fetch a single journal entry with its lines."""
    try:
        entry = engine.get_journal_entry(organization_id, entry_id)
        if entry is None:
            return {
                "status": "error",
                "error_code": "NOT_FOUND",
                "message": f"Journal entry {entry_id} not found",
            }
        return _ok({"entry": entry})
    except VaultEqError as e:
        return _err(e)


@mcp.tool()
def vaulteq_list_journal_entries(
    organization_id: str, limit: int = 50, after_id: Optional[str] = None
) -> dict:
    """List journal entries (newest first). Optional cursor via after_id."""
    try:
        entries = engine.list_journal_entries(
            organization_id, limit=limit, after_id=after_id
        )
        return _ok({"entries": entries})
    except VaultEqError as e:
        return _err(e)


@mcp.tool()
def vaulteq_get_audit_trail(organization_id: str, limit: int = 50) -> dict:
    """Return the most recent audit events for an organization."""
    try:
        events = engine.get_audit_trail(organization_id, limit=limit)
        return _ok({"events": events})
    except VaultEqError as e:
        return _err(e)


@mcp.tool()
def vaulteq_verify_audit_chain(organization_id: str) -> dict:
    """Verify the integrity of the hash-chained audit trail."""
    try:
        ok = engine.verify_audit_chain(organization_id)
        return _ok({"valid": ok})
    except VaultEqError as e:
        return _err(e)


@mcp.tool()
def vaulteq_close_period(organization_id: str, period: str) -> dict:
    """Close an accounting period (format: YYYY-MM). Further posts to that period are rejected."""
    try:
        engine.close_period(organization_id, period)
        return _ok({"message": f"Period {period} closed"})
    except VaultEqError as e:
        return _err(e)


@mcp.tool()
def vaulteq_set_exchange_rate(
    organization_id: str,
    from_currency: str,
    to_currency: str,
    rate: str,
) -> dict:
    """Register an exchange rate used for multi-currency postings."""
    try:
        engine.set_exchange_rate(
            organization_id,
            from_currency,
            to_currency,
            Decimal(rate),
        )
        return _ok(
            {
                "from_currency": from_currency.upper(),
                "to_currency": to_currency.upper(),
                "rate": rate,
            }
        )
    except VaultEqError as e:
        return _err(e)
    except Exception as e:
        return {
            "status": "error",
            "error_code": "INVALID_ARGUMENT",
            "message": str(e),
        }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
