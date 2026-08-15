import random
import unittest
from vaulteq.ledger import LedgerEngine, PostRequest, JournalLineInput, Direction, AccountType, VaultEqError

class TestSeededAdversarialSimulation(unittest.TestCase):
    def test_seeded_property_simulation(self):
        """Run 1,000 randomized operations with a fixed seed and assert invariants continuously."""
        seed = 482193
        random.seed(seed)

        ledger = LedgerEngine(":memory:")
        org_id = ledger.create_organization("Seeded Adv Org")
        ledger.create_account(org_id, "1001", "Cash", AccountType.ASSET, Direction.DEBIT)
        ledger.create_account(org_id, "2000", "Liability", AccountType.LIABILITY, Direction.CREDIT)
        ledger.create_account(org_id, "4000", "Revenue", AccountType.REVENUE, Direction.CREDIT)
        ledger.create_account(org_id, "5000", "Expense", AccountType.EXPENSE, Direction.DEBIT)

        posted_entry_ids = []

        for op_idx in range(1, 1001):
            choice = random.choice(["valid_post", "unbalanced_post", "duplicate_post", "reversal"])
            
            if choice == "valid_post":
                amt = random.randint(10, 50000)
                try:
                    resp = ledger.post(PostRequest(
                        organization_id=org_id,
                        idempotency_key=f"op_{op_idx}",
                        lines=[
                            JournalLineInput("1001", Direction.DEBIT, amt, "USD"),
                            JournalLineInput("4000", Direction.CREDIT, amt, "USD")
                        ]
                    ))
                    if resp.status == "posted":
                        posted_entry_ids.append(resp.journal_entry_id)
                except VaultEqError:
                    pass

            elif choice == "unbalanced_post":
                debit_amt = random.randint(100, 10000)
                credit_amt = debit_amt + random.choice([-50, 50, 100])
                if credit_amt <= 0:
                    credit_amt = 100
                with self.assertRaises(VaultEqError) as ctx:
                    ledger.post(PostRequest(
                        organization_id=org_id,
                        idempotency_key=f"op_{op_idx}",
                        lines=[
                            JournalLineInput("1001", Direction.DEBIT, debit_amt, "USD"),
                            JournalLineInput("4000", Direction.CREDIT, credit_amt, "USD")
                        ]
                    ))
                self.assertEqual(ctx.exception.code, "UNBALANCED_JOURNAL")

            elif choice == "duplicate_post" and posted_entry_ids:
                # Retry an existing idempotency key
                key_to_retry = f"op_{op_idx - 1}" # approximate
                try:
                    ledger.post(PostRequest(
                        organization_id=org_id,
                        idempotency_key=key_to_retry,
                        lines=[
                            JournalLineInput("1001", Direction.DEBIT, 100, "USD"),
                            JournalLineInput("4000", Direction.CREDIT, 100, "USD")
                        ]
                    ))
                except VaultEqError as e:
                    self.assertEqual(e.code, "DUPLICATE_IDEMPOTENCY_KEY")

            elif choice == "reversal" and posted_entry_ids:
                target_id = random.choice(posted_entry_ids)
                try:
                    ledger.reverse(org_id, target_id)
                except VaultEqError:
                    pass

        # Continuous invariant check after 1,000 operations
        tb = ledger.get_trial_balance(org_id)
        self.assertEqual(sum(tb.values()), 0)
        self.assertTrue(ledger.verify_audit_chain(org_id))

if __name__ == "__main__":
    unittest.main()
