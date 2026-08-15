import unittest
import sqlite3
from vaulteq.ledger import LedgerEngine, PostRequest, JournalLineInput, Direction, AccountType

class TestAuditChainIntegrity(unittest.TestCase):
    def setUp(self):
        self.ledger = LedgerEngine(":memory:")
        self.org_id = self.ledger.create_organization("Audit Corp")
        self.ledger.create_account(self.org_id, "1001", "Cash", AccountType.ASSET, Direction.DEBIT)
        self.ledger.create_account(self.org_id, "4000", "Revenue", AccountType.REVENUE, Direction.CREDIT)

    def test_audit_chain_valid_initially(self):
        req = PostRequest(
            organization_id=self.org_id,
            idempotency_key="audit-1",
            lines=[
                JournalLineInput(account_code="1001", direction=Direction.DEBIT, amount_minor=1000, currency="USD"),
                JournalLineInput(account_code="4000", direction=Direction.CREDIT, amount_minor=1000, currency="USD"),
            ]
        )
        self.ledger.post(req)
        self.assertTrue(self.ledger.verify_audit_chain(self.org_id))

    def test_tamper_detection_fails_chain(self):
        req = PostRequest(
            organization_id=self.org_id,
            idempotency_key="audit-2",
            lines=[
                JournalLineInput(account_code="1001", direction=Direction.DEBIT, amount_minor=2000, currency="USD"),
                JournalLineInput(account_code="4000", direction=Direction.CREDIT, amount_minor=2000, currency="USD"),
            ]
        )
        self.ledger.post(req)
        self.assertTrue(self.ledger.verify_audit_chain(self.org_id))

        # Tamper with db directly
        with self.ledger._get_conn() as conn:
            conn.execute("UPDATE audit_event SET payload_sha256 = 'tampered_hash_value' WHERE organization_id = ?", (self.org_id,))

        self.assertFalse(self.ledger.verify_audit_chain(self.org_id))

if __name__ == "__main__":
    unittest.main()
