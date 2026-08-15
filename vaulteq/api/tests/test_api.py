"""VaultEq FastAPI integration tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vaulteq.api.app import app
from vaulteq.api.deps import reset_engines


@pytest.fixture()
def client():
    reset_engines()
    with TestClient(app) as c:
        yield c
    reset_engines()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_auth_unauthorized(client, monkeypatch):
    monkeypatch.setenv("VAULTEQ_API_KEY", "secret-key")
    # Health check is public, but ledger routes are protected
    r = client.post("/ledger/organizations", json={"name": "Protected Org"})
    assert r.status_code == 403
    assert r.json()["detail"]["message"] == "Invalid or missing API Key"


def test_auth_authorized(client, monkeypatch):
    monkeypatch.setenv("VAULTEQ_API_KEY", "secret-key")
    r = client.post(
        "/ledger/organizations", 
        json={"name": "Protected Org"},
        headers={"X-API-Key": "secret-key"}
    )
    assert r.status_code == 200


def test_ledger_post_and_trial_balance(client):
    org = client.post("/ledger/organizations", json={"name": "API Org", "base_currency": "USD"}).json()
    org_id = org["organization_id"]

    client.post("/ledger/accounts", json={
        "organization_id": org_id, "code": "1001", "name": "Cash",
        "type": "ASSET", "normal_balance": "DEBIT",
    })
    client.post("/ledger/accounts", json={
        "organization_id": org_id, "code": "4000", "name": "Revenue",
        "type": "REVENUE", "normal_balance": "CREDIT",
    })

    post = client.post("/ledger/journal", json={
        "organization_id": org_id,
        "idempotency_key": "api_sale_1",
        "lines": [
            {"account_code": "1001", "direction": "DEBIT", "amount_minor": 5000, "currency": "USD"},
            {"account_code": "4000", "direction": "CREDIT", "amount_minor": 5000, "currency": "USD"},
        ],
    })
    assert post.status_code == 200
    body = post.json()
    assert body["status"] == "posted"
    assert body["journal_entry_id"]

    tb = client.get(f"/ledger/trial-balance/{org_id}").json()
    assert tb["balances"]["1001"] == 5000
    assert tb["balances"]["4000"] == -5000

    # reverse
    rev = client.post("/ledger/journal/reverse", json={
        "organization_id": org_id,
        "entry_id": body["journal_entry_id"],
    })
    assert rev.status_code == 200
    tb2 = client.get(f"/ledger/trial-balance/{org_id}").json()
    assert tb2["balances"]["1001"] == 0


def test_ledger_unbalanced_rejected(client):
    org = client.post("/ledger/organizations", json={"name": "Bal Org"}).json()
    org_id = org["organization_id"]
    client.post("/ledger/accounts", json={
        "organization_id": org_id, "code": "1001", "name": "Cash",
        "type": "ASSET", "normal_balance": "DEBIT",
    })
    client.post("/ledger/accounts", json={
        "organization_id": org_id, "code": "4000", "name": "Rev",
        "type": "REVENUE", "normal_balance": "CREDIT",
    })
    r = client.post("/ledger/journal", json={
        "organization_id": org_id,
        "idempotency_key": "bad",
        "lines": [
            {"account_code": "1001", "direction": "DEBIT", "amount_minor": 100, "currency": "USD"},
            {"account_code": "4000", "direction": "CREDIT", "amount_minor": 50, "currency": "USD"},
        ],
    })
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "UNBALANCED_JOURNAL"


def test_identity_kyc_and_risk(client):
    org_id = "org_id_1"
    c = client.post("/identity/customers", json={
        "organization_id": org_id, "legal_name": "Alice API", "email": "a@example.com",
    }).json()
    cid = c["customer"]["id"]

    kyc = client.post("/identity/kyc", json={"organization_id": org_id, "customer_id": cid, "level": "L2"}).json()
    case_id = kyc["kyc_case"]["id"]
    client.post("/identity/kyc/documents", json={
        "organization_id": org_id,
        "kyc_case_id": case_id,
        "document_type": "PASSPORT",
        "document_number": "X99",
    })
    client.post("/identity/kyc/verify", json={
        "organization_id": org_id, "kyc_case_id": case_id, "status": "APPROVED",
    })
    client.post("/identity/aml/screen", json={"organization_id": org_id, "customer_id": cid})
    risk = client.get(f"/identity/risk/{org_id}/{cid}").json()
    assert risk["assessment"]["risk_level"] == "LOW"
    assert risk["can_transact"] is True


def test_identity_blocks_sanctioned(client):
    org_id = "org_id_2"
    c = client.post("/identity/customers", json={
        "organization_id": org_id, "legal_name": "SANCTIONED Villain",
    }).json()
    cid = c["customer"]["id"]
    client.post("/identity/aml/screen", json={"organization_id": org_id, "customer_id": cid})
    risk = client.get(f"/identity/risk/{org_id}/{cid}").json()
    assert risk["assessment"]["risk_level"] == "PROHIBITED"
    assert risk["can_transact"] is False


def test_payments_capture_flow(client):
    org_id = "org_pay_1"
    # Ensure org/accounts exist via payments engine bootstrap
    intent = client.post("/payments/intents", json={
        "organization_id": org_id, "amount": "75.00", "currency": "USD", "description": "API order",
    }).json()
    intent_id = intent["intent"]["id"]

    method = client.post("/payments/methods", json={
        "organization_id": org_id, "customer_id": "cust_api", "method_type": "CARD", "rail": "CARD",
    }).json()
    method_id = method["method"]["id"]

    client.post("/payments/methods/attach", json={
        "organization_id": org_id, "intent_id": intent_id, "method_id": method_id,
    })
    cap = client.post(f"/payments/capture/{org_id}/{intent_id}")
    assert cap.status_code == 200
    body = cap.json()
    assert body["status"] == "success"
    assert body["ledger_entry_id"]

    tb = client.get(f"/payments/trial-balance/{org_id}").json()
    assert tb["balances"]["4000"] == -7500  # $75 revenue


def test_payments_blocked_customer(client):
    org_id = "org_pay_2"
    c = client.post("/identity/customers", json={
        "organization_id": org_id, "legal_name": "OFAC Bad Actor",
    }).json()
    cid = c["customer"]["id"]
    client.post("/identity/aml/screen", json={"organization_id": org_id, "customer_id": cid})

    r = client.post("/payments/intents", json={
        "organization_id": org_id, "amount": "10.00", "currency": "USD", "customer_id": cid,
    })
    assert r.status_code == 403
    assert r.json()["detail"]["error_code"] == "TRANSACTION_BLOCKED"
