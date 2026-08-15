import unittest
from vaulteq.ledger.mcp_server import (
    vaulteq_create_organization,
    vaulteq_create_account,
    vaulteq_post,
    vaulteq_get_trial_balance,
    vaulteq_verify_audit_chain
)

class TestMCPContracts(unittest.TestCase):
    def test_mcp_tool_contract_lifecycle(self):
        # 1. Create Org
        org_res = vaulteq_create_organization(name="MCP Contract Corp")
        self.assertEqual(org_res["status"], "success")
        org_id = org_res["organization_id"]

        # 2. Create Accounts
        acc1 = vaulteq_create_account(org_id, "1001", "Cash", "ASSET", "DEBIT")
        self.assertEqual(acc1["status"], "success")
        acc2 = vaulteq_create_account(org_id, "4000", "Revenue", "REVENUE", "CREDIT")
        self.assertEqual(acc2["status"], "success")

        # 3. Post Balanced Entry via MCP
        post_res = vaulteq_post(
            organization_id=org_id,
            idempotency_key="mcp-test-1",
            lines=[
                {"account_code": "1001", "direction": "DEBIT", "amount_minor": 5000, "currency": "USD"},
                {"account_code": "4000", "direction": "CREDIT", "amount_minor": 5000, "currency": "USD"}
            ]
        )
        self.assertEqual(post_res["status"], "posted")

        # 4. Unbalanced Entry via MCP must return structured error, not raise
        bad_res = vaulteq_post(
            organization_id=org_id,
            idempotency_key="mcp-test-2",
            lines=[
                {"account_code": "1001", "direction": "DEBIT", "amount_minor": 5000, "currency": "USD"},
                {"account_code": "4000", "direction": "CREDIT", "amount_minor": 4000, "currency": "USD"}
            ]
        )
        self.assertEqual(bad_res["status"], "error")
        self.assertEqual(bad_res["error_code"], "UNBALANCED_JOURNAL")

        # 5. Verify Trial Balance & Audit Chain via MCP
        tb_res = vaulteq_get_trial_balance(org_id)
        self.assertEqual(tb_res["status"], "success")

        audit_res = vaulteq_verify_audit_chain(org_id)
        self.assertEqual(audit_res["status"], "success")
        self.assertTrue(audit_res["valid"])

if __name__ == "__main__":
    unittest.main()
