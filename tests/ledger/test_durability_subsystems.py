import os
import tempfile
import unittest

from vaulteq.ledger import LedgerEngine
from vaulteq.identity import IdentityEngine
from vaulteq.identity.models import KYCStatus, KYCLevel

class TestSubsystemDurability(unittest.TestCase):
    def test_identity_durability_across_restarts(self):
        """Verify that identity customers and KYC cases survive engine re-instantiation on the same SQLite file."""
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        try:
            # 1. First engine session
            ledger1 = LedgerEngine(db_path)
            org_id = ledger1.create_organization("Durability Org", "USD")
            identity1 = IdentityEngine(org_id, ledger=ledger1)

            customer = identity1.create_customer("Acme Corp")
            case = identity1.initiate_kyc(customer.id, KYCLevel.L2)
            identity1.verify_kyc(case.id, KYCStatus.APPROVED, reason="Verified via registry")

            # Close first session
            ledger1.close()

            # 2. Second engine session (simulating process restart)
            ledger2 = LedgerEngine(db_path)
            identity2 = IdentityEngine(org_id, ledger=ledger2)

            # Retrieve customer and KYC case from SQLite storage
            fetched_customer = identity2.get_customer(customer.id)
            self.assertEqual(fetched_customer.legal_name, "Acme Corp")

            fetched_case = identity2.get_kyc_case(case.id)
            self.assertEqual(fetched_case.status, KYCStatus.APPROVED)
            self.assertEqual(fetched_case.reason, "Verified via registry")

            # Audit chain verification remains valid
            self.assertTrue(ledger2.verify_audit_chain(org_id))

            ledger2.close()

        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

if __name__ == "__main__":
    unittest.main()
