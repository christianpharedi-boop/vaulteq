# VaultEq Invariant & Performance Dashboard (v0.3.0)
Generated automatically by VaultEq Verification Pipeline.

## 1. Core Invariant Matrix
| Invariant Category | Feature Verified | Status |
| :--- | :--- | :--- |
| **Accounting** | Balanced Journals (`SUM(debits) == SUM(credits)`) | **PASS** |
| **Accounting** | Trial Balance Zero-Sum (`SUM(accounts) == 0`) | **PASS** |
| **Transactions** | Atomic Rollback on Failure | **PASS** |
| **Transactions** | Idempotency (`same key + same payload`) | **PASS** |
| **Transactions** | Conflict Detection (`same key + diff payload`) | **PASS** |
| **Concurrency** | Same-Key Contention & Locking | **PASS** |
| **Concurrency** | Conflicting Payload Races | **PASS** |
| **Integrity** | SHA-256 Hash-Chaining | **PASS** |
| **Integrity** | Tamper Detection | **PASS** |
| **Integrity** | Audit Chain Concurrency (100+ events) | **PASS** |
| **Recovery** | Backup & Restore Invariant Preservation | **PASS** |
| **Recovery** | Crash Consistency & Interrupted Rollback | **PASS** |
| **API Security** | CORS Hardening & Credentials Safety | **PASS** |
| **MCP** | Safety Boundary & Error Contracts | **PASS** |

## 2. Test Suite Execution Summary
- **Pytest Status**: SUCCESS (All tests passed)
- **Test Summary**: `======================== 88 passed, 1 warning in 4.65s =========================`

## 3. Performance & Scaling Benchmarks (Local SQLite Configuration)
- **Posting Throughput (TPS)**: `735.82 TPS`
- **1,000 Journals Posted In**: `1.3590 s`
- **Trial Balance Calculation**: `1.74 ms`
- **Audit Chain Verification (1,000+ events)**: `6.78 ms`
- **Trial Balance Invariant Holds**: `True`
- **Audit Chain Integrity Holds**: `True`

---
*VaultEq v0.3.0 is engineered to ensure AI agents orchestrate computation without ever becoming the system of record.*
