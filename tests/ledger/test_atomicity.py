import unittest
from vaulteq.ledger import LedgerEngine, PostRequest, JournalLineInput, Direction, AccountType, VaultEqError

class TestLedgerAtomicity(unittest.TestCase):
    def setUp(self):
        self.ledger = LedgerEngine(":memory:")
        self.org_id = self.ledger.create_organization("Atomicity Corp")
        self.ledger.create_account(self.org_id, "1001", "Cash", AccountType.ASSET, Direction.DEBIT)

    def test_failed_post_leaves_no_journal_entry(self):
        # Posting to non-existent account 9999 should fail atomically
        req = PostRequest(
            organization_id=self.org_id,
            idempotency_key="atom-1",
            lines=[
                JournalLineInput(account_code="1001", direction=Direction.DEBIT, amount_minor=1000, currency="USD"),
                JournalLineInput(account_code="9999", direction=Direction.CREDIT, amount_minor=1000, currency="USD"),
            ]
        )
        with self.assertRaises(VaultEqError):
            self.ledger.post(req)

        entries = self.ledger.list_journal_entries(self.org_id)
        self.assertEqual(len(entries), 0)

if __name__ == "__main__":
    unittest.main()
