# VaultEq

**The double-entry ledger you `pip install` — not one you sign up for.**

Deterministic financial infrastructure for AI agents.  
LLMs orchestrate. VaultEq computes.

[![CI](https://github.com/christianpharedi-boop/vaulteq/actions/workflows/ci.yml/badge.svg)](https://github.com/christianpharedi-boop/vaulteq/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Why VaultEq?

Most “AI-native” finance tools let the model touch the arithmetic. That’s how you get confident, wrong balances.

VaultEq is the boring part on purpose:

- **Debits must equal credits** — or the post is rejected
- **Integer minor units only** — never floats
- **Real idempotency** — safe retries, explicit conflicts
- **Hash-chained audit trail** — tamper-evident
- **Agent-native** — library, MCP server, and HTTP API

Your first customer is a developer building an agent that needs to post a journal without hallucinating the math.

---

## Install

```bash
pip install -e ".[dev,api,mcp]"   # from repo
# or eventually:
# pip install vaulteq
# pip install "vaulteq[api]"
# pip install "vaulteq[mcp]"
```

Core ledger has **zero required dependencies** (stdlib + SQLite).

---

## Quick start — Ledger

```python
from vaulteq.ledger import (
    LedgerEngine, PostRequest, JournalLineInput, Direction, AccountType
)

with LedgerEngine("mybook.db") as eng:
    org = eng.create_organization("Acme Corp", "USD")
    eng.create_account(org, "1001", "Cash", AccountType.ASSET, Direction.DEBIT)
    eng.create_account(org, "4000", "Revenue", AccountType.REVENUE, Direction.CREDIT)

    res = eng.post(PostRequest(
        organization_id=org,
        idempotency_key="order_123",
        lines=[
            JournalLineInput("1001", Direction.DEBIT, 5000, "USD"),
            JournalLineInput("4000", Direction.CREDIT, 5000, "USD"),
        ],
    ))
    print(res.journal_entry_id, eng.get_trial_balance(org))
```

---

## Modules

| Module | Role |
|--------|------|
| **ledger** | Double-entry engine, audit chain, FX, period close, reversals |
| **payments** | Intents → capture → fee waterfall → refunds → reconciliation |
| **identity** | KYC, AML screening, risk scoring, transaction blocking |
| **api** | FastAPI HTTP surface over all three |

Payments and Identity share the same ledger. Sanctioned or high-risk customers are blocked before capture.

---

## HTTP API

```bash
PYTHONPATH=. uvicorn vaulteq.api.app:app --reload
# OpenAPI: http://127.0.0.1:8000/docs
```

```bash
# Post a balanced journal
curl -s -X POST localhost:8000/ledger/journal \
  -H 'Content-Type: application/json' \
  -d '{
    "organization_id": "ORG",
    "idempotency_key": "k1",
    "lines": [
      {"account_code": "1001", "direction": "DEBIT",  "amount_minor": 1000, "currency": "USD"},
      {"account_code": "4000", "direction": "CREDIT", "amount_minor": 1000, "currency": "USD"}
    ]
  }'
```

---

## MCP server (agents)

```bash
vaulteq-mcp
# or
VAULTEQ_DB_PATH=./mybook.db vaulteq-mcp
```

Exposes tools such as `vaulteq_post`, `vaulteq_trial_balance`, `vaulteq_reverse`, `vaulteq_create_account`, and more — so an agent never has to do the arithmetic itself.

---

## Payments + Identity

```python
from vaulteq.identity import IdentityEngine, KYCStatus
from vaulteq.payments.engine import PaymentsEngine
from vaulteq.payments.models import PaymentMethodType, PaymentRail

id_eng = IdentityEngine("org_1")
customer = id_eng.create_customer("Alice")
case = id_eng.initiate_kyc(customer.id)
id_eng.verify_kyc(case.id, KYCStatus.APPROVED)
id_eng.screen_aml(customer.id)

pay = PaymentsEngine("org_1", identity_engine=id_eng)
intent = pay.create_intent("100.00", "USD", customer_id=customer.id)
method = pay.add_payment_method(customer.id, PaymentMethodType.CARD, PaymentRail.CARD)
pay.attach_payment_method(intent.id, method.id)
result = pay.confirm_and_capture(intent.id)
# → balanced ledger entry with fee waterfall
```

---

## Design guarantees

- Amounts are **integer minor units** (BIGINT / cents)
- Journal posts are **atomic** under `BEGIN IMMEDIATE`
- Idempotency: same key + same payload → cached response; different payload → conflict
- Audit events are **hash-chained** (`prev_event_hash` → SHA-256)
- Reversals are atomic and link via `reversed_by`
- Period close blocks further posts into closed months
- Multi-currency via explicit FX rates (no silent conversion)

---

## Tests

```bash
PYTHONPATH=. pytest vaulteq/ -q
# 55+ tests — ledger, payments, identity, API
```

---

## CFO Agent Demo

Run the end-to-end orchestration demo (onboarding, verification, and disbursement):

```bash
PYTHONPATH=. python3 examples/cfo_agent_demo.py
```

## Status

**Beta (v0.2.1).** Hardened core, enterprise features (reversals, period locks, multi-currency), and end-to-end agent orchestration verified. Not independently audited.

If you use VaultEq with real money, you own testing, review, and risk assessment. Provided as-is under the MIT License.

---

## License

MIT © Basie Pharedi

---

*Infrastructure, not a fintech. Build agents that can’t hallucinate the books.*
