# Security policy

## Reporting a vulnerability

Report it privately through GitHub's
[private vulnerability reporting](https://github.com/booji/KendoDojoManagement/security/advisories/new)
(the **Report a vulnerability** button on the Security tab). Do not open a
public issue or pull request for it.

Say what is affected, how to reproduce it, and what an attacker gains. You will
get an answer in the advisory thread, where the fix is coordinated.

## Supported versions

Only the latest Release line is supported: before 1.0 that is the newest
`0.Y`, the tag operators pin as `:0.Y`. An older line gets no fixes; upgrade to
the latest one.

## How fixes ship

A security fix ships at once as a patch release on the latest Release line,
from a `hotfix/*` branch. A dependency alert that affects the running app takes
the same path.

A security fix may be a Breaking change inside a Release line when there is no
safe way around it. Its release notes then say so under a **Security** heading,
with the operator action, and the upgrade stops until the operator has acted.
It never degrades silently.
