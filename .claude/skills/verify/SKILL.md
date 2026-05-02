---
name: verify
description: Run the full test suite in the PostgreSQL test container to verify correctness.
---

# Verify — full test suite

All tests run in the PostgreSQL test container. Do not use local pytest as the verification step.

## Command

From the repo root:

```bash
# First time, or after any change to requirements-dev.txt or Dockerfile:
podman-compose -p kdmtest -f docker-compose.test.yml build test

# Run the full suite:
podman-compose -p kdmtest -f docker-compose.test.yml run --rm test pytest tests/ -q
```

Use `-p kdmtest` to keep the test DB container isolated from the dev stack.

For `docker compose` instead of `podman-compose`:
```bash
docker compose -f docker-compose.test.yml run --rm test pytest tests/ -q
```

## Known permanent skips / open issues

Do not treat these as regressions:

| Test | Status | Reason |
|------|--------|--------|
| `test_pg_isolation::test_pg_fixture_uses_postgresql` | SKIP locally, PASS in container | By design |
| `test_pg_isolation::test_data_isolation_between_tests_a/b` | ERROR | Tracked in #128 |
| `test_ical::test_generate_checkin_token_*` | FAIL | Pre-existing app bug |

## Report

- Pass / fail / error / skip counts
- Any new failures not in the known list above (with full error output)
- Whether all tests passed or action is needed
