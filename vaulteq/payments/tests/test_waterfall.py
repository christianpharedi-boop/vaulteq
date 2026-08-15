import unittest
from decimal import Decimal
from vaulteq.payments.engine import PaymentsEngine, PaymentsError
from vaulteq.payments.models import (
    PaymentMethodType, 
    PaymentRail, 
    FeeRecoveryPolicy,
    ReconciliationStatus
)

class TestPaymentsWaterfallHardening(unittest.TestCase):
    def setUp(self):
        self.org_id = "test_org_waterfall"
        self.engine = PaymentsEngine(self.org_id, ":memory:")
        self.method = self.engine.add_payment_method("cust_1", PaymentMethodType.CARD, PaymentRail.CARD)

    def test_fee_determinism_and_net_calculation(self):
        # $100.00 Card payment
        # Interchange: 1.75% = 1.75
        # Processing: 0.15% = 0.15
        # Network: 0.05
        # Platform: 0.10% = 0.10
        # Total Fee: 2.05
        # Net: 97.95
        intent = self.engine.create_intent("100.00", "USD")
        self.engine.attach_payment_method(intent.id, self.method.id)
        res = self.engine.confirm_and_capture(intent.id)
        
        tb = self.engine.ledger.get_trial_balance(self.org_id)
        self.assertEqual(tb["1001"], 9795)  # Cash (Net)
        self.assertEqual(tb["4000"], -10000) # Revenue (Gross)
        self.assertEqual(tb["5100"], 175)   # Interchange
        self.assertEqual(tb["5300"], 15)    # Processing
        self.assertEqual(tb["5200"], 5)     # Network
        self.assertEqual(tb["5000"], 10)    # Platform

    def test_refund_keep_all_fees(self):
        intent = self.engine.create_intent("100.00", "USD")
        self.engine.attach_payment_method(intent.id, self.method.id)
        cap = self.engine.confirm_and_capture(intent.id)
        
        # Refund $50.00, keeping all fees
        self.engine.refund(cap["attempt"]["id"], amount="50.00", fee_policy=FeeRecoveryPolicy.KEEP_ALL)
        
        tb = self.engine.ledger.get_trial_balance(self.org_id)
        # Revenue: -10000 + 5000 = -5000
        # Cash: 9795 - 5000 = 4795
        # Fees: Stay at 205 total
        self.assertEqual(tb["4000"], -5000)
        self.assertEqual(tb["1001"], 4795)
        self.assertEqual(tb["5100"], 175)

    def test_refund_all_fees_full_refund(self):
        intent = self.engine.create_intent("100.00", "USD")
        self.engine.attach_payment_method(intent.id, self.method.id)
        cap = self.engine.confirm_and_capture(intent.id)
        
        # Full refund, refunding all fees
        self.engine.refund(cap["attempt"]["id"], fee_policy=FeeRecoveryPolicy.REFUND_ALL)
        
        tb = self.engine.ledger.get_trial_balance(self.org_id)
        # Everything should be zero
        for code, bal in tb.items():
            self.assertEqual(bal, 0, f"Account {code} balance {bal} is not zero")

    def test_refund_proportional_fees(self):
        intent = self.engine.create_intent("100.00", "USD")
        self.engine.attach_payment_method(intent.id, self.method.id)
        cap = self.engine.confirm_and_capture(intent.id)
        
        # Refund 50%, refunding proportional fees
        self.engine.refund(cap["attempt"]["id"], amount="50.00", fee_policy=FeeRecoveryPolicy.REFUND_PROPORTIONAL)
        
        tb = self.engine.ledger.get_trial_balance(self.org_id)
        # Revenue: -10000 + 5000 = -5000
        # Total Fees originally 205. 50% = 102.5 -> rounded to 103 (sum of parts)
        # Let's check parts: 
        # Interchange: 175 * 0.5 = 87.5 -> 88
        # Processing: 15 * 0.5 = 7.5 -> 8
        # Network: 5 * 0.5 = 2.5 -> 3
        # Platform: 10 * 0.5 = 5
        # Total reversed: 88 + 8 + 3 + 5 = 104
        # Cash: 9795 - (5000 - 104) = 9795 - 4896 = 4900 (rounded)
        # Wait, the math is: 
        # DR Revenue 5000
        # CR Cash (5000 - 104) = 4896
        # CR Fees 104
        self.assertEqual(tb["4000"], -5000)
        self.assertEqual(tb["1001"], 9795 - 4896) # Cash balance

    def test_reconciliation_net_amount_match(self):
        intent = self.engine.create_intent("100.00", "USD")
        self.engine.attach_payment_method(intent.id, self.method.id)
        cap = self.engine.confirm_and_capture(intent.id)
        
        # Expected Net is 97.95
        res = self.engine.reconcile(cap["attempt"]["id"], "REF_123", "97.95")
        self.assertEqual(res["reconciliation_status"], ReconciliationStatus.MATCHED.value)

    def test_reconciliation_short_settlement(self):
        intent = self.engine.create_intent("100.00", "USD")
        self.engine.attach_payment_method(intent.id, self.method.id)
        cap = self.engine.confirm_and_capture(intent.id)
        
        # Bank settled $95.00 instead of $97.95 (Short $2.95)
        res = self.engine.reconcile(cap["attempt"]["id"], "REF_SHORT", "95.00")
        self.assertEqual(res["reconciliation_status"], ReconciliationStatus.DISPUTED.value)
        self.assertEqual(res["discrepancy"], "2.95")
        
        tb = self.engine.ledger.get_trial_balance(self.org_id)
        self.assertEqual(tb["9999"], 295) # Suspense Debit
        self.assertEqual(tb["1001"], 9795 - 295) # Cash Credit adjustment

if __name__ == "__main__":
    unittest.main()
