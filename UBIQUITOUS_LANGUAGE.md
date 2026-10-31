# Ubiquitous Language

## People

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Admin** | A **Member** whose **Account** has full management rights over members, sessions, and configuration | Sensei, manager, owner |
| **Member** | A person on the dojo's roster: personal details, grade and membership data. Holds the person's one email address, used both to contact them and to sign in. Has at most one **Account** — none until they register, and none again after erasure | Student, practitioner, kendoka, Member Profile, profile |
| **Visitor** | A person who attends a session without an app account, recorded by an admin | Guest, drop-in |
| **Coach** | A member flagged as having a coaching role within the dojo | Instructor, teacher |
| **First Aider** | A member flagged as holding a first aid qualification | |

## Authentication & Identity

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Account** | A **Member's** means of signing in: their **Passkeys**, recovery codes and **Role**. Not a person — it always belongs to exactly one **Member**, and signs in with that Member's email | User, login |
| **Role** | The permission level of an **Account**: either `admin` or `member` | Permission, access level |
| **Passkey** | A WebAuthn credential stored on a device, used for passwordless authentication | Biometric login, FIDO key |
| **Auth Session** | One signed-in device: an **Account** and the **Passkey** it signed in with, until logout, expiry or revocation. Stored as a row in `auth_sessions`; the cookie holds only its random id | Session, login session, token |
| **First-registered Admin** | The first **Member** to register on a fresh instance: their **Member** and **Account** are created together when they claim it, with the `admin` **Role** | Superuser, root user |

## Membership

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Membership Status** | The current standing of a member: `active`, `inactive`, `suspended`, or `archived`. It also decides sign-in: `active` and `inactive` Members can sign in; `suspended` and `archived` Members cannot, and any **Auth Session** they hold stops working on its next request | Account status |
| **Deactivation** | Setting a member's **Membership Status** to `inactive`; the record is retained, not removed | Delete, remove, archive |
| **Federation Number** | A member's identifier with the national kendo federation | Licence number, membership number |
| **Federation Membership** | A member's registration with one **Federation**: the federation, their **Federation Number**, and an optional renewal date | Affiliation, federation link, member federation |
| **Emergency Contact** | A non-member person designated to be contacted on behalf of a member in an emergency | Next of kin |
| **Parental Consent** | A flag indicating that consent has been obtained from a parent or guardian for an under-18 member | Guardian consent |
| **Minor** | A member whose date of birth indicates they are under 18 years of age; derived at read-time, never stored | Under-18, child, junior |

## Grading

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Grade** | A member's current rank in the standard kendo grading system | Rank, level, belt |
| **Mukyū** | The grade assigned to an ungraded member who has not yet achieved 6-kyū | Ungraded, beginner |
| **Kyū** | A kyu-level grade; ranges from 6-kyū (lowest) to 1-kyū | Kyu grade |
| **Dan** | A dan-level grade; ranges from 1-dan (lowest) to 8-dan (highest in this system) | Dan grade |
| **Promotion** | The act of advancing a member from their current grade to the next valid grade | Grading, upgrade, advancement |
| **Grade History** | The ordered record of all promotions a member has received, including date and awarder | Grading history, grade log |

## Sessions

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Session** | A single scheduled training event at the dojo | Class, training, practice |
| **Session Template** | A recurring rule that generates sessions on a fixed schedule | Recurring session, schedule |
| **Segment** | A timed block within a **Session** — start time and duration — carrying one or more **Session Types** | Part, block, section |
| **Ad-hoc Session** | A one-off session created directly, not from a template | Extra session, special session |
| **Session Type** | An admin-configurable label describing the nature of a session (e.g. General Training, Grading) | Session category, class type |
| **Cancellation** | The act of marking a specific session instance as not taking place | |

## Attendance

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Attendance** | The record of who was present at a session | Register, roll call |
| **Check-in** | The action a member takes to record their own presence at a session | Sign-in, mark attendance |
| **Check-in Link** | The one public link a **Session** has for checking in. Stable and tokenless: it grants nothing by itself — the member still signs in, and the check-in window still applies | Check-in token, sign-in code |
| **Admin Override** | An admin manually adding or removing a member's attendance record after the fact | Manual attendance, correction |

## Settings & Preferences

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **User Settings** | Per-user configuration accessible to every authenticated user: **Personal Details** and **Appearance** | Settings (unqualified when dojo settings are also in scope) |
| **Personal Details** | The subset of **Member** fields a Member can edit themselves: name, DOB, emergency contact, federation number | Profile settings |
| **Appearance** | The **User Settings** section controlling visual preferences, specifically the **Theme** | Display settings |
| **Theme** | A Member's preferred colour scheme: `light`, `dark`, or `system` (follows device preference) | Dark mode, colour scheme |
| **Dojo Settings** | Admin-managed configuration scoped to the whole instance: name, primary colour, logo | Settings (unqualified when user settings are also in scope) |

## Relationships

