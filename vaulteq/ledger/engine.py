"""
VaultEq Ledger Engine
=====================
Deterministic double-entry accounting with hash-chained audit trails.
Zero external dependencies for the core (stdlib + SQLite only).

LLMs orchestrate. VaultEq computes.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# ─── Error Taxonomy ───────────────────────────────────────────────────────────

class VaultEqError(Exception):
    code: str = "UNKNOWN"

    def to_dict(self) -> dict:
        return {"status": "error", "error_code": self.code, "message": str(self)}


class OrganizationNotFoundError(VaultEqError):
    code = "ORGANIZATION_NOT_FOUND"


class AccountNotFoundError(VaultEqError):
    code = "ACCOUNT_NOT_FOUND"


class AccountInactiveError(VaultEqError):
    code = "ACCOUNT_INACTIVE"


class InvalidJournalError(VaultEqError):
    code = "INVALID_JOURNAL"


class UnbalancedJournalError(VaultEqError):
    code = "UNBALANCED_JOURNAL"

    def __init__(self, debit_total: int, credit_total: int):
        self.debit_total = debit_total
        self.credit_total = credit_total
        super().__init__(
            f"Sum of debits ({debit_total}) does not equal sum of credits ({credit_total})"
        )

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["details"] = {
            "debit_total": self.debit_total,
            "credit_total": self.credit_total,
        }
        return d


class DuplicateIdempotencyError(VaultEqError):
    code = "DUPLICATE_IDEMPOTENCY_KEY"


class CurrencyMismatchError(VaultEqError):
    code = "CURRENCY_MISMATCH"


class PeriodClosedError(VaultEqError):
    code = "PERIOD_CLOSED"


class AlreadyReversedError(VaultEqError):
    code = "ALREADY_REVERSED"


# ─── Data Models ──────────────────────────────────────────────────────────────

class AccountType(str, Enum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    REVENUE = "REVENUE"
    EXPENSE = "EXPENSE"


class Direction(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


@dataclass
class JournalLineInput:
    account_code: str
    direction: Direction
    amount_minor: int
    currency: str
    memo: Optional[str] = None


@dataclass
class PostRequest:
    organization_id: str
    idempotency_key: str
    lines: List[JournalLineInput]
    memo: Optional[str] = None
    posting_date: Optional[date] = None


@dataclass
class PostResponse:
    status: str
    journal_entry_id: str
    audit_event_id: str
    audit_signature: str
    trial_balance_delta: Dict[str, int]
    cached: bool = False
    execution_time_ms: Optional[float] = None
    affected_accounts: Optional[List[str]] = None


# ─── Core Engine ──────────────────────────────────────────────────────────────

class LedgerEngine:
    """
    Deterministic double-entry ledger.
    All money is integer minor units. Debits must equal credits or the post is rejected.
    """

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._in_memory_conn: Optional[sqlite3.Connection] = None

        if db_path == ":memory:":
            self._in_memory_conn = sqlite3.connect(
                ":memory:", check_same_thread=False, isolation_level=None
            )
            self._in_memory_conn.row_factory = sqlite3.Row
            self._init_db(self._in_memory_conn)
        else:
            # Ensure schema exists on first open
            with self._get_conn() as conn:
                self._init_db(conn)

    def __enter__(self) -> "LedgerEngine":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def close(self) -> None:
        if self._in_memory_conn is not None:
            self._in_memory_conn.close()
            self._in_memory_conn = None

    # ── Connection & Schema ───────────────────────────────────────────────────

    def _init_db(self, conn: sqlite3.Connection) -> None:
        import importlib.resources
        try:
            # Preferred: package data
            schema_sql = (
                importlib.resources.files("vaulteq.ledger")
                .joinpath("schema.sql")
                .read_text(encoding="utf-8")
            )
        except Exception:
            # Fallback for development / direct file use
            import os
            schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
            with open(schema_path, "r", encoding="utf-8") as f:
                schema_sql = f.read()
        conn.executescript(schema_sql)
        if conn.isolation_level is not None:
            conn.commit()

    @contextmanager
    def _get_conn(self):
        """Yield a connection. In-memory reuses the single connection; file opens a fresh one."""
        if self._in_memory_conn is not None:
            yield self._in_memory_conn
        else:
            conn = sqlite3.connect(self.db_path, isolation_level=None)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _sha256(self, payload: str) -> str:
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _generate_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    def _normalize_payload(self, req: PostRequest) -> str:
        """Deterministic JSON for idempotency comparison."""
        payload = {
            "organization_id": req.organization_id,
            "idempotency_key": req.idempotency_key,
            "memo": req.memo,
            "posting_date": req.posting_date.isoformat() if req.posting_date else None,
            "lines": sorted(
                [
                    {
                        "account_code": l.account_code,
                        "direction": l.direction.value,
                        "amount_minor": l.amount_minor,
                        "currency": l.currency,
                        "memo": l.memo,
                    }
                    for l in (req.lines or [])
                ],
                key=lambda x: (x["account_code"], x["direction"], x["amount_minor"]),
            ),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def _get_last_audit_hash(self, conn: sqlite3.Connection, org_id: str) -> Optional[str]:
        row = conn.execute(
            """
            SELECT payload_sha256 FROM audit_event
            WHERE organization_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (org_id,),
        ).fetchone()
        return row["payload_sha256"] if row else None

    def _append_audit(
        self,
        conn: sqlite3.Connection,
        org_id: str,
        entity_type: str,
        entity_id: str,
        action: str,
        payload: dict,
    ) -> Tuple[str, str]:
        """Append a hash-chained audit event. Returns (event_id, payload_sha256)."""
        event_id = self._generate_id("ae")
        prev_hash = self._get_last_audit_hash(conn, org_id)

        # Include chain metadata inside the payload that is hashed
        full_payload = {
            **payload,
            "_audit_meta": {
                "event_id": event_id,
                "prev_event_hash": prev_hash,
                "timestamp": self._now(),
            },
        }
        payload_json = json.dumps(full_payload, sort_keys=True, default=str)
        payload_hash = self._sha256(payload_json)
        created_at = self._now()

        conn.execute(
            """
            INSERT INTO audit_event
                (id, organization_id, entity_type, entity_id, action,
                 payload, payload_sha256, prev_event_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                org_id,
                entity_type,
                entity_id,
                action,
                payload_json,
                payload_hash,
                prev_hash,
                created_at,
            ),
        )
        return event_id, payload_hash

    # ── Organization & Accounts ───────────────────────────────────────────────

    def create_organization(
        self, name: str, base_currency: str = "USD", org_id: Optional[str] = None
    ) -> str:
        org_id = org_id or self._generate_id("org")
        with self._get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "INSERT INTO organization (id, name, base_currency) VALUES (?, ?, ?)",
                    (org_id, name, base_currency.upper()),
                )
                self._append_audit(
                    conn,
                    org_id,
                    "organization",
                    org_id,
                    "CREATE",
                    {"name": name, "base_currency": base_currency.upper()},
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return org_id

    def create_account(
        self,
        organization_id: str,
        code: str,
        name: str,
        account_type: AccountType,
        normal_balance: Direction,
    ) -> str:
        acc_id = self._generate_id("acc")
        with self._get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                org = conn.execute(
                    "SELECT id FROM organization WHERE id = ?", (organization_id,)
                ).fetchone()
                if not org:
                    raise OrganizationNotFoundError(
                        f"Organization {organization_id} not found"
                    )

                conn.execute(
                    """
                    INSERT INTO account
                        (id, organization_id, code, name, type, normal_balance)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        acc_id,
                        organization_id,
                        code,
                        name,
                        account_type.value,
                        normal_balance.value,
                    ),
                )
                self._append_audit(
                    conn,
                    organization_id,
                    "account",
                    acc_id,
                    "CREATE",
                    {
                        "code": code,
                        "name": name,
                        "type": account_type.value,
                        "normal_balance": normal_balance.value,
                    },
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return acc_id

    def list_accounts(self, organization_id: str) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT id, code, name, type, normal_balance, is_active, created_at
                FROM account
                WHERE organization_id = ?
                ORDER BY code ASC
                """,
                (organization_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Core Post ─────────────────────────────────────────────────────────────

    def post(self, request: PostRequest) -> PostResponse:
        import time

        t0 = time.perf_counter()

        if not request.lines or len(request.lines) < 2:
            raise InvalidJournalError("Journal entry must contain at least two lines")

        incoming_payload = self._normalize_payload(request)
        incoming_hash = self._sha256(incoming_payload)

        with self._get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")  # reserved lock – critical for real idempotency

            try:
                # ── Idempotency check (under lock) ────────────────────────────
                existing = conn.execute(
                    """
                    SELECT id, payload_hash FROM journal_entry
                    WHERE organization_id = ? AND idempotency_key = ?
                    """,
                    (request.organization_id, request.idempotency_key),
                ).fetchone()

                if existing:
                    if existing["payload_hash"] == incoming_hash:
                        conn.execute("COMMIT")
                        return self._reconstruct_response(
                            conn, existing["id"], cached=True
                        )
                    else:
                        conn.execute("ROLLBACK")
                        raise DuplicateIdempotencyError(
                            f"Idempotency key '{request.idempotency_key}' already used "
                            f"with a different payload (existing entry {existing['id']})"
                        )

                # ── Organization & period checks ──────────────────────────────
                org = conn.execute(
                    "SELECT base_currency FROM organization WHERE id = ?",
                    (request.organization_id,),
                ).fetchone()
                if not org:
                    raise OrganizationNotFoundError(
                        f"Organization {request.organization_id} not found"
                    )
                base_currency = org["base_currency"]

                post_date = request.posting_date or date.today()
                period_str = post_date.strftime("%Y-%m")
                closed = conn.execute(
                    """
                    SELECT 1 FROM closed_period
                    WHERE organization_id = ? AND period = ?
                    """,
                    (request.organization_id, period_str),
                ).fetchone()
                if closed:
                    raise PeriodClosedError(
                        f"Period {period_str} is closed for organization {request.organization_id}"
                    )

                # ── Validate lines & compute base amounts ─────────────────────
                resolved_lines: List[dict] = []
                debit_total = 0
                credit_total = 0
                affected_accounts: List[str] = []

                for line in request.lines:
                    if line.amount_minor <= 0:
                        raise InvalidJournalError(
                            f"amount_minor must be positive (got {line.amount_minor})"
                        )

                    acc = conn.execute(
                        """
                        SELECT id, code, is_active FROM account
                        WHERE organization_id = ? AND code = ?
                        """,
                        (request.organization_id, line.account_code),
                    ).fetchone()
                    if not acc:
                        raise AccountNotFoundError(
                            f"Account '{line.account_code}' not found"
                        )
                    if not acc["is_active"]:
                        raise AccountInactiveError(
                            f"Account '{line.account_code}' is inactive"
                        )

                    fx_rate = Decimal("1")
                    if line.currency.upper() != base_currency:
                        rate_row = conn.execute(
                            """
                            SELECT rate FROM fx_rate
                            WHERE organization_id = ?
                              AND from_currency = ?
                              AND to_currency = ?
                              AND effective_at <= ?
                            ORDER BY effective_at DESC
                            LIMIT 1
                            """,
                            (
                                request.organization_id,
                                line.currency.upper(),
                                base_currency,
                                post_date.isoformat() + "T23:59:59.999999+00:00",
                            ),
                        ).fetchone()
                        if not rate_row:
                            raise CurrencyMismatchError(
                                f"No exchange rate found for {line.currency} → {base_currency} "
                                f"as of {post_date}"
                            )
                        fx_rate = Decimal(rate_row["rate"])

                    base_amount = int(
                        (Decimal(line.amount_minor) * fx_rate).to_integral_value()
                    )

                    if line.direction == Direction.DEBIT:
                        debit_total += base_amount
                    else:
                        credit_total += base_amount

                    resolved_lines.append(
                        {
                            "id": self._generate_id("jl"),
                            "account_id": acc["id"],
                            "account_code": acc["code"],
                            "direction": line.direction.value,
                            "amount_minor": line.amount_minor,
                            "currency": line.currency.upper(),
                            "fx_rate": str(fx_rate),
                            "base_amount_minor": base_amount,
                            "memo": line.memo,
                        }
                    )
                    affected_accounts.append(acc["code"])

                if debit_total != credit_total:
                    raise UnbalancedJournalError(debit_total, credit_total)

                # ── Insert journal entry + lines ──────────────────────────────
                entry_id = self._generate_id("je")
                posted_at = self._now()

                conn.execute(
                    """
                    INSERT INTO journal_entry
                        (id, organization_id, idempotency_key, payload_hash, posted_at, memo)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry_id,
                        request.organization_id,
                        request.idempotency_key,
                        incoming_hash,
                        posted_at,
                        request.memo,
                    ),
                )

                for l in resolved_lines:
                    conn.execute(
                        """
                        INSERT INTO journal_line
                            (id, journal_entry_id, account_id, direction,
                             amount_minor, currency, fx_rate, base_amount_minor, memo)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            l["id"],
                            entry_id,
                            l["account_id"],
                            l["direction"],
                            l["amount_minor"],
                            l["currency"],
                            l["fx_rate"],
                            l["base_amount_minor"],
                            l["memo"],
                        ),
                    )

                # ── Audit ─────────────────────────────────────────────────────
                audit_payload = {
                    "journal_entry_id": entry_id,
                    "idempotency_key": request.idempotency_key,
                    "memo": request.memo,
                    "lines": resolved_lines,
                    "debit_total": debit_total,
                    "credit_total": credit_total,
                }
                audit_id, audit_hash = self._append_audit(
                    conn,
                    request.organization_id,
                    "journal_entry",
                    entry_id,
                    "POST",
                    audit_payload,
                )

                conn.execute("COMMIT")

            except sqlite3.IntegrityError as e:
                # UNIQUE constraint race – another writer committed first
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.OperationalError:
                    pass
                winner = conn.execute(
                    """
                    SELECT id, payload_hash FROM journal_entry
                    WHERE organization_id = ? AND idempotency_key = ?
                    """,
                    (request.organization_id, request.idempotency_key),
                ).fetchone()
                if winner and winner["payload_hash"] == incoming_hash:
                    return self._reconstruct_response(conn, winner["id"], cached=True)
                raise DuplicateIdempotencyError(
                    f"Idempotency key '{request.idempotency_key}' conflict after race"
                ) from e
            except VaultEqError:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.OperationalError:
                    pass
                raise
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.OperationalError:
                    pass
                raise

        elapsed = (time.perf_counter() - t0) * 1000

        # Build delta outside the transaction (read-only)
        delta: Dict[str, int] = {}
        for l in resolved_lines:
            sign = 1 if l["direction"] == "DEBIT" else -1
            delta[l["account_code"]] = (
                delta.get(l["account_code"], 0) + sign * l["base_amount_minor"]
            )

        return PostResponse(
            status="posted",
            journal_entry_id=entry_id,
            audit_event_id=audit_id,
            audit_signature=f"sha256:{audit_hash}",
            trial_balance_delta=delta,
            cached=False,
            execution_time_ms=round(elapsed, 2),
            affected_accounts=sorted(set(affected_accounts)),
        )

    def _reconstruct_response(
        self, conn: sqlite3.Connection, je_id: str, cached: bool = False
    ) -> PostResponse:
        audit = conn.execute(
            """
            SELECT id, payload_sha256 FROM audit_event
            WHERE entity_id = ? AND entity_type = 'journal_entry'
            ORDER BY created_at DESC LIMIT 1
            """,
            (je_id,),
        ).fetchone()

        lines = conn.execute(
            """
            SELECT a.code, jl.direction, jl.base_amount_minor
            FROM journal_line jl
            JOIN account a ON jl.account_id = a.id
            WHERE jl.journal_entry_id = ?
            """,
            (je_id,),
        ).fetchall()

        delta: Dict[str, int] = {}
        for line in lines:
            sign = 1 if line["direction"] == "DEBIT" else -1
            delta[line["code"]] = (
                delta.get(line["code"], 0) + sign * line["base_amount_minor"]
            )

        return PostResponse(
            status="posted",
            journal_entry_id=je_id,
            audit_event_id=audit["id"] if audit else "",
            audit_signature=f"sha256:{audit['payload_sha256']}" if audit else "",
            trial_balance_delta=delta,
            cached=cached,
        )

    # ── Reversal (atomic, single transaction) ─────────────────────────────────

    def reverse(
        self,
        organization_id: str,
        entry_id: str,
        memo: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> PostResponse:
        """
        Create the exact opposite journal entry and link it via reversed_by.
        Fully atomic – everything happens under one reserved lock.
        """
        key = idempotency_key or f"rev_{entry_id}"

        with self._get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                entry = conn.execute(
                    """
                    SELECT id, reversed_by, memo FROM journal_entry
                    WHERE organization_id = ? AND id = ?
                    """,
                    (organization_id, entry_id),
                ).fetchone()
                if not entry:
                    raise InvalidJournalError(f"Journal entry {entry_id} not found")
                if entry["reversed_by"]:
                    raise AlreadyReversedError(
                        f"Journal entry {entry_id} is already reversed by {entry['reversed_by']}"
                    )

                # Check if a reverse already exists under this key (idempotent reverse)
                existing_rev = conn.execute(
                    """
                    SELECT id, payload_hash FROM journal_entry
                    WHERE organization_id = ? AND idempotency_key = ?
                    """,
                    (organization_id, key),
                ).fetchone()
                if existing_rev:
                    # Already reversed (or concurrent reverse succeeded)
                    conn.execute(
                        "UPDATE journal_entry SET reversed_by = ? WHERE id = ? AND reversed_by IS NULL",
                        (existing_rev["id"], entry_id),
                    )
                    conn.execute("COMMIT")
                    return self._reconstruct_response(
                        conn, existing_rev["id"], cached=True
                    )

                lines = conn.execute(
                    """
                    SELECT a.code AS account_code, jl.direction, jl.amount_minor,
                           jl.currency, jl.memo
                    FROM journal_line jl
                    JOIN account a ON jl.account_id = a.id
                    WHERE jl.journal_entry_id = ?
                    """,
                    (entry_id,),
                ).fetchall()

                if not lines:
                    raise InvalidJournalError(
                        f"Journal entry {entry_id} has no lines"
                    )

                # Build opposite lines
                rev_lines = [
                    JournalLineInput(
                        account_code=l["account_code"],
                        direction=(
                            Direction.CREDIT
                            if l["direction"] == "DEBIT"
                            else Direction.DEBIT
                        ),
                        amount_minor=l["amount_minor"],
                        currency=l["currency"],
                        memo=l["memo"],
                    )
                    for l in lines
                ]

                # Re-use the post validation/insertion path but stay inside this transaction.
                # We do the work manually so we never nest connections/transactions.
                org = conn.execute(
                    "SELECT base_currency FROM organization WHERE id = ?",
                    (organization_id,),
                ).fetchone()
                if not org:
                    raise OrganizationNotFoundError(
                        f"Organization {organization_id} not found"
                    )
                base_currency = org["base_currency"]

                resolved: List[dict] = []
                debit_total = credit_total = 0
                affected: List[str] = []

                for line in rev_lines:
                    acc = conn.execute(
                        """
                        SELECT id, code, is_active FROM account
                        WHERE organization_id = ? AND code = ?
                        """,
                        (organization_id, line.account_code),
                    ).fetchone()
                    if not acc:
                        raise AccountNotFoundError(
                            f"Account '{line.account_code}' not found"
                        )
                    if not acc["is_active"]:
                        raise AccountInactiveError(
                            f"Account '{line.account_code}' is inactive"
                        )

                    # For reversals we keep the original amounts/currencies (no new FX)
                    base_amount = line.amount_minor  # already in base if original was converted
                    # Safer: look up original base_amount_minor from the line we just selected
                    # (we already have the original lines; recompute from original base)
                    # For simplicity and correctness we re-fetch original base amounts.
                    orig = conn.execute(
                        """
                        SELECT jl.base_amount_minor
                        FROM journal_line jl
                        JOIN account a ON jl.account_id = a.id
                        WHERE jl.journal_entry_id = ? AND a.code = ?
                          AND jl.direction = ?
                        LIMIT 1
                        """,
                        (
                            entry_id,
                            line.account_code,
                            "DEBIT" if line.direction == Direction.CREDIT else "CREDIT",
                        ),
                    ).fetchone()
                    base_amount = orig["base_amount_minor"] if orig else line.amount_minor

                    if line.direction == Direction.DEBIT:
                        debit_total += base_amount
                    else:
                        credit_total += base_amount

                    resolved.append(
                        {
                            "id": self._generate_id("jl"),
                            "account_id": acc["id"],
                            "account_code": acc["code"],
                            "direction": line.direction.value,
                            "amount_minor": line.amount_minor,
                            "currency": line.currency,
                            "fx_rate": "1",
                            "base_amount_minor": base_amount,
                            "memo": line.memo,
                        }
                    )
                    affected.append(acc["code"])

                if debit_total != credit_total:
                    # Should never happen if original was balanced
                    raise UnbalancedJournalError(debit_total, credit_total)

                rev_id = self._generate_id("je")
                posted_at = self._now()
                payload_hash = self._sha256(
                    self._normalize_payload(
                        PostRequest(
                            organization_id=organization_id,
                            idempotency_key=key,
                            lines=rev_lines,
                            memo=memo or f"Reversal of {entry_id}",
                        )
                    )
                )

                conn.execute(
                    """
                    INSERT INTO journal_entry
                        (id, organization_id, idempotency_key, payload_hash, posted_at, memo)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rev_id,
                        organization_id,
                        key,
                        payload_hash,
                        posted_at,
                        memo or f"Reversal of {entry_id}",
                    ),
                )

                for l in resolved:
                    conn.execute(
                        """
                        INSERT INTO journal_line
                            (id, journal_entry_id, account_id, direction,
                             amount_minor, currency, fx_rate, base_amount_minor, memo)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            l["id"],
                            rev_id,
                            l["account_id"],
                            l["direction"],
                            l["amount_minor"],
                            l["currency"],
                            l["fx_rate"],
                            l["base_amount_minor"],
                            l["memo"],
                        ),
                    )

                # Link original → reversal
                conn.execute(
                    "UPDATE journal_entry SET reversed_by = ? WHERE id = ?",
                    (rev_id, entry_id),
                )

                audit_id, audit_hash = self._append_audit(
                    conn,
                    organization_id,
                    "journal_entry",
                    rev_id,
                    "REVERSE",
                    {
                        "reverses": entry_id,
                        "journal_entry_id": rev_id,
                        "lines": resolved,
                    },
                )

                # Also record the reverse link on the original
                self._append_audit(
                    conn,
                    organization_id,
                    "journal_entry",
                    entry_id,
                    "REVERSED",
                    {"reversed_by": rev_id},
                )

                conn.execute("COMMIT")

            except Exception:
                conn.execute("ROLLBACK")
                raise

        delta: Dict[str, int] = {}
        for l in resolved:
            sign = 1 if l["direction"] == "DEBIT" else -1
            delta[l["account_code"]] = (
                delta.get(l["account_code"], 0) + sign * l["base_amount_minor"]
            )

        return PostResponse(
            status="posted",
            journal_entry_id=rev_id,
            audit_event_id=audit_id,
            audit_signature=f"sha256:{audit_hash}",
            trial_balance_delta=delta,
            cached=False,
            affected_accounts=sorted(set(affected)),
        )

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_trial_balance(self, organization_id: str) -> Dict[str, int]:
        """
        Net balances across all journal lines.
        Original + reversal cancel naturally (both kept for full auditability).
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT a.code,
                       SUM(CASE
                             WHEN jl.direction = 'DEBIT'  THEN jl.base_amount_minor
                             ELSE -jl.base_amount_minor
                           END) AS net
                FROM account a
                LEFT JOIN journal_line jl ON a.id = jl.account_id
                LEFT JOIN journal_entry je ON jl.journal_entry_id = je.id
                WHERE a.organization_id = ?
                GROUP BY a.code
                ORDER BY a.code
                """,
                (organization_id,),
            ).fetchall()
            return {row["code"]: (row["net"] or 0) for row in rows}

    def get_account_balance(self, organization_id: str, account_code: str) -> int:
        """Net balance for one account. Original + reversal cancel naturally."""
        with self._get_conn() as conn:
            acc = conn.execute(
                "SELECT id FROM account WHERE organization_id = ? AND code = ?",
                (organization_id, account_code),
            ).fetchone()
            if not acc:
                raise AccountNotFoundError(f"Account {account_code} not found")

            row = conn.execute(
                """
                SELECT SUM(CASE
                             WHEN jl.direction = 'DEBIT'  THEN jl.base_amount_minor
                             ELSE -jl.base_amount_minor
                           END) AS net
                FROM journal_line jl
                JOIN journal_entry je ON jl.journal_entry_id = je.id
                WHERE jl.account_id = ?
                """,
                (acc["id"],),
            ).fetchone()
            return row["net"] or 0


    def get_journal_entry(
        self, organization_id: str, entry_id: str
    ) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            entry = conn.execute(
                """
                SELECT * FROM journal_entry
                WHERE organization_id = ? AND id = ?
                """,
                (organization_id, entry_id),
            ).fetchone()
            if not entry:
                return None

            lines = conn.execute(
                """
                SELECT jl.*, a.code AS account_code
                FROM journal_line jl
                JOIN account a ON jl.account_id = a.id
                WHERE jl.journal_entry_id = ?
                """,
                (entry_id,),
            ).fetchall()

            res = dict(entry)
            res["lines"] = [dict(l) for l in lines]
            return res

    def list_journal_entries(
        self,
        organization_id: str,
        limit: int = 50,
        after_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            if after_id:
                rows = conn.execute(
                    """
                    SELECT * FROM journal_entry
                    WHERE organization_id = ?
                      AND created_at > (
                          SELECT created_at FROM journal_entry WHERE id = ?
                      )
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (organization_id, after_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM journal_entry
                    WHERE organization_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (organization_id, limit),
                ).fetchall()
            return [dict(r) for r in rows]

    def get_audit_trail(
        self, organization_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT id, entity_type, entity_id, action, payload,
                       payload_sha256, prev_event_hash, created_at
                FROM audit_event
                WHERE organization_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (organization_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def verify_audit_chain(self, organization_id: str) -> bool:
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT payload_sha256, prev_event_hash
                FROM audit_event
                WHERE organization_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (organization_id,),
            ).fetchall()
            for i in range(1, len(rows)):
                if rows[i]["prev_event_hash"] != rows[i - 1]["payload_sha256"]:
                    return False
            return True

    # ── Period Close & FX ─────────────────────────────────────────────────────

    def close_period(self, organization_id: str, period: str) -> None:
        """period format: YYYY-MM"""
        with self._get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO closed_period (organization_id, period)
                    VALUES (?, ?)
                    """,
                    (organization_id, period),
                )
                self._append_audit(
                    conn,
                    organization_id,
                    "period",
                    period,
                    "CLOSE_PERIOD",
                    {"period": period},
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def set_exchange_rate(
        self,
        organization_id: str,
        from_currency: str,
        to_currency: str,
        rate: Decimal,
        effective_at: Optional[datetime] = None,
    ) -> None:
        eff = (effective_at or datetime.now(timezone.utc)).isoformat()
        with self._get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO fx_rate
                        (organization_id, from_currency, to_currency, rate, effective_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        organization_id,
                        from_currency.upper(),
                        to_currency.upper(),
                        str(rate),
                        eff,
                    ),
                )
                self._append_audit(
                    conn,
                    organization_id,
                    "fx_rate",
                    f"{from_currency.upper()}/{to_currency.upper()}",
                    "SET_RATE",
                    {"rate": str(rate), "effective_at": eff},
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
