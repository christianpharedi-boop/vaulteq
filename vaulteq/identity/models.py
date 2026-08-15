"""
VaultEq — Identity Domain Models
================================
KYC/KYB workflow, AML screening, sanctions, risk scoring.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class CustomerType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    BUSINESS = "BUSINESS"


class KYCStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVIEW = "REVIEW"
    EXPIRED = "EXPIRED"


class KYCLevel(str, Enum):
    L1 = "L1"  # Basic
    L2 = "L2"  # ID verification
    L3 = "L3"  # Enhanced due diligence


class DocumentType(str, Enum):
    PASSPORT = "PASSPORT"
    DRIVERS_LICENSE = "DRIVERS_LICENSE"
    NATIONAL_ID = "NATIONAL_ID"
    UTILITY_BILL = "UTILITY_BILL"
    BANK_STATEMENT = "BANK_STATEMENT"
    CERTIFICATE_OF_INCORPORATION = "CERTIFICATE_OF_INCORPORATION"
    ARTICLES_OF_ASSOCIATION = "ARTICLES_OF_ASSOCIATION"
    UBO_DECLARATION = "UBO_DECLARATION"


class DocumentStatus(str, Enum):
    UPLOADED = "UPLOADED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class AMLStatus(str, Enum):
    CLEAN = "CLEAN"
    HIT = "HIT"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class ScreeningType(str, Enum):
    PEP = "PEP"
    SANCTIONS = "SANCTIONS"
    ADVERSE_MEDIA = "ADVERSE_MEDIA"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    PROHIBITED = "PROHIBITED"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Customer:
    organization_id: str
    legal_name: str
    customer_type: CustomerType = CustomerType.INDIVIDUAL
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    email: str = ""
    phone: str = ""
    address: str = ""
    country: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "customer_type": self.customer_type.value,
            "legal_name": self.legal_name,
            "email": self.email,
            "phone": self.phone,
            "address": self.address,
            "country": self.country,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class KYCCase:
    customer_id: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: KYCStatus = KYCStatus.PENDING
    level: KYCLevel = KYCLevel.L1
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "status": self.status.value,
            "level": self.level.value,
            "reason": self.reason,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class KYCDocument:
    kyc_case_id: str
    document_type: DocumentType
    document_number: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    file_url: str = ""
    status: DocumentStatus = DocumentStatus.UPLOADED
    created_at: datetime = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kyc_case_id": self.kyc_case_id,
            "document_type": self.document_type.value,
            "document_number": self.document_number,
            "file_url": self.file_url,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class AMLScreening:
    customer_id: str
    status: AMLStatus
    screening_type: ScreeningType = ScreeningType.SANCTIONS
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    hit_details: str = "[]"
    risk_score: float = 0.0
    provider: str = ""
    screened_at: datetime = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "status": self.status.value,
            "screening_type": self.screening_type.value,
            "hit_details": self.hit_details,
            "risk_score": self.risk_score,
            "provider": self.provider,
            "screened_at": self.screened_at.isoformat(),
        }


@dataclass
class RiskAssessment:
    customer_id: str
    risk_level: RiskLevel
    risk_factors: List[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    assessed_at: datetime = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "risk_level": self.risk_level.value,
            "risk_factors": self.risk_factors,
            "assessed_at": self.assessed_at.isoformat(),
        }
