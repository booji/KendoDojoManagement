"""E2E stub for issue #108: docker-compose.test.yml brings up watcher + postgres."""

import pytest


@pytest.mark.xfail(strict=True, reason="not implemented: requires live compose stack")
def test_docker_compose_test_yml_brings_up_watcher_and_postgres() -> None:
    assert False, "not implemented"
