---
name: security
description: Security reviewer for KendoDojoManagement. Checks OWASP top 10 issues, auth correctness, PII handling, secret management, and injection risks. Use when adding auth, handling member data, changing API boundaries, or when the user mentions "security review", "check for vulnerabilities", or "is this safe".
---

# Security

## Severity levels
- **CRITICAL** — exploitable now, must fix before merge
- **WARNING** — likely problem or bad practice, fix soon
- **INFO** — suggestion or defence-in-depth improvement

## Checklist

### Secrets
- [ ] No hardcoded secrets — all from env vars (`DATABASE_URL`, `JWT_SECRET`, etc.)
- [ ] `.env` is in `.gitignore`; `.env.example` has no real values
- [ ] Default values in code never work in production

### Auth & sessions
- [ ] Every protected route goes through `REQUIRE_MEMBER` / `REQUIRE_ADMIN`, which resolve the cookie to an `auth_sessions` row (ADR-0008) — never trust a cookie or token without that lookup
- [ ] Role and active status read from the Account per request, never snapshotted into a cookie or token
- [ ] Auth Session ids stored only as SHA-256 hashes; revocation is deleting rows
- [ ] Recovery tokens (JWT until #486): signature and `exp` checked, Bearer header only
- [ ] Passkey ceremonies use the `webauthn` library correctly — no hand-rolled crypto
- [ ] No password login exists (#155) — don't add one; passkeys are the only login path
- [ ] Recovery codes and admin recovery tokens hashed with `bcrypt` — no MD5/SHA1/plaintext
- [ ] First-admin claim requires `SETUP_TOKEN`, compared with `secrets.compare_digest` (ADR-0003)

### Input validation
- [ ] All external input goes through a Pydantic model before reaching the DB
- [ ] No raw string interpolation in SQLAlchemy queries — use ORM or bound params
- [ ] File uploads (if any) validated for type and size

### PII protection
- [ ] Member DOB, emergency contact, email never appear in logs
- [ ] Error responses don't leak stack traces or internal field names to the client
- [ ] `parental_consent_obtained` and minor flag not exposed to non-admin roles

### Access control
- [ ] Admin-only endpoints check role — not just authentication
- [ ] Members can only read/write their own records
- [ ] Check-in tokens are session-scoped and expire

### Injection
- [ ] SQLAlchemy ORM used — no `text()` with string formatting
- [ ] No `eval`, `exec`, or `subprocess` with user input

## Open-source self-hosting reminder
This project is deployed by third parties. Any misconfiguration must be safe by default — no "works out of the box with debug=True" or default admin passwords.
