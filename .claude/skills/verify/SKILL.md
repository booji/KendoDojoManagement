---
name: verify
description: Run the full test suite to verify correctness. Update the test command in this file once the stack is chosen.
---

Run the project's full test suite and report results.

**Until the stack is decided**, ask the user which test command to run, or check for a test runner config (e.g., pytest.ini, jest.config.*, cargo test, go test ./...) and use the appropriate command.

Once the stack is set, update this skill with the exact command (e.g., `pytest`, `cargo test`, `go test ./...`, `npm test`).

Report:
- Pass/fail summary
- Any failing test names and their error output
- Whether all tests passed or action is needed
