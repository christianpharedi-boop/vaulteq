"""Payments HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from vaulteq.api.deps import get_payments
from vaulteq.api.schemas import (
    AddPaymentMethodRequest,
    AttachMethodRequest,
    CreateIntentRequest,
    ReconcileRequest,
    RefundRequest,
)
from vaulteq.payments.engine import PaymentsEngine, PaymentsError
from vaulteq.payments.models import PaymentMethodType, PaymentRail
from vaulteq.identity import TransactionBlockedError

router = APIRouter(prefix="/payments", tags=["payments"])


def _pay_err(e: Exception) -> HTTPException:
    if isinstance(e, PaymentsError):
        return HTTPException(status_code=400, detail=e.to_dict())
    if isinstance(e, TransactionBlockedError):
        return HTTPException(status_code=403, detail=e.to_dict())
    return HTTPException(status_code=400, detail={"status": "error", "message": str(e)})


@router.post("/intents")
def create_intent(body: CreateIntentRequest, eng: PaymentsEngine = Depends(get_payments)):
    try:
        intent = eng.create_intent(
            amount=body.amount,
            currency=body.currency,
            description=body.description,
            idempotency_key=body.idempotency_key,
            customer_id=body.customer_id,
        )
        return {"status": "success", "intent": intent.to_dict()}
    except Exception as e:
        raise _pay_err(e)


@router.post("/methods")
def add_method(body: AddPaymentMethodRequest, eng: PaymentsEngine = Depends(get_payments)):
    try:
        method = eng.add_payment_method(
            body.customer_id,
            PaymentMethodType(body.method_type.upper()),
            PaymentRail(body.rail.upper()),
        )
        return {"status": "success", "method": method.to_dict() if hasattr(method, "to_dict") else {
            "id": method.id,
            "customer_id": method.customer_id,
            "method_type": method.method_type.value,
            "rail": method.rail.value,
            "token": method.token,
        }}
    except Exception as e:
        raise _pay_err(e)


@router.post("/methods/attach")
def attach_method(body: AttachMethodRequest, eng: PaymentsEngine = Depends(get_payments)):
    try:
        intent = eng.attach_payment_method(body.intent_id, body.method_id)
        return {"status": "success", "intent": intent.to_dict()}
    except Exception as e:
        raise _pay_err(e)


@router.post("/capture/{intent_id}")
def capture(intent_id: str, eng: PaymentsEngine = Depends(get_payments)):
    try:
        return eng.confirm_and_capture(intent_id)
    except Exception as e:
        raise _pay_err(e)


@router.post("/refunds")
def refund(body: RefundRequest, eng: PaymentsEngine = Depends(get_payments)):
    try:
        return eng.refund(body.attempt_id, amount=body.amount)
    except Exception as e:
        raise _pay_err(e)


@router.post("/reconcile")
def reconcile(body: ReconcileRequest, eng: PaymentsEngine = Depends(get_payments)):
    try:
        return eng.reconcile(body.attempt_id, body.external_ref, body.external_amount)
    except Exception as e:
        raise _pay_err(e)


@router.get("/trial-balance")
def trial_balance(eng: PaymentsEngine = Depends(get_payments)):
    return eng.trial_balance()
