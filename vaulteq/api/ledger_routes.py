"""Ledger HTTP routes."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException

from vaulteq.api.deps import get_ledger
from vaulteq.api.schemas import (
    ClosePeriodRequest,
    CreateAccountRequest,
    CreateOrganizationRequest,
    PostJournalRequest,
    ReverseRequest,
    SetFxRateRequest,
)
from vaulteq.ledger import (
    AccountType,
    Direction,
    JournalLineInput,
    LedgerEngine,
    PostRequest,
    VaultEqError,
)

router = APIRouter(prefix="/ledger", tags=["ledger"])


def _err(e: VaultEqError) -> HTTPException:
    return HTTPException(status_code=400, detail=e.to_dict())


@router.post("/organizations")
def create_organization(body: CreateOrganizationRequest, eng: LedgerEngine = Depends(get_ledger)):
    try:
        org_id = eng.create_organization(body.name, body.base_currency, org_id=body.organization_id)
        return {"status": "success", "organization_id": org_id, "name": body.name}
    except VaultEqError as e:
        raise _err(e)


@router.post("/accounts")
def create_account(body: CreateAccountRequest, eng: LedgerEngine = Depends(get_ledger)):
    try:
        acc_id = eng.create_account(
            body.organization_id,
            body.code,
            body.name,
            AccountType(body.type.upper()),
            Direction(body.normal_balance.upper()),
        )
        return {"status": "success", "account_id": acc_id, "code": body.code}
    except VaultEqError as e:
        raise _err(e)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"status": "error", "message": str(e)})


@router.get("/accounts/{organization_id}")
def list_accounts(organization_id: str, eng: LedgerEngine = Depends(get_ledger)):
    return {"status": "success", "accounts": eng.list_accounts(organization_id)}


@router.post("/journal")
def post_journal(body: PostJournalRequest, eng: LedgerEngine = Depends(get_ledger)):
    try:
        lines = [
            JournalLineInput(
                account_code=l.account_code,
                direction=Direction(l.direction.upper()),
                amount_minor=l.amount_minor,
                currency=l.currency,
                memo=l.memo,
            )
            for l in body.lines
        ]
        res = eng.post(
            PostRequest(
                organization_id=body.organization_id,
                idempotency_key=body.idempotency_key,
                memo=body.memo,
                lines=lines,
            )
        )
        return {
            "status": res.status,
            "journal_entry_id": res.journal_entry_id,
            "audit_event_id": res.audit_event_id,
            "audit_signature": res.audit_signature,
            "trial_balance_delta": res.trial_balance_delta,
            "cached": res.cached,
            "execution_time_ms": res.execution_time_ms,
        }
    except VaultEqError as e:
        raise _err(e)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"status": "error", "message": str(e)})


@router.post("/journal/reverse")
def reverse_journal(body: ReverseRequest, eng: LedgerEngine = Depends(get_ledger)):
    try:
        res = eng.reverse(body.organization_id, body.entry_id, memo=body.memo)
        return {
            "status": "success",
            "reversal_entry_id": res.journal_entry_id,
            "audit_signature": res.audit_signature,
            "trial_balance_delta": res.trial_balance_delta,
        }
    except VaultEqError as e:
        raise _err(e)


@router.get("/trial-balance/{organization_id}")
def trial_balance(organization_id: str, eng: LedgerEngine = Depends(get_ledger)):
    return {"status": "success", "balances": eng.get_trial_balance(organization_id)}


@router.get("/journal/{organization_id}/{entry_id}")
def get_journal_entry(organization_id: str, entry_id: str, eng: LedgerEngine = Depends(get_ledger)):
    entry = eng.get_journal_entry(organization_id, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail={"status": "error", "error_code": "NOT_FOUND"})
    return {"status": "success", "entry": entry}


@router.get("/audit/{organization_id}")
def audit_trail(organization_id: str, limit: int = 50, eng: LedgerEngine = Depends(get_ledger)):
    return {"status": "success", "events": eng.get_audit_trail(organization_id, limit=limit)}


@router.get("/audit/{organization_id}/verify")
def verify_audit(organization_id: str, eng: LedgerEngine = Depends(get_ledger)):
    return {"status": "success", "valid": eng.verify_audit_chain(organization_id)}


@router.post("/fx-rates")
def set_fx_rate(body: SetFxRateRequest, eng: LedgerEngine = Depends(get_ledger)):
    try:
        eng.set_exchange_rate(
            body.organization_id,
            body.from_currency,
            body.to_currency,
            Decimal(body.rate),
        )
        return {"status": "success"}
    except VaultEqError as e:
        raise _err(e)


@router.post("/periods/close")
def close_period(body: ClosePeriodRequest, eng: LedgerEngine = Depends(get_ledger)):
    try:
        eng.close_period(body.organization_id, body.period)
        return {"status": "success", "period": body.period}
    except VaultEqError as e:
        raise _err(e)
