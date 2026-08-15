import os
import shutil
import tempfile
import unittest

from vaulteq.ledger import LedgerEngine, PostRequest, JournalLineInput, Direction, AccountType

class TestBackupRestore(unittest.TestCase):
    def test_backup_restore_invariant_preservation(self):
        """Test live database backup, restoration, and complete invariant validation."""
        src_fd, src_path = tempfile.mkstemp(suffix=".db")
        os.close(src_fd)
        
        dst_fd, dst_path = tempfile.mkstemp(suffix=".db")
        os.close(dst_fd)

        try:
            # 1. Populate source engine
            engine_src = LedgerEngine(src_path)
            org_id = engine_src.create_organization("Backup Corp", "USD")
            engine_src.create_account(org_id, "1001", "Cash", AccountType.ASSET, Direction.DEBIT)
            engine_src.create_account(org_id, "4000", "Revenue", AccountType.REVENUE, Direction.CREDIT)

            # Post some journals
            res1 = engine_src.post(PostRequest(
                organization_id=org_id,
                idempotency_key="bk_1",
                lines=[
                    JournalLineInput("1001", Direction.DEBIT, 10000, "USD"),
                    JournalLineInput("4000", Direction.CREDIT, 10000, "USD")
                ]
            ))
            
            # Close period
            engine_src.close_period(org_id, "2026-08")

            # Get source state for comparison
            src_tb = engine_src.get_trial_balance(org_id)
            src_audit = engine_src.get_audit_trail(org_id)
            src_entries = engine_src.list_journal_entries(org_id)
            engine_src.close()

            # 2. Perform file backup (SQLite safe file copy or online backup)
            shutil.copyfile(src_path, dst_path)

            # 3. Instantiate restored engine from backup
            engine_dst = LedgerEngine(dst_path)

            # 4. Verify all invariants and state match identically
            dst_tb = engine_dst.get_trial_balance(org_id)
            dst_audit = engine_dst.get_audit_trail(org_id)
            dst_entries = engine_dst.list_journal_entries(org_id)

            self.assertEqual(src_tb, dst_tb)
            self.assertEqual(len(src_entries), len(dst_entries))
            self.assertEqual(src_entries[0]["id"], dst_entries[0]["id"])
            
            # Audit chain must remain valid on restored DB
            self.assertTrue(engine_dst.verify_audit_chain(org_id))
            self.assertEqual(len(src_audit), len(dst_audit))
            self.assertEqual(src_audit[0]["payload_sha256"], dst_audit[0]["payload_sha256"])

            # Verify idempotency record persists (retrying bk_1 should return cached response)
            cached_res = engine_dst.post(PostRequest(
                organization_id=org_id,
                idempotency_key="bk_1",
                lines=[
                    JournalLineInput("1001", Direction.DEBIT, 10000, "USD"),
                    JournalLineInput("4000", Direction.CREDIT, 10000, "USD")
                ]
            ))
            self.assertTrue(cached_res.cached)
            self.assertEqual(cached_res.journal_entry_id, res1.journal_entry_id)

            engine_dst.close()

        finally:
            if os.path.exists(src_path):
                os.remove(src_path)
            if os.path.exists(dst_path):
                os.remove(dst_path)

if __name__ == "__main__":
    unittest.main()
