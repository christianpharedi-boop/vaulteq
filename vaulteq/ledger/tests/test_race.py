"""
VaultEq — Ledger Concurrency Race Tests
========================================
Verifies that LedgerEngine handles concurrent posts correctly using SQLite's locking.
"""

import sys
import os
import threading
import tempfile
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))
from vaulteq.ledger import LedgerEngine, PostRequest, JournalLineInput, Direction, AccountType

class TestLedgerRace(unittest.TestCase):

    def setUp(self):
        # Use a temporary file for the race test to avoid disk I/O issues in sandboxes
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        
        self.engine = LedgerEngine(self.db_path)
        self.org_id = self.engine.create_organization("Race Org", "USD")
        self.engine.create_account(self.org_id, "1001", "Cash", AccountType.ASSET, Direction.DEBIT)
        self.engine.create_account(self.org_id, "4000", "Revenue", AccountType.REVENUE, Direction.CREDIT)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_concurrent_posts(self):
        num_threads = 10
        posts_per_thread = 5
        barrier = threading.Barrier(num_threads)
        results = []
        errors = []

        def worker(thread_id):
            # Each thread gets its own engine instance (separate connection)
            thread_engine = LedgerEngine(self.db_path)
            barrier.wait()
            for i in range(posts_per_thread):
                try:
                    res = thread_engine.post(PostRequest(
                        organization_id=self.org_id,
                        idempotency_key=f"thread_{thread_id}_post_{i}",
                        lines=[
                            JournalLineInput("1001", Direction.DEBIT, 100, "USD"),
                            JournalLineInput("4000", Direction.CREDIT, 100, "USD")
                        ]
                    ))
                    results.append(res)
                except Exception as e:
                    errors.append(e)
            thread_engine.close()

        threads = []
        for i in range(num_threads):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Total posts should be num_threads * posts_per_thread
        self.assertEqual(len(results), num_threads * posts_per_thread)
        self.assertEqual(len(errors), 0, f"Encountered errors during concurrent posts: {errors}")

        # Verify final balance
        balance = self.engine.get_account_balance(self.org_id, "1001")
        self.assertEqual(balance, num_threads * posts_per_thread * 100)

if __name__ == "__main__":
    unittest.main()
