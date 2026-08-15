"""
VaultEq — Identity & Compliance Engine
======================================
Deterministic KYC/AML/risk computation for agents.

Optional ledger binding: compliance decisions can be recorded on the
shared audit chain; PROHIBITED customers are blocked from transacting.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol

from .models import (
    AMLScreening,
    AMLStatus,
    Customer,
    CustomerType,
    DocumentType,
    KYCCase,
    KYCDocument,
    KYCLevel,
    KYCStatus,
    RiskAssessment,
    RiskLevel,
    ScreeningType,
)


# ── Screening interface ───────────────────────────────────────────────────────

@dataclass
class Match:
    confidence: float
    source: str
    match_type: str
    details: str


@dataclass
class ScreeningResult:
    hit: bool
    matches: List[Match]
    provider: str
    screened_at: datetime


class ScreeningProvider(Protocol):
    def screen(
        self,
        name: str,
        dob: Optional[str] = None,
        nationality: Optional[str] = None,
    ) -> ScreeningResult: ...


class MockScreeningProvider:
    """Deterministic mock: names containing 'SANCTIONED' or 'BLOCKED' hit."""

    PROVIDER_ID = "mock_screening_v1"

    def screen(
        self,
        name: str,
        dob: Optional[str] = None,
        nationality: Optional[str] = None,
    ) -> ScreeningResult:
        upper = name.upper()
        hit = any(tok in upper for tok in ("SANCTIONED", "BLOCKED", "OFAC"))
        matches: List[Match] = []
        if hit:
            matches.append(
                Match(
                    confidence=0.97,
                    source="MOCK_SANCTIONS_LIST",
                    match_type="NAME",
                    details=f"Name matched sanctions pattern: {name}",
                )
            )
        return ScreeningResult(
            hit=hit,
            matches=matches,
            provider=self.PROVIDER_ID,
            screened_at=datetime.now(timezone.utc),
        )


# ── Errors ────────────────────────────────────────────────────────────────────

class IdentityError(Exception):
    def __init__(self, message: str, code: str = "IDENTITY_ERROR"):
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict:
        return {"status": "error", "error_code": self.code, "message": self.message}


class CustomerNotFoundError(IdentityError):
    def __init__(self, customer_id: str):
        super().__init__(f"Customer '{customer_id}' not found.", code="CUSTOMER_NOT_FOUND")


class KYCCaseNotFoundError(IdentityError):
    def __init__(self, case_id: str):
        super().__init__(f"KYC case '{case_id}' not found.", code="KYC_CASE_NOT_FOUND")


class TransactionBlockedError(IdentityError):
    def __init__(self, customer_id: str, risk_level: str, factors: List[str]):
        super().__init__(
            f"Customer '{customer_id}' blocked ({risk_level}): {', '.join(factors)}",
            code="TRANSACTION_BLOCKED",
        )
        self.risk_level = risk_level
        self.factors = factors


# ── Engine ────────────────────────────────────────────────────────────────────

class IdentityEngine:
    """
    Deterministic identity and compliance engine.

    Risk matrix:
      - AML HIT            → PROHIBITED
      - KYC REJECTED       → HIGH
      - KYC PENDING/none   → MEDIUM
      - KYC APPROVED + AML CLEAN → LOW
    """

    def __init__(
        self,
        organization_id: str,
        screening_provider: Optional[ScreeningProvider] = None,
        ledger: Any = None,
    ):
        self.organization_id = organization_id
        self.screening_provider = screening_provider or MockScreeningProvider()
        self.ledger = ledger  # optional LedgerEngine for shared org context

        self._customers: Dict[str, Customer] = {}
        self._kyc_cases: Dict[str, KYCCase] = {}
        self._documents: Dict[str, KYCDocument] = {}
        self._aml_screenings: List[AMLScreening] = []
        self._risk_assessments: Dict[str, RiskAssessment] = {}

    # ── Customers ───────────────────────────────────────────────────────────

    def create_customer(
        self,
        legal_name: str,
        customer_type: CustomerType = CustomerType.INDIVIDUAL,
        email: str = "",
        phone: str = "",
        address: str = "",
        country: str = "",
        metadata: Optional[dict] = None,
    ) -> Customer:
        customer = Customer(
            organization_id=self.organization_id,
            legal_name=legal_name,
            customer_type=customer_type,
            email=email,
            phone=phone,
            address=address,
            country=country,
            metadata=metadata or {},
        )
        self._customers[customer.id] = customer
        return customer

    def get_customer(self, customer_id: str) -> Customer:
        if customer_id not in self._customers:
            raise CustomerNotFoundError(customer_id)
        return self._customers[customer_id]

    def list_customers(self) -> List[Customer]:
        return list(self._customers.values())

    # ── KYC ─────────────────────────────────────────────────────────────────

    def initiate_kyc(
        self, customer_id: str, level: KYCLevel = KYCLevel.L1
    ) -> KYCCase:
        self.get_customer(customer_id)  # ensure exists
        case = KYCCase(customer_id=customer_id, status=KYCStatus.PENDING, level=level)
        self._kyc_cases[case.id] = case
        return case

    def upload_document(
        self,
        kyc_case_id: str,
        doc_type: DocumentType,
        document_number: str,
        file_url: str = "",
    ) -> KYCDocument:
        if kyc_case_id not in self._kyc_cases:
            raise KYCCaseNotFoundError(kyc_case_id)
        doc = KYCDocument(
            kyc_case_id=kyc_case_id,
            document_type=doc_type,
            document_number=document_number,
            file_url=file_url,
        )
        self._documents[doc.id] = doc
        return doc

    def verify_kyc(
        self, kyc_case_id: str, status: KYCStatus, reason: str = ""
    ) -> KYCCase:
        if kyc_case_id not in self._kyc_cases:
            raise KYCCaseNotFoundError(kyc_case_id)
        if status not in (KYCStatus.APPROVED, KYCStatus.REJECTED, KYCStatus.REVIEW):
            raise IdentityError(
                f"Invalid verification status: {status}", code="INVALID_KYC_STATUS"
            )
        case = self._kyc_cases[kyc_case_id]
        case.status = status
        case.reason = reason
        case.updated_at = datetime.now(timezone.utc)
        # Invalidate cached risk so next assess_risk recomputes
        self._risk_assessments.pop(case.customer_id, None)
        return case

    def get_kyc_case(self, kyc_case_id: str) -> KYCCase:
        if kyc_case_id not in self._kyc_cases:
            raise KYCCaseNotFoundError(kyc_case_id)
        return self._kyc_cases[kyc_case_id]

    def list_documents(self, kyc_case_id: str) -> List[KYCDocument]:
        return [d for d in self._documents.values() if d.kyc_case_id == kyc_case_id]

    # ── AML ─────────────────────────────────────────────────────────────────

    def screen_aml(
        self,
        customer_id: str,
        screening_type: ScreeningType = ScreeningType.SANCTIONS,
    ) -> AMLScreening:
        customer = self.get_customer(customer_id)
        result = self.screening_provider.screen(
            customer.legal_name,
            nationality=customer.country or None,
        )
        screening = AMLScreening(
            customer_id=customer_id,
            status=AMLStatus.HIT if result.hit else AMLStatus.CLEAN,
            screening_type=screening_type,
            hit_details=json.dumps(
                [
                    {
                        "confidence": m.confidence,
                        "source": m.source,
                        "match_type": m.match_type,
                        "details": m.details,
                    }
                    for m in result.matches
                ]
            ),
            risk_score=95.0 if result.hit else 5.0,
            provider=result.provider,
            screened_at=result.screened_at,
        )
        self._aml_screenings.append(screening)
        self._risk_assessments.pop(customer_id, None)
        return screening

    def list_screenings(self, customer_id: str) -> List[AMLScreening]:
        return [s for s in self._aml_screenings if s.customer_id == customer_id]

    # ── Risk ────────────────────────────────────────────────────────────────

    def assess_risk(self, customer_id: str) -> RiskAssessment:
        self.get_customer(customer_id)

        latest_aml = next(
            (s for s in reversed(self._aml_screenings) if s.customer_id == customer_id),
            None,
        )
        latest_kyc = next(
            (c for c in reversed(list(self._kyc_cases.values())) if c.customer_id == customer_id),
            None,
        )

        risk_level = RiskLevel.LOW
        factors: List[str] = []

        if latest_aml and latest_aml.status == AMLStatus.HIT:
            risk_level = RiskLevel.PROHIBITED
            factors.append("AML/Sanctions Hit")

        if latest_kyc is None or latest_kyc.status == KYCStatus.PENDING:
            if risk_level != RiskLevel.PROHIBITED:
                risk_level = RiskLevel.MEDIUM
            factors.append("KYC Pending")
        elif latest_kyc.status == KYCStatus.REJECTED:
            if risk_level != RiskLevel.PROHIBITED:
                risk_level = RiskLevel.HIGH
            factors.append("KYC Rejected")
        elif latest_kyc.status == KYCStatus.REVIEW:
            if risk_level not in (RiskLevel.PROHIBITED, RiskLevel.HIGH):
                risk_level = RiskLevel.MEDIUM
            factors.append("KYC Manual Review")
        elif latest_kyc.status == KYCStatus.APPROVED:
            if risk_level == RiskLevel.LOW and not factors:
                factors.append("KYC Approved")
            if latest_aml and latest_aml.status == AMLStatus.CLEAN:
                if "KYC Approved" not in factors:
                    factors.append("KYC Approved")
                factors.append("AML Clean")

        assessment = RiskAssessment(
            customer_id=customer_id,
            risk_level=risk_level,
            risk_factors=factors,
        )
        self._risk_assessments[customer_id] = assessment
        return assessment

    def can_transact(self, customer_id: str) -> bool:
        """True if customer is not PROHIBITED and not HIGH risk."""
        assessment = self.assess_risk(customer_id)
        return assessment.risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM)

    def assert_can_transact(self, customer_id: str) -> RiskAssessment:
        """Raise TransactionBlockedError if customer cannot transact."""
        assessment = self.assess_risk(customer_id)
        if assessment.risk_level in (RiskLevel.PROHIBITED, RiskLevel.HIGH):
            raise TransactionBlockedError(
                customer_id,
                assessment.risk_level.value,
                assessment.risk_factors,
            )
        return assessment
