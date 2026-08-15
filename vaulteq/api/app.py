"""
VaultEq HTTP API
================
FastAPI surface over Ledger, Payments, and Identity.

Run:
    uvicorn vaulteq.api.app:app --reload
    VAULTEQ_DB_PATH=./vaulteq.db uvicorn vaulteq.api.app:app
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from vaulteq.api.identity_routes import router as identity_router
from vaulteq.api.ledger_routes import router as ledger_router
from vaulteq.api.payments_routes import router as payments_router

app = FastAPI(
    title="VaultEq",
    description=(
        "Deterministic, agent-native financial infrastructure. "
        "Ledger · Payments · Identity. LLMs orchestrate. VaultEq computes."
    ),
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ledger_router)
app.include_router(payments_router)
app.include_router(identity_router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "vaulteq", "version": "0.2.0"}


@app.get("/")
def root():
    return {
        "name": "VaultEq",
        "version": "0.2.0",
        "modules": ["ledger", "payments", "identity"],
        "docs": "/docs",
    }
