"""
Shared pytest fixtures for backend test suite isolation.
"""
import pytest

from app.main import app
from app.core.database import get_db


@pytest.fixture(autouse=True)
def ensure_module_db_override(request):
    """Ensure each test uses its module's DB override, avoiding cross-module leakage."""
    override = getattr(request.module, "override_get_db", None)
    if override is None:
        yield
        return

    app.dependency_overrides[get_db] = override
    yield
    app.dependency_overrides.pop(get_db, None)
