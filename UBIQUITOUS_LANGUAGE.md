# Ubiquitous Language

## People

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Admin** | A user with full management rights over members, sessions, and configuration | Sensei, manager, owner |
| **Member** | A registered person who trains at the dojo; has both a **User** identity and a **Member Profile** | Student, practitioner, kendoka |
| **Visitor** | A person who attends a session without an app account, recorded by an admin | Guest, drop-in |
| **Coach** | A member flagged as having a coaching role within the dojo | Instructor, teacher |
| **First Aider** | A member flagged as holding a first aid qualification | |

## Authentication & Identity

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **User** | The authentication identity in the system; holds credentials, email, and a **Role** | Login, account |
| **Role** | The permission level of a user: either `admin` or `member` | Permission, access level |
| **Passkey** | A WebAuthn credential stored on a device, used for passwordless authentication | Biometric login, FIDO key |
| **Member Profile** | The dojo-domain record linked to a **User**; holds personal details, grade, and membership data | Profile, account, user record |
| **First-registered Admin** | The first **User** to register on a fresh instance, automatically assigned the `admin` **Role** | Superuser, root user |

## Membership

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Membership Status** | The current standing of a member: `active`, `inactive`, or `suspended` | Account status |
| **Deactivation** | Setting a member's **Membership Status** to `inactive`; the record is retained, not removed | Delete, remove, archive |
| **Federation Number** | A member's identifier with the national kendo federation | Licence number, membership number |
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
| **Ad-hoc Session** | A one-off session created directly, not from a template | Extra session, special session |
| **Session Type** | An admin-configurable label describing the nature of a session (e.g. General Training, Grading) | Session category, class type |
| **Cancellation** | The act of marking a specific session instance as not taking place | |

## Attendance

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Attendance** | The record of who was present at a session | Register, roll call |
| **Check-in** | The action a member takes to record their own presence at a session | Sign-in, mark attendance |
| **Check-in Token** | A short-lived, session-scoped URL token an admin shares so members can check in remotely | Check-in link, sign-in code |
| **Admin Override** | An admin manually adding or removing a member's attendance record after the fact | Manual attendance, correction |

## Settings & Preferences

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **User Settings** | Per-user configuration accessible to every authenticated user: **Personal Details** and **Appearance** | Settings (unqualified when dojo settings are also in scope) |
| **Personal Details** | The subset of **Member Profile** fields a user can edit themselves: name, DOB, emergency contact, federation number | Profile settings |
| **Appearance** | The **User Settings** section controlling visual preferences, specifically the **Theme** | Display settings |
| **Theme** | A user's preferred colour scheme: `light`, `dark`, or `system` (follows device preference) | Dark mode, colour scheme |
| **Dojo Settings** | Admin-managed configuration scoped to the whole instance: name, primary colour, logo | Settings (unqualified when user settings are also in scope) |

## Relationships

- A **User** is linked to at most one **Member Profile**; a **User** without a linked profile can self-onboard via **Personal Details** in **User Settings**.
- A **User** has exactly one **Role**: `admin` or `member`.
- A **Member** holds exactly one current **Grade** and accumulates a **Grade History** over time.
- A **Grade** progresses in strict order: Mukyū → 6-kyū → 5-kyū → 4-kyū → 3-kyū → 2-kyū → 1-kyū → 1-dan → 2-dan → 3-dan → 4-dan → 5-dan → 6-dan → 7-dan → 8-dan.
- A **Session** is either generated from a **Session Template** or created as an **Ad-hoc Session**.
- A **Session** has exactly one **Session Type**.
- **Attendance** at a **Session** is a collection of **Check-ins** by **Members** and named **Visitors**.
- A **Check-in Token** is scoped to exactly one **Session** and expires after use or after the session ends.
- A **Minor** requires a **Parental Consent** flag before being considered fully registered.
- A **Deactivation** sets **Membership Status** to `inactive`; it never removes the **Member Profile** or the **User**.

## Example dialogue

> **Dev:** "When an admin 'deletes' a member, what happens to their account?"

> **Domain expert:** "There is no deletion — the operation is a **Deactivation**. The **Member Profile** stays in the database with **Membership Status** set to `inactive`. The **User** identity is also retained so the person could be reactivated later."

> **Dev:** "And what's the difference between the **User** and the **Member Profile**?"

> **Domain expert:** "The **User** is just the login: email, credentials, **Role**. The **Member Profile** is the dojo record: grade, emergency contact, federation number. They're linked, but a **User** can exist before a **Member Profile** is created — for example, the first **Admin** registered before any profiles existed."

> **Dev:** "If I'm building the settings page, should I call it 'User Settings' or just 'Settings'?"

> **Domain expert:** "Call it **User Settings** whenever **Dojo Settings** might also be in scope. Unqualified 'settings' is ambiguous — **User Settings** covers personal details and appearance; **Dojo Settings** covers dojo-wide configuration like name and colours."

> **Dev:** "What **Theme** does a new member see?"

> **Domain expert:** "**System** — the device preference is the default. The member can override it to `light` or `dark` in **Appearance**, and that choice is saved to their account so it follows them across devices."

> **Dev:** "When we record a **Promotion**, who is the awarder?"

> **Domain expert:** "The **Admin** who performs the promotion. It's stored in the **Grade History** alongside the date, so there's always an audit trail of who awarded each **Grade**."

## Flagged ambiguities

- **"User" vs "Member"**: Throughout the codebase and conversation, "user" is sometimes used generically to mean any person using the app. It has a precise meaning here: **User** = auth identity. **Member** = dojo profile. A sentence like "the user's name" is ambiguous — use "the **Member's** name" or "the **User's** email" to be precise.
- **"Settings"**: Used unqualified for both per-user preferences and dojo-wide configuration. Always qualify: **User Settings** or **Dojo Settings**.
- **"Delete" vs "Deactivate"**: The API endpoint `DELETE /members/{id}` performs a **Deactivation**, not a deletion. The word "delete" must not be used for this operation in any user-facing text, documentation, or domain discussion.
- **"Profile"**: Used loosely to mean the auth account, the member record, or both. The canonical term for the dojo record is **Member Profile**. Avoid bare "profile".
- **"Grading"**: Used in two senses — the event type (a session where grades are awarded) and the act of awarding a grade. Use **Session Type: Grading** for the event and **Promotion** for the act.
- **"Guest"** and **"Visitor"**: Used interchangeably in early discussion. The canonical term is **Visitor**.
- **"Rank"** and **"Grade"**: The canonical term is **Grade**, to align with kendo federation terminology.
