import unittest
from vaulteq.identity.engine import IdentityEngine
from vaulteq.identity.models import (
    KYCStatus, 
    KYCLevel, 
    RiskLevel, 
    AMLStatus,
    DocumentType
)
from vaulteq.ledger import LedgerEngine

class TestIdentityRiskScoringHardening(unittest.TestCase):
    def setUp(self):
        self.org_id = "test_org_identity"
        self.ledger = LedgerEngine(":memory:")
        self.engine = IdentityEngine(self.org_id, ledger=self.ledger)

    def test_sanctions_hit_prohibited(self):
        # Name with 'OFAC' should hit sanctions
        c = self.engine.create_customer("OFAC Bad Actor")
        self.engine.screen_aml(c.id)
        
        risk = self.engine.assess_risk(c.id)
        self.assertEqual(risk.risk_level, RiskLevel.PROHIBITED)
        self.assertIn("CRITICAL: Active Sanctions Hit", risk.risk_factors)
        self.assertFalse(self.engine.can_transact(c.id))

    def test_adverse_media_hit_high(self):
        # Name with 'SCAM' should hit adverse media
        c = self.engine.create_customer("SCAM Artist")
        self.engine.screen_aml(c.id)
        
        risk = self.engine.assess_risk(c.id)
        self.assertEqual(risk.risk_level, RiskLevel.HIGH)
        self.assertIn("HIGH: Adverse Media/Financial Crime Link", risk.risk_factors)
        self.assertFalse(self.engine.can_transact(c.id))

    def test_pep_hit_medium(self):
        # Name with 'POLITICIAN' should hit PEP
        c = self.engine.create_customer("Local Politician")
        self.engine.screen_aml(c.id)
        
        risk = self.engine.assess_risk(c.id)
        self.assertEqual(risk.risk_level, RiskLevel.MEDIUM)
        self.assertIn("MEDIUM: Politically Exposed Person (PEP)", risk.risk_factors)
        # PEP is allowed to transact but monitored (MEDIUM)
        self.assertTrue(self.engine.can_transact(c.id))

    def test_kyc_rejected_high(self):
        c = self.engine.create_customer("Alice")
        case = self.engine.initiate_kyc(c.id)
        self.engine.verify_kyc(case.id, KYCStatus.REJECTED, reason="Fake ID")
        
        risk = self.engine.assess_risk(c.id)
        self.assertEqual(risk.risk_level, RiskLevel.HIGH)
        self.assertIn("KYC: Case rejected", risk.risk_factors)

    def test_kyc_l3_approved_clean_low(self):
        c = self.engine.create_customer("Bob")
        case = self.engine.initiate_kyc(c.id, level=KYCLevel.L3)
        self.engine.verify_kyc(case.id, KYCStatus.APPROVED)
        
        risk = self.engine.assess_risk(c.id)
        self.assertEqual(risk.risk_level, RiskLevel.LOW)
        self.assertIn("KYC: L3 Enhanced Due Diligence complete", risk.risk_factors)

    def test_audit_integration(self):
        c = self.engine.create_customer("Charlie")
        case = self.engine.initiate_kyc(c.id)
        
        # Verify KYC
        self.engine.verify_kyc(case.id, KYCStatus.APPROVED)
        
        # Assess Risk
        self.engine.assess_risk(c.id)
        
        # Check Ledger Audit Trail
        events = self.ledger.get_audit_trail(self.org_id)
        
        # Should have KYC_CASE VERIFY and RISK_ASSESSMENT ASSESS events
        actions = [e["action"] for e in events]
        entity_types = [e["entity_type"] for e in events]
        
        self.assertIn("VERIFY", actions)
        self.assertIn("kyc_case", entity_types)
        self.assertIn("ASSESS", actions)
        self.assertIn("risk_assessment", entity_types)
        
        # Verify chain integrity
        self.assertTrue(self.ledger.verify_audit_chain(self.org_id))

if __name__ == "__main__":
    unittest.main()
