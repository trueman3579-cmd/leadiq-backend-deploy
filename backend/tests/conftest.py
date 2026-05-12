from __future__ import annotations

import os
import sys

# Make `backend` importable from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Provide required env vars so Settings() can instantiate during test collection
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("ADMIN_USERNAME", "testadmin")
os.environ.setdefault("ADMIN_PASSWORD", "testpassword")

import pytest


def integration_enabled() -> bool:
    return os.getenv("RUN_INTEGRATION_TESTS", "0") == "1"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if integration_enabled():
        return

    skip_integration = pytest.mark.skip(reason="integration tests disabled; set RUN_INTEGRATION_TESTS=1")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)