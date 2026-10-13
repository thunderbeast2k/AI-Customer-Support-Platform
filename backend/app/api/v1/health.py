"""
Health, Readiness, and System Inspection API Endpoints.
Provides standardized operational endpoints used by Docker, Kubernetes, and frontend dashboards.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, status, Response
from app.core.config import settings
from app.core.database import check_database_connection
from app.schemas.health import (
    HealthResponse,
    ReadinessResponse,
    DatabaseHealth,
    ServiceHealth,
    SystemInfoResponse,
)

router = APIRouter(prefix="/health", tags=["Health & System Diagnostics"])


@router.get(
    "/live",
    response_model=HealthResponse,
    summary="Liveness Probe",
    description="Returns 200 if the FastAPI application process is alive and accepting connections.",
)
def liveness_check() -> HealthResponse:
    return HealthResponse(
        status="healthy",
        environment=settings.ENVIRONMENT,
        version=settings.VERSION,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness Probe with Database & Vector Inspection",
    description="Checks downstream dependencies (PostgreSQL + pgvector) to verify readiness for customer traffic.",
)
def readiness_check(response: Response) -> ReadinessResponse:
    db_check = check_database_connection()
    is_db_healthy = db_check.get("status") == "healthy"

    # Services status
    services = {
        "database": ServiceHealth(
            service="postgresql",
            status="operational" if is_db_healthy else "unavailable",
            details={
                "latency_ms": db_check.get("latency_ms"),
                "vector_extension_available": db_check.get("vector_extension_available"),
                "error": db_check.get("error"),
            },
        ),
        "ml_classifier": ServiceHealth(
            service="scikit-learn",
            status="pending_phase7",
            details={"artifacts_dir": settings.CLASSIFIER_ARTIFACTS_DIR},
        ),
        "embeddings": ServiceHealth(
            service="sentence-transformers",
            status="pending_phase5",
            details={
                "model": settings.EMBEDDING_MODEL_NAME,
                "dimension": settings.EMBEDDING_DIMENSION,
            },
        ),
        "llm_provider": ServiceHealth(
            service=f"llm_{settings.LLM_PROVIDER}",
            status="operational_mock" if settings.LLM_PROVIDER == "mock" else "configured",
            details={"model": settings.LLM_MODEL_NAME},
        ),
    }

    # If database is down in production, respond with 503 Service Unavailable
    # In development/initial bootstrap, we mark ready as false but allow inspection
    is_ready = is_db_healthy
    if not is_ready and settings.ENVIRONMENT == "production":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        ready=is_ready,
        status="ready" if is_ready else "degraded",
        database=DatabaseHealth(
            status=db_check.get("status", "unknown"),
            latency_ms=db_check.get("latency_ms", 0.0),
            database=db_check.get("database", "postgresql"),
            vector_extension_available=db_check.get("vector_extension_available", False),
            vector_extension_version=db_check.get("vector_extension_version"),
            error=db_check.get("error"),
        ),
        services=services,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get(
    "/system-info",
    response_model=SystemInfoResponse,
    summary="Platform System Info and Phase 1 Metadata",
)
def system_info() -> SystemInfoResponse:
    return SystemInfoResponse(
        project_name=settings.PROJECT_NAME,
        version=settings.VERSION,
        api_prefix=settings.API_V1_PREFIX,
        environment=settings.ENVIRONMENT,
        embedding_model=settings.EMBEDDING_MODEL_NAME,
        embedding_dimension=settings.EMBEDDING_DIMENSION,
        llm_provider=settings.LLM_PROVIDER,
        cors_allowed_origins=settings.CORS_ORIGINS if isinstance(settings.CORS_ORIGINS, list) else [settings.CORS_ORIGINS],
        phase="Phase 1: Architecture, PostgreSQL + pgvector, and Health Checks",
    )
