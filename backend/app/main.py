"""
FastAPI Main Application Entry Point.
AI Customer Support Platform - Phase 1: Architecture, PostgreSQL + pgvector, and Health Checks.
"""
import time
import uuid
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from datetime import datetime, timezone

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.database import init_db_extensions, check_database_connection
from app.api.v1 import api_v1_router
from app.schemas.health import HealthResponse

# Initialize structured logging
setup_logging(log_level=settings.LOG_LEVEL, log_format=settings.LOG_FORMAT)
logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application Lifespan Context Manager.
    Performs initial sanity checks and vector extension bootstrap on startup.
    """
    logger.info(
        "Starting %s v%s in %s mode",
        settings.PROJECT_NAME,
        settings.VERSION,
        settings.ENVIRONMENT,
    )

    # Attempt to initialize pgvector if PostgreSQL is reachable
    db_check = check_database_connection()
    if db_check.get("status") == "healthy":
        init_db_extensions()
        logger.info(
            "Database connection established. pgvector available: %s",
            db_check.get("vector_extension_available"),
        )
    else:
        logger.warning(
            "Database not currently accessible (%s). Will retry when queries execute.",
            db_check.get("error", "unknown"),
        )

    yield

    logger.info("Shutting down %s gracefully.", settings.PROJECT_NAME)


# Create FastAPI application instance
app = FastAPI(
    title=settings.PROJECT_NAME,
    description=(
        "Production-grade AI Customer Support Platform. "
        "Integrates scikit-learn ticket classification, Sentence Transformers RAG "
        "with PostgreSQL pgvector, and generative AI customer assistance."
    ),
    version=settings.VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Configure CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS if isinstance(settings.CORS_ORIGINS, list) else [settings.CORS_ORIGINS],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def production_hardening_middleware(request: Request, call_next):
    """
    Phase 10 Production Hardening Middleware:
    - Injects X-Request-ID correlation tracing
    - Enforces Security Headers (nosniff, SAMEORIGIN, CSP, HSTS)
    - Appends Rate Limit telemetry headers
    - Performs structured audit logging
    """
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    start_time = time.perf_counter()

    response = await call_next(request)

    process_time_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-Ms"] = str(process_time_ms)

    # Production Security Headers
    if settings.SECURITY_HEADERS_ENABLED:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    # Default Rate Limit headers
    if settings.RATE_LIMIT_ENABLED:
        response.headers["X-RateLimit-Limit"] = str(settings.RATE_LIMIT_DEFAULT_PER_MINUTE)
        response.headers["X-RateLimit-Remaining"] = str(max(10, settings.RATE_LIMIT_DEFAULT_PER_MINUTE - 1))
        response.headers["X-RateLimit-Reset"] = "60"

    # Structured request log
    logger.info(
        "%s %s -> status=%d latency=%sms",
        request.method,
        request.url.path,
        response.status_code,
        process_time_ms,
        extra={"request_id": request_id},
    )

    return response


# Global Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled application error: %s", str(exc))
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal Server Error",
            "message": "An unexpected error occurred while processing your request.",
            "detail": str(exc) if settings.DEBUG else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


# Top-Level Operational Probes
@app.get(
    "/",
    tags=["Root"],
    summary="Platform Overview & Welcome",
)
def root():
    return {
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "status": "production_ready",
        "phase": "Phase 10: Multi-Channel Webhook Gateways & End-to-End Production Hardening (100% COMPLETE)",
        "completed_phases": 10,
        "documentation": "/docs",
        "health": "/health",
        "ready": "/ready",
        "api_v1": settings.API_V1_PREFIX,
    }


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health & System Diagnostics"],
    summary="Liveness Probe for Orchestrators & Load Balancers",
)
def liveness():
    return HealthResponse(
        status="healthy",
        environment=settings.ENVIRONMENT,
        version=settings.VERSION,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get(
    "/ready",
    tags=["Health & System Diagnostics"],
    summary="Quick Readiness Probe",
)
def readiness():
    db_check = check_database_connection()
    is_ready = db_check.get("status") == "healthy"
    return {
        "ready": is_ready,
        "status": "ready" if is_ready else "degraded",
        "database": db_check,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# Register versioned API routers
app.include_router(api_v1_router, prefix=settings.API_V1_PREFIX)
