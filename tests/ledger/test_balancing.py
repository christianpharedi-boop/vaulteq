import unittest
from decimal import Decimal
from vaulteq.ledger import LedgerEngine, PostRequest, JournalLineInput, Direction, AccountType, VaultEqError

class TestLedgerBalancing(unittest.TestCase):
    def setUp(self):
        self.ledger = LedgerEngine(":memory:")
        self.org_id = self.ledger.create_organization("Test Corp")
        self.ledger.create_account(self.org_id, "1001", "Cash", AccountType.ASSET, Direction.DEBIT)
        self.ledger.create_account(self.org_id, "4000", "Revenue", AccountType.REVENUE, Direction.CREDIT)

    def test_balanced_posting_succeeds(self):
        req = PostRequest(
            organization_id=self.org_id,
            idempotency_key="bal-1",
            lines=[
                JournalLineInput(account_code="1001", direction=Direction.DEBIT, amount_minor=10000, currency="USD"),
                JournalLineInput(account_code="4000", direction=Direction.CREDIT, amount_minor=10000, currency="USD"),
            ]
        )
        resp = self.ledger.post(req)
        self.assertEqual(resp.status, "posted")
        tb = self.ledger.get_trial_balance(self.org_id)
        # In trial balance, debits are positive, credits are negative or summed
        # Let's verify sum of trial balance equals zero (accounting invariant: sum of all accounts = 0)
        total = sum(tb.values())
        self.assertEqual(total, 0)

    def test_unbalanced_posting_raises(self):
        req = PostRequest(
            organization_id=self.org_id,
            idempotency_key="bal-2",
            lines=[
                JournalLineInput(account_code="1001", direction=Direction.DEBIT, amount_minor=10000, currency="USD"),
                JournalLineInput(account_code="4000", direction=Direction.CREDIT, amount_minor=9000, currency="USD"),
            ]
        )
        with self.assertRaises(VaultEqError) as ctx:
            self.ledger.post(req)
        self.assertEqual(ctx.exception.code, "UNBALANCED_JOURNAL")

if __name__ == "__main__":
    unittest.main()
