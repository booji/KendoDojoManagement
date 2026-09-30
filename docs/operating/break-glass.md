# Break-glass recovery

Use this when the only admin is locked out and has no recovery codes.

```bash
podman exec kendo-app python -m app.cli create-recovery-token <email>
```

This prints a single-use plaintext token valid for **60 minutes**. Redeem it at:

- **API:** `POST /auth/recovery/redeem` — body `{"email": "<email>", "code": "<token>"}`
- **Login page:** enter the email and paste the token into the recovery code field

Security notes:
- Run this command on the server only — never over an untrusted network.
- The token is stored as a bcrypt hash; the plaintext is never persisted.
- Delete the token from your terminal history after use.