- Every **Account** belongs to exactly one **Member**; a **Member** has at most one **Account**. There is no sign-in without a kendoka behind it.
- An **Account** has exactly one **Role**: `admin` or `member`.
- Only an **Admin** can change a **Member's** email: the app sends no mail, so a self-service change could not be verified.
- A **Member** holds exactly one current **Grade** and accumulates a **Grade History** over time.
- A **Grade** progresses in strict order: Mukyū → 6-kyū → 5-kyū → 4-kyū → 3-kyū → 2-kyū → 1-kyū → 1-dan → 2-dan → 3-dan → 4-dan → 5-dan → 6-dan → 7-dan → 8-dan.
- A **Session** is either generated from a **Session Template** or created as an **Ad-hoc Session**.
- A **Session** has one or more **Segments**, and each **Segment** carries one or more **Session Types** — so a single evening keiko can be both Kihon and Keiko.
- **Attendance** at a **Session** is a collection of **Check-ins** by **Members** and named **Visitors**.
- A **Session** has exactly one **Check-in Link**, and it never changes.
- A **Minor** requires a **Parental Consent** flag before being considered fully registered.
- A **Deactivation** sets **Membership Status** to `inactive`; it never removes the **Member** or their **Account**.
- A **Member** may hold a **Federation Membership** with each of several **Federations**; an **Admin** manages any member's, a **Member** manages their own, and both go through the same card.

## Deployment

These are environment names rather than domain concepts, but they are used
constantly in discussion and "production" was ambiguous between two different
stacks, so they are pinned here.

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Hardened deployment** | The rootless Podman + Quadlet stack in `deploy/quadlet`: Traefik terminating TLS, `kendo-app`, and `kendo-db` across the `kendo-edge` and `kendo-backend` networks, Podman secrets and automated backups. What an operator graduates to from the **quick self-host** | The Quadlet thing, systemd deploy |
| **Quick self-host** | The Compose stack in `docker-compose.yml`: the same app and database images with a simpler single-file setup. A supported production path for a single dojo, and the one the install docs lead with | Prod compose, docker prod |
| **Release image** | The published application container, `ghcr.io/booji/kendodojomanagement`, pinned by its **major** tag (`:1`). The app and nothing else — it holds no operator config | The container, the GHCR image, the build |
| **Deployment bundle** | The config a host needs alongside the **Release Image**: `docker-compose.yml`, `.env.example`, the Traefik `.example` files, the Quadlet units, the backup scripts and `setup.sh`. Extracted from the image (`podman run --rm <image> init`), so it is always on the same version as the image it configures | The repo files, the deploy directory, the checkout |

## Example dialogue

> **Dev:** "When an admin 'deletes' a member, what happens to their account?"

> **Domain expert:** "There is no deletion — the operation is a **Deactivation**. The **Member** stays in the database with **Membership Status** set to `inactive`. Their **Account** is also retained so they could be reactivated later."

> **Dev:** "And what's the difference between the **Account** and the **Member**?"

> **Domain expert:** "The **Member** is the kendoka: name, email, grade, emergency contact. The **Account** is just how they sign in: passkeys and a **Role**. Every **Account** belongs to a **Member**, but most **Members** on the roster never sign in, so they have none."

> **Dev:** "If I'm building the settings page, should I call it 'User Settings' or just 'Settings'?"

> **Domain expert:** "Call it **User Settings** whenever **Dojo Settings** might also be in scope. Unqualified 'settings' is ambiguous — **User Settings** covers personal details and appearance; **Dojo Settings** covers dojo-wide configuration like name and colours."

> **Dev:** "What **Theme** does a new member see?"

> **Domain expert:** "**System** — the device preference is the default. The member can override it to `light` or `dark` in **Appearance**, and that choice is saved to their account so it follows them across devices."

> **Dev:** "When we record a **Promotion**, who is the awarder?"

> **Domain expert:** "The **Admin** who performs the promotion. It's stored in the **Grade History** alongside the date, so there's always an audit trail of who awarded each **Grade**."

## Flagged ambiguities

- **"User"**: Retired as a domain term (#418) because it sounds like a person, and the person is always the **Member**. The sign-in is the **Account** (the code followed in #436). "The user's name" means "the **Member's** name". **User Settings** stays as a page name.
- **"Settings"**: Used unqualified for both per-user preferences and dojo-wide configuration. Always qualify: **User Settings** or **Dojo Settings**.
- **"Delete" vs "Deactivate"**: The API endpoint `DELETE /members/{id}` performs a **Deactivation**, not a deletion. The word "delete" must not be used for this operation in any user-facing text, documentation, or domain discussion.
- **"Profile"**: Used loosely to mean the auth account, the member record, or both. The canonical term for the dojo record is **Member**. Avoid bare "profile" and the retired "Member Profile".
- **"Session"**: A **Session** is a training event. Signed-in state is an **Auth Session**, always qualified, in code and discussion alike (#455).
- **"Grading"**: Used in two senses — the event type (a session where grades are awarded) and the act of awarding a grade. Use **Session Type: Grading** for the event and **Promotion** for the act.
- **"Guest"** and **"Visitor"**: Used interchangeably in early discussion. The canonical term is **Visitor**.
- **"Rank"** and **"Grade"**: The canonical term is **Grade**, to align with kendo federation terminology.
- **"Production"**: Meant two different stacks — the Quadlet units in `deploy/quadlet` and the Compose file in `docker-compose.yml`. Both are supported production paths, so never use "production" to tell them apart: say **quick self-host** or **hardened deployment**.
