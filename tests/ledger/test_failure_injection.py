import unittest
import sqlite3
from vaulteq.ledger import LedgerEngine, PostRequest, JournalLineInput, Direction, AccountType, VaultEqError

class TestFailureInjection(unittest.TestCase):
    def setUp(self):
        self.ledger = LedgerEngine(":memory:")
        self.org_id = self.ledger.create_organization("Failure Injection Org")
        self.ledger.create_account(self.org_id, "1001", "Cash", AccountType.ASSET, Direction.DEBIT)

    def test_forced_exception_during_post_rolls_back(self):
        """Verify that if an unexpected error occurs during posting, transaction rolls back cleanly."""
        req = PostRequest(
            organization_id=self.org_id,
            idempotency_key="fail-1",
            lines=[
                JournalLineInput(account_code="1001", direction=Direction.DEBIT, amount_minor=1000, currency="USD"),
                # We can trigger a foreign key or constraint error by passing an account code that doesn't exist
                # but let's force a direct db exception by corrupting the connection or passing invalid currency enum if any
                JournalLineInput(account_code="NONEXISTENT", direction=Direction.CREDIT, amount_minor=1000, currency="USD"),
            ]
        )
        
        initial_entries = len(self.ledger.list_journal_entries(self.org_id))
        
        with self.assertRaises(VaultEqError):
            self.ledger.post(req)
            
        # Verify no entries were persisted
        final_entries = len(self.ledger.list_journal_entries(self.org_id))
        self.assertEqual(initial_entries, final_entries)
        
        # Verify trial balance is unaffected
        tb = self.ledger.get_trial_balance(self.org_id)
        self.assertEqual(sum(tb.values()), 0)

if __name__ == "__main__":
    unittest.main()
