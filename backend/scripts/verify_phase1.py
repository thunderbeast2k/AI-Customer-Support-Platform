#!/usr/bin/env python3
"""
Phase 1 Verification and Diagnostics Script.
Runs standalone diagnostics on Python environment, Pydantic settings,
PostgreSQL database connection, pgvector extension, and FastAPI routing.

Usage:
    python scripts/verify_phase1.py
"""
import sys
import os
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

def print_section(title: str):
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)

def test_config():
    print_section("1. Verifying Settings & Environment Config")
    try:
        from app.core.config import settings
        print(f"  [OK] Project Name:       {settings.PROJECT_NAME}")
        print(f"  [OK] Version:            {settings.VERSION}")
        print(f"  [OK] Environment:        {settings.ENVIRONMENT}")
        print(f"  [OK] Database Target:    {settings.DATABASE_URL.split('@')[-1] if '@' in settings.DATABASE_URL else settings.DATABASE_URL}")
        print(f"  [OK] Embedding Model:    {settings.EMBEDDING_MODEL_NAME} ({settings.EMBEDDING_DIMENSION}d)")
        print(f"  [OK] LLM Provider:       {settings.LLM_PROVIDER}")
        return True
    except Exception as exc:
        print(f"  [FAIL] Config failed to load: {exc}")
        return False

def test_database():
    print_section("2. Verifying PostgreSQL & pgvector Extension")
    try:
        from app.core.database import check_database_connection
        db_info = check_database_connection()
        status = db_info.get("status")
        latency = db_info.get("latency_ms")
        vector_ok = db_info.get("vector_extension_available")
        
        if status == "healthy":
            print(f"  [OK] Database Status:     HEALTHY (Roundtrip: {latency} ms)")
            if vector_ok:
                print(f"  [OK] pgvector Extension:  AVAILABLE (Version: {db_info.get('vector_extension_version', 'active')})")
            else:
                print(f"  [WARN] pgvector Extension: NOT DETECTED (Run: CREATE EXTENSION IF NOT EXISTS vector;)")
            return True
        else:
            print(f"  [INFO] Database Status:   {status.upper()}")
            print(f"  [INFO] Error details:     {db_info.get('error')}")
            print(f"  [NOTE] If PostgreSQL is not running yet, run: docker compose up -d postgres")
            return False
    except Exception as exc:
        print(f"  [FAIL] Database check failed: {exc}")
        return False

def test_fastapi_app():
    print_section("3. Verifying FastAPI App & Endpoint Routing")
    try:
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)

        # Test /health
        res_health = client.get("/health")
        assert res_health.status_code == 200, f"/health returned {res_health.status_code}"
        print("  [OK] GET /health -> 200 OK")

        # Test /ready
        res_ready = client.get("/ready")
        assert res_ready.status_code == 200, f"/ready returned {res_ready.status_code}"
        print("  [OK] GET /ready -> 200 OK")

        # Test /api/v1/health/system-info
        res_info = client.get("/api/v1/health/system-info")
        assert res_info.status_code == 200, f"/api/v1/health/system-info returned {res_info.status_code}"
        print("  [OK] GET /api/v1/health/system-info -> 200 OK")

        return True
    except ImportError:
        print("  [INFO] TestClient dependencies not fully installed in this shell.")
        print("  [INFO] Run: pip install -r requirements.txt")
        return None
    except Exception as exc:
        print(f"  [FAIL] FastAPI route check failed: {exc}")
        return False

def main():
    print("\nStarting AI Customer Support Platform - Phase 1 Verification")
    cfg_ok = test_config()
    db_ok = test_database()
    app_ok = test_fastapi_app()

    print_section("Phase 1 Diagnostic Summary")
    print(f"  Configuration System:  {'[PASS]' if cfg_ok else '[FAIL]'}")
    print(f"  Database / pgvector:   {'[PASS]' if db_ok else '[PENDING DOCKER START]'}")
    print(f"  FastAPI Routing:       {'[PASS]' if app_ok else ('[NEEDS PIP]' if app_ok is None else '[FAIL]')}")
    print("\nPhase 1 verification script execution finished.\n")

if __name__ == "__main__":
    main()
