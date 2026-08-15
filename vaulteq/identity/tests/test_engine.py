"""VaultEq Identity — engine tests."""

from __future__ import annotations

import pytest

from vaulteq.identity import (
    CustomerNotFoundError,
    CustomerType,
    DocumentType,
    IdentityEngine,
    KYCCaseNotFoundError,
    KYCLevel,
    KYCStatus,
    MockScreeningProvider,
    RiskLevel,
    TransactionBlockedError,
)


@pytest.fixture
def eng():
    return IdentityEngine(organization_id="id_org_1")


def test_create_and_get_customer(eng):
    c = eng.create_customer("Alice Smith", email="alice@example.com")
    assert c.legal_name == "Alice Smith"
    assert eng.get_customer(c.id).email == "alice@example.com"


def test_customer_not_found(eng):
    with pytest.raises(CustomerNotFoundError):
        eng.get_customer("missing")


def test_kyc_happy_path(eng):
    c = eng.create_customer("Bob Jones")
    case = eng.initiate_kyc(c.id, level=KYCLevel.L2)
    assert case.status == KYCStatus.PENDING
    doc = eng.upload_document(case.id, DocumentType.PASSPORT, "P123456")
    assert doc.document_number == "P123456"
    verified = eng.verify_kyc(case.id, KYCStatus.APPROVED, reason="All clear")
    assert verified.status == KYCStatus.APPROVED


def test_kyc_case_not_found(eng):
    with pytest.raises(KYCCaseNotFoundError):
        eng.verify_kyc("nope", KYCStatus.APPROVED)


def test_aml_clean(eng):
    c = eng.create_customer("Clean Citizen")
    s = eng.screen_aml(c.id)
    assert s.status.value == "CLEAN"
    assert s.risk_score < 50


def test_aml_hit_on_sanctioned_name(eng):
    c = eng.create_customer("John SANCTIONED Doe")
    s = eng.screen_aml(c.id)
    assert s.status.value == "HIT"
    assert s.risk_score >= 90


def test_risk_prohibited_on_aml_hit(eng):
    c = eng.create_customer("BLOCKED Entity")
    eng.screen_aml(c.id)
    risk = eng.assess_risk(c.id)
    assert risk.risk_level == RiskLevel.PROHIBITED
    assert eng.can_transact(c.id) is False


def test_risk_low_when_approved_and_clean(eng):
    c = eng.create_customer("Good Actor")
    case = eng.initiate_kyc(c.id)
    eng.verify_kyc(case.id, KYCStatus.APPROVED)
    eng.screen_aml(c.id)
    risk = eng.assess_risk(c.id)
    assert risk.risk_level == RiskLevel.LOW
    assert eng.can_transact(c.id) is True


def test_risk_medium_when_kyc_pending(eng):
    c = eng.create_customer("Pending Person")
    eng.initiate_kyc(c.id)
    eng.screen_aml(c.id)  # clean
    risk = eng.assess_risk(c.id)
    assert risk.risk_level == RiskLevel.MEDIUM


def test_risk_high_when_kyc_rejected(eng):
    c = eng.create_customer("Rejected Person")
    case = eng.initiate_kyc(c.id)
    eng.verify_kyc(case.id, KYCStatus.REJECTED, reason="Fake docs")
    eng.screen_aml(c.id)
    risk = eng.assess_risk(c.id)
    assert risk.risk_level == RiskLevel.HIGH
    assert eng.can_transact(c.id) is False


def test_assert_can_transact_blocks_prohibited(eng):
    c = eng.create_customer("OFAC Listed Co")
    eng.screen_aml(c.id)
    with pytest.raises(TransactionBlockedError) as ei:
        eng.assert_can_transact(c.id)
    assert ei.value.code == "TRANSACTION_BLOCKED"


def test_assert_can_transact_allows_low(eng):
    c = eng.create_customer("Allowed User")
    case = eng.initiate_kyc(c.id)
    eng.verify_kyc(case.id, KYCStatus.APPROVED)
    eng.screen_aml(c.id)
    assessment = eng.assert_can_transact(c.id)
    assert assessment.risk_level == RiskLevel.LOW


def test_list_customers_and_documents(eng):
    c = eng.create_customer("Doc User", customer_type=CustomerType.BUSINESS)
    case = eng.initiate_kyc(c.id, KYCLevel.L3)
    eng.upload_document(case.id, DocumentType.CERTIFICATE_OF_INCORPORATION, "INC-1")
    eng.upload_document(case.id, DocumentType.UBO_DECLARATION, "UBO-1")
    assert len(eng.list_customers()) == 1
    assert len(eng.list_documents(case.id)) == 2


def test_custom_screening_provider():
    class AlwaysHit:
        def screen(self, name, dob=None, nationality=None):
            from vaulteq.identity.engine import Match, ScreeningResult
            from datetime import datetime, timezone
            return ScreeningResult(
                hit=True,
                matches=[Match(1.0, "TEST", "NAME", "forced")],
                provider="always_hit",
                screened_at=datetime.now(timezone.utc),
            )

    eng = IdentityEngine("org", screening_provider=AlwaysHit())
    c = eng.create_customer("Anyone")
    s = eng.screen_aml(c.id)
    assert s.status.value == "HIT"
    assert s.provider == "always_hit"
