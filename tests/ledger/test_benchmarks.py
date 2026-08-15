import time
import unittest
import tempfile
import os

from vaulteq.ledger import LedgerEngine, PostRequest, JournalLineInput, Direction, AccountType

class TestPerformanceBenchmarks(unittest.TestCase):
    def test_performance_scaling_boundaries(self):
        """Benchmark posting 1,000 journals and verifying trial balance / audit chain."""
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)
        
        try:
            engine = LedgerEngine(db_path)
            org_id = engine.create_organization("Bench Org", "USD")
            engine.create_account(org_id, "1001", "Cash", AccountType.ASSET, Direction.DEBIT)
            engine.create_account(org_id, "4000", "Revenue", AccountType.REVENUE, Direction.CREDIT)

            start_time = time.time()
            for i in range(1000):
                engine.post(PostRequest(
                    organization_id=org_id,
                    idempotency_key=f"bench_{i}",
                    lines=[
                        JournalLineInput("1001", Direction.DEBIT, 100, "USD"),
                        JournalLineInput("4000", Direction.CREDIT, 100, "USD")
                    ]
                ))
            duration = time.time() - start_time
            print(f"\n[BENCHMARK] Posted 1,000 journals in {duration:.4f} seconds ({1000/duration:.2f} TPS)")

            # Benchmark trial balance calculation
            tb_start = time.time()
            tb = engine.get_trial_balance(org_id)
            tb_duration = time.time() - tb_start
            self.assertEqual(sum(tb.values()), 0)
            print(f"[BENCHMARK] Trial balance computed in {tb_duration:.4f} seconds")

            # Benchmark audit chain verification
            audit_start = time.time()
            valid = engine.verify_audit_chain(org_id)
            audit_duration = time.time() - audit_start
            self.assertTrue(valid)
            print(f"[BENCHMARK] Audit chain verified in {audit_duration:.4f} seconds")

        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

if __name__ == "__main__":
    unittest.main()
