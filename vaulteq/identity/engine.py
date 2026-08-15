"""
VaultEq — Identity & Compliance Engine
======================================
Deterministic KYC/AML/risk computation for agents with full SQLite durability.

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
    DocumentStatus,
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
    """
    Deterministic mock screening provider.
    - Names containing 'SANCTIONED', 'BLOCKED', or 'OFAC' hit Sanctions (PROHIBITED).
    - Names containing 'SUSPICIOUS' or 'SCAM' hit Adverse Media (HIGH).
    - Names containing 'POLITICIAN' hit PEP (MEDIUM).
    """

    PROVIDER_ID = "mock_screening_v1"

    def screen(
        self,
        name: str,
        dob: Optional[str] = None,
        nationality: Optional[str] = None,
    ) -> ScreeningResult:
        upper = name.upper()
        matches: List[Match] = []
        
        # 1. Sanctions Check
        if any(tok in upper for tok in ("SANCTIONED", "BLOCKED", "OFAC")):
            matches.append(Match(
                confidence=0.99,
                source="MOCK_SANCTIONS_LIST",
                match_type="SANCTIONS",
                details=f"Exact match found in OFAC SDN list for: {name}"
            ))
            
        # 2. Adverse Media Check
        if any(tok in upper for tok in ("SUSPICIOUS", "SCAM", "FRAUD")):
            matches.append(Match(
                confidence=0.85,
                source="MOCK_NEWS_SEARCH",
                match_type="ADVERSE_MEDIA",
                details=f"Negative news reports linked to financial crime for: {name}"
            ))
            
        # 3. PEP Check
        if "POLITICIAN" in upper:
            matches.append(Match(
                confidence=0.95,
                source="MOCK_PEP_LIST",
                match_type="PEP",
                details=f"Identified as a Politically Exposed Person: {name}"
            ))

        return ScreeningResult(
            hit=len(matches) > 0,
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
    Deterministic identity and compliance engine backed by SQLite durability.

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
        from vaulteq.ledger import LedgerEngine
        self.ledger = ledger or LedgerEngine(":memory:")

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
        with self.ledger._get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO identity_customer 
                (id, organization_id, legal_name, customer_type, email, phone, address, country, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    customer.id,
                    customer.organization_id,
                    customer.legal_name,
                    customer.customer_type.value,
                    customer.email,
                    customer.phone,
                    customer.address,
                    customer.country,
                    json.dumps(customer.metadata),
                    customer.created_at.isoformat(),
                ),
            )
        return customer

    def get_customer(self, customer_id: str) -> Customer:
        with self.ledger._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM identity_customer WHERE id = ? AND organization_id = ?",
                (customer_id, self.organization_id),
            ).fetchone()
            if not row:
                raise CustomerNotFoundError(customer_id)
            return Customer(
                organization_id=row["organization_id"],
                legal_name=row["legal_name"],
                customer_type=CustomerType(row["customer_type"]),
                id=row["id"],
                email=row["email"] or "",
                phone=row["phone"] or "",
                address=row["address"] or "",
                country=row["country"] or "",
                metadata=json.loads(row["metadata"] or "{}"),
                created_at=datetime.fromisoformat(row["created_at"]),
            )

    def list_customers(self) -> List[Customer]:
        with self.ledger._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM identity_customer WHERE organization_id = ?",
                (self.organization_id,),
            ).fetchall()
            return [
                Customer(
                    organization_id=r["organization_id"],
                    legal_name=r["legal_name"],
                    customer_type=CustomerType(r["customer_type"]),
                    id=r["id"],
                    email=r["email"] or "",
                    phone=r["phone"] or "",
                    address=r["address"] or "",
                    country=r["country"] or "",
                    metadata=json.loads(r["metadata"] or "{}"),
                    created_at=datetime.fromisoformat(r["created_at"]),
                )
                for r in rows
            ]

    # ── KYC ─────────────────────────────────────────────────────────────────

    def initiate_kyc(
        self, customer_id: str, level: KYCLevel = KYCLevel.L1
    ) -> KYCCase:
        self.get_customer(customer_id)  # ensure exists
        case = KYCCase(customer_id=customer_id, status=KYCStatus.PENDING, level=level)
        with self.ledger._get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO identity_kyc_case (id, customer_id, status, level, reason, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case.id,
                    case.customer_id,
                    case.status.value,
                    case.level.value,
                    case.reason,
                    case.created_at.isoformat(),
                    case.updated_at.isoformat(),
                ),
            )
        return case

    def upload_document(
        self,
        kyc_case_id: str,
        doc_type: DocumentType,
        document_number: str,
        file_url: str = "",
    ) -> KYCDocument:
        self.get_kyc_case(kyc_case_id)
        doc = KYCDocument(
            kyc_case_id=kyc_case_id,
            document_type=doc_type,
            document_number=document_number,
            file_url=file_url,
        )
        with self.ledger._get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO identity_document (id, case_id, document_type, document_number, status, uploaded_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    doc.id,
                    doc.kyc_case_id,
                    doc.document_type.value,
                    doc.document_number,
                    doc.status.value,
                    doc.created_at.isoformat(),
                ),
            )
        return doc

    def verify_kyc(
        self, kyc_case_id: str, status: KYCStatus, reason: str = ""
    ) -> KYCCase:
        case = self.get_kyc_case(kyc_case_id)
        if status not in (KYCStatus.APPROVED, KYCStatus.REJECTED, KYCStatus.REVIEW):
            raise IdentityError(
                f"Invalid verification status: {status}", code="INVALID_KYC_STATUS"
            )
        old_status = case.status
        case.status = status
        case.reason = reason
        case.updated_at = datetime.now(timezone.utc)
        
        with self.ledger._get_conn() as conn:
            conn.execute(
                "UPDATE identity_kyc_case SET status = ?, reason = ?, updated_at = ? WHERE id = ?",
                (status.value, reason, case.updated_at.isoformat(), kyc_case_id),
            )

        # Audit: Record KYC decision on Ledger
        if self.ledger:
            self.ledger.append_audit_event(
                organization_id=self.organization_id,
                entity_type="kyc_case",
                entity_id=kyc_case_id,
                action="VERIFY",
                payload={
                    "customer_id": case.customer_id,
                    "old_status": old_status.value,
                    "new_status": status.value,
                    "reason": reason,
                },
            )

        return case

    def get_kyc_case(self, kyc_case_id: str) -> KYCCase:
        with self.ledger._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM identity_kyc_case WHERE id = ?", (kyc_case_id,)
            ).fetchone()
            if not row:
                raise KYCCaseNotFoundError(kyc_case_id)
            return KYCCase(
                customer_id=row["customer_id"],
                id=row["id"],
                status=KYCStatus(row["status"]),
                level=KYCLevel(row["level"]),
                reason=row["reason"] or "",
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )

    def list_documents(self, kyc_case_id: str) -> List[KYCDocument]:
        with self.ledger._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM identity_document WHERE case_id = ?", (kyc_case_id,)
            ).fetchall()
            return [
                KYCDocument(
                    kyc_case_id=r["case_id"],
                    document_type=DocumentType(r["document_type"]),
                    document_number=r["document_number"],
                    id=r["id"],
                    status=DocumentStatus(r["status"]),
                    created_at=datetime.fromisoformat(r["uploaded_at"]),
                )
                for r in rows
            ]

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
        with self.ledger._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO identity_screening (id, customer_id, provider, hit, matches, screened_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    screening.id,
                    screening.customer_id,
                    screening.provider,
                    1 if result.hit else 0,
                    screening.hit_details,
                    screening.screened_at.isoformat(),
                ),
            )
        return screening

    def list_screenings(self, customer_id: str) -> List[AMLScreening]:
        with self.ledger._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM identity_screening WHERE customer_id = ?", (customer_id,)
            ).fetchall()
            return [
                AMLScreening(
                    customer_id=r["customer_id"],
                    status=AMLStatus.HIT if r["hit"] else AMLStatus.CLEAN,
                    id=r["id"],
                    hit_details=r["matches"],
                    provider=r["provider"],
                    screened_at=datetime.fromisoformat(r["screened_at"]),
                )
                for r in rows
            ]

    # ── Risk ────────────────────────────────────────────────────────────────

    def assess_risk(self, customer_id: str) -> RiskAssessment:
        """
        Deterministic Risk Matrix Aggregator.
        Evaluates KYC level, status, and AML hit types to produce a final RiskLevel.
        """
        self.get_customer(customer_id)

        screenings = self.list_screenings(customer_id)
        latest_aml = screenings[-1] if screenings else None

        with self.ledger._get_conn() as conn:
            kyc_rows = conn.execute(
                "SELECT * FROM identity_kyc_case WHERE customer_id = ?", (customer_id,)
            ).fetchall()
            latest_kyc = None
            if kyc_rows:
                r = kyc_rows[-1]
                latest_kyc = KYCCase(
                    customer_id=r["customer_id"],
                    id=r["id"],
                    status=KYCStatus(r["status"]),
                    level=KYCLevel(r["level"]),
                )

        # Risk weights for comparison since str Enums don't support order
        weights = {
            RiskLevel.LOW: 0,
            RiskLevel.MEDIUM: 1,
            RiskLevel.HIGH: 2,
            RiskLevel.PROHIBITED: 3,
        }

        risk_level = RiskLevel.LOW
        factors: List[str] = []

        # 1. Evaluate AML Screenings (Highest Precedence)
        if latest_aml and latest_aml.status == AMLStatus.HIT:
            hit_types = set()
            try:
                details = json.loads(latest_aml.hit_details)
                for match in details:
                    hit_types.add(match.get("match_type"))
            except:
                hit_types.add("UNKNOWN")

            if "SANCTIONS" in hit_types:
                risk_level = RiskLevel.PROHIBITED
                factors.append("CRITICAL: Active Sanctions Hit")
            elif "ADVERSE_MEDIA" in hit_types:
                risk_level = RiskLevel.HIGH
                factors.append("HIGH: Adverse Media/Financial Crime Link")
            elif "PEP" in hit_types:
                risk_level = RiskLevel.MEDIUM
                factors.append("MEDIUM: Politically Exposed Person (PEP)")
            else:
                risk_level = RiskLevel.HIGH
                factors.append("HIGH: AML Screening Hit")

        # 2. Evaluate KYC Status (Additive Precedence)
        if latest_kyc is None:
            if weights[risk_level] < weights[RiskLevel.MEDIUM]:
                risk_level = RiskLevel.MEDIUM
            factors.append("KYC: No active case")
        elif latest_kyc.status == KYCStatus.PENDING:
            if weights[risk_level] < weights[RiskLevel.MEDIUM]:
                risk_level = RiskLevel.MEDIUM
            factors.append("KYC: Verification pending")
        elif latest_kyc.status == KYCStatus.REJECTED:
            if weights[risk_level] < weights[RiskLevel.HIGH]:
                risk_level = RiskLevel.HIGH
            factors.append("KYC: Case rejected")
        elif latest_kyc.status == KYCStatus.REVIEW:
            if weights[risk_level] < weights[RiskLevel.MEDIUM]:
                risk_level = RiskLevel.MEDIUM
            factors.append("KYC: Manual review required")
        elif latest_kyc.status == KYCStatus.APPROVED:
            if latest_kyc.level == KYCLevel.L3 and risk_level == RiskLevel.LOW:
                factors.append("KYC: L3 Enhanced Due Diligence complete")
            else:
                factors.append(f"KYC: {latest_kyc.level.value} Approved")

        # 3. Final Aggregation
        if not factors and risk_level == RiskLevel.LOW:
            factors.append("Compliance: Standard monitoring")

        assessment = RiskAssessment(
            customer_id=customer_id,
            risk_level=risk_level,
            risk_factors=factors,
        )
        
        # Audit: Record Risk Assessment on Ledger
        if self.ledger:
            self.ledger.append_audit_event(
                organization_id=self.organization_id,
                entity_type="risk_assessment",
                entity_id=assessment.id,
                action="ASSESS",
                payload={
                    "customer_id": customer_id,
                    "risk_level": risk_level.value,
                    "factors": factors,
                },
            )

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
