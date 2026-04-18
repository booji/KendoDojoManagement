# KendoDojoManagement
Managing sessions, members of a kendo dojo

## Break-glass recovery

Use this procedure when the single admin account is locked out and cannot log in.

### When to use it

If the only admin has lost access to their passkey and recovery codes, and there is no other admin who can issue a token via the web UI, you can generate a break-glass token directly on the server.

### How to use it

Run the following command on the server that hosts the app container:

```bash
docker exec kendo-app python -m app.cli create-recovery-token <email>
```

Replace `<email>` with the admin's email address. If the email is found, a single-use plaintext token is printed to stdout. **Protect this token — anyone who obtains it can log in as that user.**

The token expires in **60 minutes**.

### Redeeming the token

Use the printed token to log in via the recovery flow:

- **API:** `POST /auth/recovery/redeem` with body `{"email": "<email>", "code": "<token>"}`
- **Login page:** enter the email and paste the token into the recovery code field

On success you receive a short-lived access token granting a logged-in session.

### Security notes

- Run this command only from the server — never over an untrusted network.
- The token is stored as a bcrypt hash; the plaintext is never persisted.
- Each token is single-use and expires after 60 minutes.
- Treat the printed token like a password and delete it from your terminal history after use.
