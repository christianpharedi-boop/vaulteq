import sys
import os
import threading
import tempfile
import unittest
from decimal import Decimal

from vaulteq.ledger import LedgerEngine, PostRequest, JournalLineInput, Direction, AccountType, VaultEqError

class TestAdvancedConcurrency(unittest.TestCase):

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        
        self.engine = LedgerEngine(self.db_path)
        self.org_id = self.engine.create_organization("Adv Concurrency Org", "USD")
        self.engine.create_account(self.org_id, "1001", "Cash", AccountType.ASSET, Direction.DEBIT)
        self.engine.create_account(self.org_id, "4000", "Revenue", AccountType.REVENUE, Direction.CREDIT)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_concurrent_same_idempotency_key(self):
        """Multiple threads posting the exact same idempotency key simultaneously."""
        num_threads = 10
        barrier = threading.Barrier(num_threads)
        results = []
        errors = []

        def worker():
            thread_engine = LedgerEngine(self.db_path)
            barrier.wait()
            try:
                res = thread_engine.post(PostRequest(
                    organization_id=self.org_id,
                    idempotency_key="shared_key_123",
                    lines=[
                        JournalLineInput("1001", Direction.DEBIT, 1000, "USD"),
                        JournalLineInput("4000", Direction.CREDIT, 1000, "USD")
                    ]
                ))
                results.append(res)
            except Exception as e:
                errors.append(e)
            thread_engine.close()

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads should succeed without deadlocks or constraint violations,
        # returning either fresh or cached responses.
        self.assertEqual(len(results), num_threads)
        self.assertEqual(len(errors), 0)

        # Verify exactly ONE journal entry was created (idempotency guarantee)
        entries = self.engine.list_journal_entries(self.org_id)
        self.assertEqual(len(entries), 1)

        # Verify audit chain integrity remains intact under contention
        self.assertTrue(self.engine.verify_audit_chain(self.org_id))

if __name__ == "__main__":
    unittest.main()
