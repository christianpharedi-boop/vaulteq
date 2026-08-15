import sys
import os
import threading
import tempfile
import unittest

from vaulteq.ledger import LedgerEngine, PostRequest, JournalLineInput, Direction, AccountType, VaultEqError

class TestConcurrencyMatrix(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        
        self.engine = LedgerEngine(self.db_path)
        self.org_id = self.engine.create_organization("Matrix Org", "USD")
        self.engine.create_account(self.org_id, "1001", "Cash", AccountType.ASSET, Direction.DEBIT)
        self.engine.create_account(self.org_id, "4000", "Revenue", AccountType.REVENUE, Direction.CREDIT)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_concurrent_conflicting_payloads_same_key(self):
        """Workers attempting same idempotency key with conflicting payloads simultaneously."""
        num_threads = 6
        barrier = threading.Barrier(num_threads)
        errors = []
        successes = []

        def worker(i):
            eng = LedgerEngine(self.db_path)
            barrier.wait()
            try:
                # Half send payload A, half send payload B with same key
                amt = 1000 if i % 2 == 0 else 2000
                res = eng.post(PostRequest(
                    organization_id=self.org_id,
                    idempotency_key="conflict_key_999",
                    lines=[
                        JournalLineInput("1001", Direction.DEBIT, amt, "USD"),
                        JournalLineInput("4000", Direction.CREDIT, amt, "USD")
                    ]
                ))
                successes.append(res)
            except VaultEqError as e:
                errors.append(e)
            eng.close()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # At least one succeeds, others with conflicting payload must raise DUPLICATE_IDEMPOTENCY_KEY
        self.assertGreaterEqual(len(successes), 1)
        for err in errors:
            self.assertEqual(err.code, "DUPLICATE_IDEMPOTENCY_KEY")

        # Audit chain intact
        self.assertTrue(self.engine.verify_audit_chain(self.org_id))

if __name__ == "__main__":
    unittest.main()
