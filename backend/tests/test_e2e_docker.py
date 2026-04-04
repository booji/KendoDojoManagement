"""
E2E browser/HTTP stubs for Production Docker Compose (Issue #5).

These are xfail(strict=True) stubs — they represent acceptance criteria that
require a live `docker compose up` environment. Promote to real tests after
the implementation is verified end-to-end.

AC mapping:
  AC1 — app + db services defined in docker-compose.yml (file test, see test_docker_config.py)
  AC2 — postgres data volume survives restarts (file test, see test_docker_config.py)
  AC3 — app connects to PostgreSQL via DATABASE_URL (file test, see test_docker_config.py)
  AC4 — .env.example documents all required vars (file test, see test_docker_config.py)
  AC5 — no hardcoded secrets (file test, see test_docker_config.py)
  AC6 — GET /health returns {"status": "ok"} after docker compose up (e2e below)
"""

import httpx
import pytest

DOCKER_APP_BASE_URL = "http://localhost:8000"


# ---------------------------------------------------------------------------
# AC1-AC5: covered by test_docker_config.py (file-based checks)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=False, reason="requires live docker compose environment")
def test_ac1_compose_defines_app_and_db_services() -> None:
    pytest.fail("requires live docker compose environment")


@pytest.mark.xfail(strict=False, reason="requires live docker compose environment")
def test_ac2_postgres_data_survives_restart() -> None:
    pytest.fail("requires live docker compose environment")


@pytest.mark.xfail(strict=False, reason="requires live docker compose environment")
def test_ac3_app_connects_to_postgres_via_database_url() -> None:
    pytest.fail("requires live docker compose environment")


@pytest.mark.xfail(strict=False, reason="requires live docker compose environment")
def test_ac4_env_example_documents_all_required_vars() -> None:
    pytest.fail("requires live docker compose environment")


@pytest.mark.xfail(strict=False, reason="requires live docker compose environment")
def test_ac5_no_hardcoded_secrets() -> None:
    pytest.fail("requires live docker compose environment")


# ---------------------------------------------------------------------------
# AC6: GET /health returns {"status": "ok"} — tested against live dev server
# ---------------------------------------------------------------------------


def test_ac6_health_endpoint_returns_ok() -> None:
    response = httpx.get(f"{DOCKER_APP_BASE_URL}/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
