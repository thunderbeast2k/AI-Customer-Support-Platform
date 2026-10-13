"""
Database Connection and Session Management Module.
Sets up SQLAlchemy 2.x engine, session factory, pgvector extension initialization,
and database health check utilities.
"""
import logging
import time
from typing import Generator, Dict, Any
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings

logger = logging.getLogger(__name__)

# Base class for SQLAlchemy ORM models
Base = declarative_base()

# SQLAlchemy Engine configured with connection pooling
engine = create_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_pre_ping=True,
    connect_args={"connect_timeout": settings.DATABASE_TIMEOUT_SECONDS},
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields an isolated database session per request
    and guarantees safe closure/rollback on failure.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db_extensions() -> bool:
    """
    Ensures required PostgreSQL extensions (such as pgvector) exist.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.commit()
            logger.info("PostgreSQL pgvector extension verified/enabled.")
            return True
    except SQLAlchemyError as exc:
        logger.warning(
            "Could not enable pgvector extension automatically. Verify user privileges: %s",
            str(exc)
        )
        return False


def check_database_connection() -> Dict[str, Any]:
    """
    Executes a lightweight query to test database connectivity, measure latency,
    and verify pgvector extension availability.
    """
    start_time = time.perf_counter()
    status_info: Dict[str, Any] = {
        "status": "unavailable",
        "latency_ms": 0.0,
        "database": "postgresql",
        "vector_extension_available": False,
        "error": None
    }

    try:
        with engine.connect() as conn:
            # Check basic connection and latency
            conn.execute(text("SELECT 1;"))
            elapsed = (time.perf_counter() - start_time) * 1000.0
            status_info["latency_ms"] = round(elapsed, 2)
            status_info["status"] = "healthy"

            # Check pgvector extension
            try:
                result = conn.execute(
                    text("SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';")
                ).fetchone()
                if result:
                    status_info["vector_extension_available"] = True
                    status_info["vector_extension_version"] = result[1]
                else:
                    # Attempt to check if type vector exists
                    vector_check = conn.execute(
                        text("SELECT typname FROM pg_type WHERE typname = 'vector';")
                    ).fetchone()
                    status_info["vector_extension_available"] = bool(vector_check)
            except Exception as vector_err:
                status_info["vector_extension_available"] = False
                status_info["vector_check_note"] = str(vector_err)

    except Exception as exc:
        elapsed = (time.perf_counter() - start_time) * 1000.0
        status_info["latency_ms"] = round(elapsed, 2)
        status_info["status"] = "unhealthy"
        status_info["error"] = str(exc)
        logger.warning("Database connectivity check failed: %s", str(exc))

    return status_info
