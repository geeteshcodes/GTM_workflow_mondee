"""
backend/main.py
---------------
FastAPI application entry point for the GTM UAE Partner Acquisition Pipeline.

Run from the project root (c:\\geetesh\\aimldl\\m) with:
    conda activate backend
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db.connection import close_pool, init_pool
from backend.api.pipeline import router as pipeline_router
from backend.api.partners import router as partners_router
from backend.api.outreach import router as outreach_router
from backend.api.analytics import router as analytics_router
from backend.api.discovery import router as discovery_router
from backend.api.enrichment import router as enrichment_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan: initialise / teardown DB connection pool
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Startup: initialising PostgreSQL connection pool…")
    try:
        await init_pool()
        logger.info("DB pool ready.")
    except Exception as exc:
        logger.warning(
            "DB pool init failed at startup (%s). "
            "Endpoints will return 503 until the database is reachable. "
            "Create the database with: createdb gtm_uae (or via psql).",
            exc,
        )
    yield
    logger.info("Shutdown: closing PostgreSQL connection pool…")
    try:
        await close_pool()
    except Exception:
        pass
    logger.info("DB pool closed.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="GTM UAE Partner Pipeline API",
    description="Agentic pipeline API: Discovery → Enrichment → Outreach → Onboarding",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow the Next.js dev server (and any local origin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(pipeline_router,   prefix="/api/pipeline",   tags=["Pipeline"])
app.include_router(partners_router,   prefix="/api/partners",   tags=["Partners"])
app.include_router(outreach_router,   prefix="/api/outreach",   tags=["Outreach"])
app.include_router(analytics_router,  prefix="/api/analytics",  tags=["Analytics"])
app.include_router(discovery_router,  prefix="/api/discovery",  tags=["Discovery"])
app.include_router(enrichment_router, prefix="/api/enrichment", tags=["Enrichment"])


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "service": "GTM UAE Pipeline API"}
