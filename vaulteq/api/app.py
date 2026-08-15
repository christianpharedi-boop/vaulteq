"""
VaultEq HTTP API
================
FastAPI surface over Ledger, Payments, and Identity.

Run:
    uvicorn vaulteq.api.app:app --reload
    VAULTEQ_DB_PATH=./vaulteq.db uvicorn vaulteq.api.app:app
"""

from __future__ import annotations

import os
from fastapi import FastAPI, Security, HTTPException, status, Depends
from fastapi.security.api_key import APIKeyHeader
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
    version="0.3.0",
)

# Security: API Key Authentication
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

async def get_api_key(api_key: str = Security(api_key_header)):
    # Check env var at request time so tests can toggle it
    expected_key = os.environ.get("VAULTEQ_API_KEY")
    if not expected_key:
        return None  # Auth disabled if no key set
    if api_key == expected_key:
        return api_key
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"status": "error", "message": "Invalid or missing API Key"}
    )

# CORS: Fix configuration for production safety
# When allow_credentials=True, allow_origins cannot be ["*"]
# We default to ["*"] with allow_credentials=False for the beta,
# but allow pinning via environment variable.
ALLOWED_ORIGINS = os.environ.get("VAULTEQ_ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False, # Credentials require explicit origins
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routes with optional global authentication
# We apply the dependency to all routers
app.include_router(ledger_router, dependencies=[Depends(get_api_key)])
app.include_router(payments_router, dependencies=[Depends(get_api_key)])
app.include_router(identity_router, dependencies=[Depends(get_api_key)])


@app.get("/health")
def health():
    return {"status": "ok", "service": "vaulteq", "version": "0.3.0"}


@app.get("/")
def root():
    return {
        "name": "VaultEq",
        "version": "0.3.0",
        "modules": ["ledger", "payments", "identity"],
        "docs": "/docs",
    }
