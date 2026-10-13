"""
Health and System Status Pydantic Schemas.
"""
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class DatabaseHealth(BaseModel):
    status: str = Field(..., description="Database connection health status (healthy/unhealthy/unavailable)")
    latency_ms: float = Field(..., description="Query round-trip latency in milliseconds")
    database: str = Field(default="postgresql", description="Target database engine")
    vector_extension_available: bool = Field(..., description="Whether pgvector extension is present")
    vector_extension_version: Optional[str] = Field(None, description="Installed pgvector version")
    error: Optional[str] = Field(None, description="Error message if connection failed")


class ServiceHealth(BaseModel):
    service: str = Field(..., description="Subservice or component identifier")
    status: str = Field(..., description="Service status (operational/degraded/mock)")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Additional diagnostic context")


class HealthResponse(BaseModel):
    status: str = Field(..., description="Overall platform status (healthy/degraded)")
    environment: str = Field(..., description="Current deployment environment")
    version: str = Field(..., description="API semantic version")
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp")


class ReadinessResponse(BaseModel):
    ready: bool = Field(..., description="Indicates whether the pod/container is ready for customer traffic")
    status: str = Field(..., description="Overall readiness status")
    database: DatabaseHealth
    services: Dict[str, ServiceHealth]
    timestamp: str


class SystemInfoResponse(BaseModel):
    project_name: str
    version: str
    api_prefix: str
    environment: str
    embedding_model: str
    embedding_dimension: int
    llm_provider: str
    cors_allowed_origins: list[str]
    phase: str = Field(default="Phase 1: Architecture, PostgreSQL + pgvector, and Health Checks")
