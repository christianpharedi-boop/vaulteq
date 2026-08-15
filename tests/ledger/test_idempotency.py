import unittest
from vaulteq.ledger import LedgerEngine, PostRequest, JournalLineInput, Direction, AccountType, VaultEqError

class TestLedgerIdempotency(unittest.TestCase):
    def setUp(self):
        self.ledger = LedgerEngine(":memory:")
        self.org_id = self.ledger.create_organization("Idempotency Corp")
        self.ledger.create_account(self.org_id, "1001", "Cash", AccountType.ASSET, Direction.DEBIT)
        self.ledger.create_account(self.org_id, "4000", "Revenue", AccountType.REVENUE, Direction.CREDIT)

    def test_same_key_same_payload_returns_cached(self):
        req = PostRequest(
            organization_id=self.org_id,
            idempotency_key="idem-key-1",
            lines=[
                JournalLineInput(account_code="1001", direction=Direction.DEBIT, amount_minor=5000, currency="USD"),
                JournalLineInput(account_code="4000", direction=Direction.CREDIT, amount_minor=5000, currency="USD"),
            ]
        )
        resp1 = self.ledger.post(req)
        self.assertFalse(resp1.cached)

        resp2 = self.ledger.post(req)
        self.assertTrue(resp2.cached)
        self.assertEqual(resp1.journal_entry_id, resp2.journal_entry_id)

    def test_same_key_different_payload_raises_conflict(self):
        req1 = PostRequest(
            organization_id=self.org_id,
            idempotency_key="idem-key-2",
            lines=[
                JournalLineInput(account_code="1001", direction=Direction.DEBIT, amount_minor=5000, currency="USD"),
                JournalLineInput(account_code="4000", direction=Direction.CREDIT, amount_minor=5000, currency="USD"),
            ]
        )
        self.ledger.post(req1)

        req2 = PostRequest(
            organization_id=self.org_id,
            idempotency_key="idem-key-2",
            lines=[
                JournalLineInput(account_code="1001", direction=Direction.DEBIT, amount_minor=6000, currency="USD"),
                JournalLineInput(account_code="4000", direction=Direction.CREDIT, amount_minor=6000, currency="USD"),
            ]
        )
        with self.assertRaises(VaultEqError) as ctx:
            self.ledger.post(req2)
        self.assertEqual(ctx.exception.code, "DUPLICATE_IDEMPOTENCY_KEY")

if __name__ == "__main__":
    unittest.main()
