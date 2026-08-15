"""Identity HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from vaulteq.api.deps import get_identity
from vaulteq.api.schemas import (
    CreateCustomerRequest,
    InitiateKycRequest,
    ScreenAmlRequest,
    UploadDocumentRequest,
    VerifyKycRequest,
)
from vaulteq.identity import (
    CustomerType,
    DocumentType,
    IdentityEngine,
    IdentityError,
    KYCLevel,
    KYCStatus,
)

router = APIRouter(prefix="/identity", tags=["identity"])


def _id_err(e: IdentityError) -> HTTPException:
    code = 404 if e.code.endswith("NOT_FOUND") else 400
    if e.code == "TRANSACTION_BLOCKED":
        code = 403
    return HTTPException(status_code=code, detail=e.to_dict())


@router.post("/customers")
def create_customer(body: CreateCustomerRequest, eng: IdentityEngine = Depends(get_identity)):
    try:
        c = eng.create_customer(
            legal_name=body.legal_name,
            customer_type=CustomerType(body.customer_type.upper()),
            email=body.email,
            phone=body.phone,
            address=body.address,
            country=body.country,
        )
        return {"status": "success", "customer": c.to_dict()}
    except IdentityError as e:
        raise _id_err(e)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"status": "error", "message": str(e)})


@router.get("/customers")
def list_customers(eng: IdentityEngine = Depends(get_identity)):
    return {"status": "success", "customers": [c.to_dict() for c in eng.list_customers()]}


@router.get("/customers/{customer_id}")
def get_customer(customer_id: str, eng: IdentityEngine = Depends(get_identity)):
    try:
        return {"status": "success", "customer": eng.get_customer(customer_id).to_dict()}
    except IdentityError as e:
        raise _id_err(e)


@router.post("/kyc")
def initiate_kyc(body: InitiateKycRequest, eng: IdentityEngine = Depends(get_identity)):
    try:
        case = eng.initiate_kyc(body.customer_id, level=KYCLevel(body.level.upper()))
        return {"status": "success", "kyc_case": case.to_dict()}
    except IdentityError as e:
        raise _id_err(e)


@router.post("/kyc/documents")
def upload_document(body: UploadDocumentRequest, eng: IdentityEngine = Depends(get_identity)):
    try:
        doc = eng.upload_document(
            body.kyc_case_id,
            DocumentType(body.document_type.upper()),
            body.document_number,
            file_url=body.file_url,
        )
        return {"status": "success", "document": doc.to_dict()}
    except IdentityError as e:
        raise _id_err(e)


@router.post("/kyc/verify")
def verify_kyc(body: VerifyKycRequest, eng: IdentityEngine = Depends(get_identity)):
    try:
        case = eng.verify_kyc(body.kyc_case_id, KYCStatus(body.status.upper()), reason=body.reason)
        return {"status": "success", "kyc_case": case.to_dict()}
    except IdentityError as e:
        raise _id_err(e)


@router.post("/aml/screen")
def screen_aml(body: ScreenAmlRequest, eng: IdentityEngine = Depends(get_identity)):
    try:
        s = eng.screen_aml(body.customer_id)
        return {"status": "success", "screening": s.to_dict()}
    except IdentityError as e:
        raise _id_err(e)


@router.get("/risk/{customer_id}")
def assess_risk(customer_id: str, eng: IdentityEngine = Depends(get_identity)):
    try:
        r = eng.assess_risk(customer_id)
        return {"status": "success", "assessment": r.to_dict(), "can_transact": eng.can_transact(customer_id)}
    except IdentityError as e:
        raise _id_err(e)
