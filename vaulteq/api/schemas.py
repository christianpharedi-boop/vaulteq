"""Pydantic request/response schemas for the VaultEq HTTP API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Ledger ────────────────────────────────────────────────────────────────────

class CreateOrganizationRequest(BaseModel):
    name: str
    base_currency: str = "USD"
    organization_id: Optional[str] = None


class CreateAccountRequest(BaseModel):
    organization_id: str
    code: str
    name: str
    type: str = Field(..., description="ASSET | LIABILITY | EQUITY | REVENUE | EXPENSE")
    normal_balance: str = Field(..., description="DEBIT | CREDIT")


class JournalLineSchema(BaseModel):
    account_code: str
    direction: str
    amount_minor: int
    currency: str
    memo: Optional[str] = None


class PostJournalRequest(BaseModel):
    organization_id: str
    idempotency_key: str
    lines: List[JournalLineSchema]
    memo: Optional[str] = None


class ReverseRequest(BaseModel):
    organization_id: str
    entry_id: str
    memo: Optional[str] = None


class SetFxRateRequest(BaseModel):
    organization_id: str
    from_currency: str
    to_currency: str
    rate: str


class ClosePeriodRequest(BaseModel):
    organization_id: str
    period: str = Field(..., description="YYYY-MM")


# ── Payments ──────────────────────────────────────────────────────────────────

class CreateIntentRequest(BaseModel):
    amount: str
    currency: str = "USD"
    description: str = ""
    customer_id: Optional[str] = None
    idempotency_key: Optional[str] = None


class AddPaymentMethodRequest(BaseModel):
    customer_id: str
    method_type: str = "CARD"
    rail: str = "CARD"


class AttachMethodRequest(BaseModel):
    intent_id: str
    method_id: str


class RefundRequest(BaseModel):
    attempt_id: str
    amount: Optional[str] = None


class ReconcileRequest(BaseModel):
    attempt_id: str
    external_ref: str
    external_amount: str


# ── Identity ──────────────────────────────────────────────────────────────────

class CreateCustomerRequest(BaseModel):
    legal_name: str
    customer_type: str = "INDIVIDUAL"
    email: str = ""
    phone: str = ""
    address: str = ""
    country: str = ""


class InitiateKycRequest(BaseModel):
    customer_id: str
    level: str = "L1"


class UploadDocumentRequest(BaseModel):
    kyc_case_id: str
    document_type: str
    document_number: str
    file_url: str = ""


class VerifyKycRequest(BaseModel):
    kyc_case_id: str
    status: str
    reason: str = ""


class ScreenAmlRequest(BaseModel):
    customer_id: str


# ── Generic ───────────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    status: str = "error"
    error_code: str
    message: str
