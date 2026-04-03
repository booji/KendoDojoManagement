import os

import pytest

# Must be set before any app imports so token.py can read it
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"
