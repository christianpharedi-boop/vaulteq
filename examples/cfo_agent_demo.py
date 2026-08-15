import sys
import os
import json
from decimal import Decimal
from datetime import datetime

# Ensure the monorepo is in the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vaulteq.ledger import LedgerEngine, Direction, AccountType
from vaulteq.payments import PaymentsEngine, PaymentMethodType, PaymentRail
from vaulteq.identity import IdentityEngine
from vaulteq.identity.models import KYCStatus, DocumentType

def run_demo():
    print("=" * 60)
    print("VaultEq CFO Agent Demo: Vendor Onboarding & Disbursement")
    print("=" * 60)
    
    # 1. Initialize the Unified Core
    # We share a single Ledger instance so all modules write to the same audit chain.
    org_id = "org_cfo_demo"
    ledger = LedgerEngine(":memory:")
    payments = PaymentsEngine(org_id, ledger=ledger)
    identity = IdentityEngine(organization_id=org_id, ledger=ledger)
    
    print(f"\n[1] Initialized VaultEq Core for Organization: {org_id}")
    
    # 2. Onboard a New Vendor (IdentityX)
    vendor_name = "Global Logistics Inc"
    print(f"\n[2] Agent Action: Onboarding Vendor '{vendor_name}'...")
    
    vendor = identity.create_customer(vendor_name)
    vendor_id = vendor.id
    print(f"    - Vendor ID created: {vendor_id}")
    
    # Start KYC Case
    kyc_case = identity.initiate_kyc(vendor_id)
    case_id = kyc_case.id
    print(f"    - KYC Case initiated: {case_id}")
    
    # Upload Verification Documents
    identity.upload_document(case_id, DocumentType.PASSPORT, "DOC-99-LOGISTICS")
    print(f"    - Business verification document uploaded.")
    
    # Perform AML Screening & Risk Assessment
    risk_res = identity.assess_risk(vendor_id)
    print(f"    - Initial Risk Assessment: {risk_res.risk_level}")
    
    # Approve Vendor
    identity.verify_kyc(case_id, KYCStatus.APPROVED)
    final_risk = identity.assess_risk(vendor_id)
    print(f"    - Final Risk Assessment: {final_risk.risk_level}")
    print(f"    - Vendor Status: VERIFIED")
    
    # 3. Setup Payment Method (PaymentsX)
    print(f"\n[3] Agent Action: Registering Vendor Bank Account (ACH)...")
    method = payments.add_payment_method(vendor_id, PaymentMethodType.BANK_ACCOUNT, PaymentRail.ACH)
    method_id = method.id
    print(f"    - Payment Method Tokenized: {method.token}")
    
    # 4. Execute Disbursement (PaymentsX -> LedgerX)
    disbursement_amount = "500.00"
    print(f"\n[4] Agent Action: Executing Disbursement of ${disbursement_amount}...")
    
    # Create Payment Intent
    intent = payments.create_intent(disbursement_amount, "USD", f"Disbursement for Invoice #INV-2026-001")
    payments.attach_payment_method(intent.id, method_id)
    
    # Capture (Triggers Ledger Post)
    res_cap = payments.confirm_and_capture(intent.id)
    print(f"    - Payment Captured. Ledger Entry ID: {res_cap['ledger_entry_id']}")
    
    # 5. Financial Verification (LedgerX)
    print(f"\n[5] Agent Action: Verifying Financial Integrity...")
    
    tb = ledger.get_trial_balance(org_id)
    print("\n    --- Trial Balance (Non-Zero) ---")
    for code, balance in tb.items():
        if balance != 0:
            print(f"    Account {code}: {balance:>10} (minor units)")
            
    # Verify Audit Chain
    is_valid = ledger.verify_audit_chain(org_id)
    print(f"\n    - Hash-Linked Audit Chain Integrity: {'VALID' if is_valid else 'COMPROMISED'}")
    
    # 6. Detailed Audit Trace
    print(f"\n[6] Audit Trail Trace (Last 5 events):")
    audit_trail = ledger.get_audit_trail(org_id, limit=5)
    for event in audit_trail:
        print(f"    [{event['created_at'][:19]}] {event['action']} on {event['entity_type']} ({event['entity_id']})")
        print(f"    Hash: {event['payload_sha256'][:16]}...")

    print("\n" + "=" * 60)
    print("Demo Complete: Vendor Onboarded, Paid, and Audited.")
    print("=" * 60)

if __name__ == "__main__":
    run_demo()
