# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | *(none)*             | Maintainer needs to evaluate this issue  |
| `needs-info`               | *(none)*             | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | *(none)*             | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Three roles have no label here, deliberately: this is a single-maintainer
tracker, so an untriaged issue is one the maintainer has not read yet and a
human-only issue is simply one without `ready-for-agent`. A skill asking for
one of those roles should apply no label rather than create one. Edit the
right-hand column if that changes — the mapping describes the tracker, it does
not prescribe to it.

## Kind labels

Orthogonal to the triage roles above, and applied alongside them:

| Label      | Meaning                                              |
| ---------- | ---------------------------------------------------- |
| `bug`      | Something is broken                                  |
| `feature`  | New capability                                       |
| `chore`    | Maintenance, removals, cleanup                       |
| `refactor` | Internal restructuring, no behaviour change          |
| `security` | Security-related                                     |
| `documentation` | Docs only                                       |

Domain labels (`auth`, `sessions`, `members`, `attendance`, `settings`,
`frontend`, `backend`, `infra`) say where the work lands and can be combined
with any of the above.
