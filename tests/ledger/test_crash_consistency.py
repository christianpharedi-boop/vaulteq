import sqlite3
import tempfile
import os
import unittest

from vaulteq.ledger import LedgerEngine, PostRequest, JournalLineInput, Direction, AccountType, VaultEqError

class TestCrashConsistency(unittest.TestCase):
    def test_interrupted_transaction_rollback(self):
        """Simulate a sudden connection termination / crash during an uncommitted transaction."""
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)

        try:
            engine = LedgerEngine(db_path)
            org_id = engine.create_organization("Crash Org", "USD")
            engine.create_account(org_id, "1001", "Cash", AccountType.ASSET, Direction.DEBIT)
            engine.create_account(org_id, "4000", "Revenue", AccountType.REVENUE, Direction.CREDIT)

            # Manually open a connection, start transaction, insert partial data, and abruptly close without commit
            conn = sqlite3.connect(db_path)
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO journal_entry (id, organization_id, idempotency_key, payload_hash, posted_at) VALUES (?, ?, ?, ?, ?)",
                ("je_orphan", org_id, "orphan_key", "dummy_hash", "2026-08-15T00:00:00Z")
            )
            # Abruptly close connection without commit (simulating process crash)
            conn.close()

            # Re-open engine on the same database file
            engine_recovered = LedgerEngine(db_path)

            # SQLite rollback should have discarded the uncommitted orphan entry
            entries = engine_recovered.list_journal_entries(org_id)
            self.assertEqual(len(entries), 0)

            # Audit chain and trial balance remain pristine
            self.assertTrue(engine_recovered.verify_audit_chain(org_id))
            tb = engine_recovered.get_trial_balance(org_id)
            self.assertEqual(sum(tb.values()), 0)

            engine_recovered.close()

        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

if __name__ == "__main__":
    unittest.main()
