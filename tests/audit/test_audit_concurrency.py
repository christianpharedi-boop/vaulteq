import sys
import os
import threading
import tempfile
import unittest

from vaulteq.ledger import LedgerEngine, PostRequest, JournalLineInput, Direction, AccountType

class TestAuditConcurrency(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        
        self.engine = LedgerEngine(self.db_path)
        self.org_id = self.engine.create_organization("Audit Stress Org", "USD")
        self.engine.create_account(self.org_id, "1001", "Cash", AccountType.ASSET, Direction.DEBIT)
        self.engine.create_account(self.org_id, "4000", "Revenue", AccountType.REVENUE, Direction.CREDIT)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_high_contention_audit_chain_integrity(self):
        """10 threads concurrently posting 10 entries each, creating 100+ audit events. Verify hash chain."""
        num_threads = 10
        posts_per_thread = 10
        barrier = threading.Barrier(num_threads)

        def worker(t_id):
            eng = LedgerEngine(self.db_path)
            barrier.wait()
            for i in range(posts_per_thread):
                eng.post(PostRequest(
                    organization_id=self.org_id,
                    idempotency_key=f"t_{t_id}_p_{i}",
                    lines=[
                        JournalLineInput("1001", Direction.DEBIT, 100, "USD"),
                        JournalLineInput("4000", Direction.CREDIT, 100, "USD")
                    ]
                ))
            eng.close()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify audit chain integrity across all concurrent writes
        self.assertTrue(self.engine.verify_audit_chain(self.org_id))
        
        # Verify trail length matches expected posts + org creation audit events
        trail = self.engine.get_audit_trail(self.org_id, limit=200)
        self.assertGreaterEqual(len(trail), num_threads * posts_per_thread)

if __name__ == "__main__":
    unittest.main()
