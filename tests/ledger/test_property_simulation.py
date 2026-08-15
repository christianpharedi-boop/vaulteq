import random
import unittest
from vaulteq.ledger import LedgerEngine, PostRequest, JournalLineInput, Direction, AccountType, VaultEqError

class TestPropertySimulation(unittest.TestCase):
    def setUp(self):
        self.ledger = LedgerEngine(":memory:")
        self.org_id = self.ledger.create_organization("Property Sim Org")
        self.ledger.create_account(self.org_id, "1001", "Cash", AccountType.ASSET, Direction.DEBIT)
        self.ledger.create_account(self.org_id, "2000", "Liability", AccountType.LIABILITY, Direction.CREDIT)
        self.ledger.create_account(self.org_id, "4000", "Revenue", AccountType.REVENUE, Direction.CREDIT)
        self.ledger.create_account(self.org_id, "5000", "Expense", AccountType.EXPENSE, Direction.DEBIT)

    def test_randomized_valid_journals_preserve_invariants(self):
        """Generate 50 random valid balanced journals and verify accounting laws hold."""
        for i in range(50):
            amount = random.randint(10, 100000)
            req = PostRequest(
                organization_id=self.org_id,
                idempotency_key=f"rand_valid_{i}",
                lines=[
                    JournalLineInput("1001", Direction.DEBIT, amount, "USD"),
                    JournalLineInput("4000", Direction.CREDIT, amount, "USD"),
                ]
            )
            resp = self.ledger.post(req)
            self.assertEqual(resp.status, "posted")

        # Trial balance should sum to zero across all accounts
        tb = self.ledger.get_trial_balance(self.org_id)
        self.assertEqual(sum(tb.values()), 0)
        
        # Audit chain must be valid
        self.assertTrue(self.ledger.verify_audit_chain(self.org_id))

    def test_randomized_unbalanced_journals_always_rejected(self):
        """Generate 50 random unbalanced journals and verify they are strictly rejected."""
        for i in range(50):
            debit_amt = random.randint(100, 50000)
            credit_amt = debit_amt + random.choice([-10, 10, 50, -100]) # Unbalanced
            if credit_amt <= 0:
                credit_amt = 100
                
            req = PostRequest(
                organization_id=self.org_id,
                idempotency_key=f"rand_invalid_{i}",
                lines=[
                    JournalLineInput("1001", Direction.DEBIT, debit_amt, "USD"),
                    JournalLineInput("4000", Direction.CREDIT, credit_amt, "USD"),
                ]
            )
            with self.assertRaises(VaultEqError) as ctx:
                self.ledger.post(req)
            self.assertEqual(ctx.exception.code, "UNBALANCED_JOURNAL")

if __name__ == "__main__":
    unittest.main()
