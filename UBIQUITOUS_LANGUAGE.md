# Ubiquitous Language

## People

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Admin** | A user with full management rights over members, sessions, and configuration | Sensei, manager, owner |
| **Member** | A registered person who trains at the dojo and has an app account | Student, practitioner, kendoka |
| **Visitor** | A person who attends a session without an app account, recorded by an admin | Guest, drop-in |
| **Coach** | A member flagged as having a coaching role within the dojo | Instructor, teacher |
| **First Aider** | A member flagged as holding a first aid qualification | |

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

## Membership

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Membership Status** | The current standing of a member: active, inactive, or suspended | Account status |
| **Federation Number** | A member's identifier with the national kendo federation | Licence number, membership number |
| **Emergency Contact** | A non-member person designated to be contacted on behalf of a member in an emergency | Next of kin |
| **Parental Consent** | A flag indicating that consent has been obtained from a parent or guardian for an under-18 member | Guardian consent |
| **Minor** | A member whose date of birth indicates they are under 18 years of age | Under-18, child, junior |

## Relationships

- A **Member** holds exactly one current **Grade** and accumulates a **Grade History** over time.
- A **Grade** progresses in strict order: Mukyū → 6-kyū → 5-kyū → 4-kyū → 3-kyū → 2-kyū → 1-kyū → 1-dan → 2-dan → 3-dan → 4-dan → 5-dan → 6-dan → 7-dan → 8-dan.
- A **Session** is either generated from a **Session Template** or created as an **Ad-hoc Session**.
- A **Session** has exactly one **Session Type**.
- **Attendance** at a **Session** is a collection of **Check-ins** by **Members** and named **Visitors**.
- A **Check-in Token** is scoped to exactly one **Session** and expires after use or after the session ends.
- A **Minor** requires a **Parental Consent** flag before being considered fully registered.

## Example dialogue

> **Dev:** "When an **Admin** cancels a **Session**, does that affect the **Session Template**?"

> **Domain expert:** "No — a **Cancellation** only affects that single **Session** instance. The **Session Template** keeps generating future sessions on its normal schedule."

> **Dev:** "And if a **Member** clicks a **Check-in Token** link for a cancelled session?"

> **Domain expert:** "The token should be rejected. A **Check-in** is only valid while the **Session** is in scheduled status."

> **Dev:** "When we record a **Promotion**, who is the awarder?"

> **Domain expert:** "The **Admin** who performs the promotion. It's stored in the **Grade History** alongside the date, so there's always an audit trail of who awarded each **Grade**."

> **Dev:** "Is a **Visitor** the same as a **Member** with no **Grade**?"

> **Domain expert:** "No — a **Visitor** has no app account at all. They appear only in **Attendance** records by name, added manually by an **Admin**. A **Member** always has an account, even if they are **Mukyū**."

## Flagged ambiguities

- **"Grading"** was used in two senses: the event type (a session where grades are awarded) and the act of awarding a grade. Use **Session Type: Grading** for the event and **Promotion** for the act of advancing a member's grade.
- **"Guest"** and **"Visitor"** were used interchangeably in early discussion. The canonical term is **Visitor** — a person who attends without an app account. Avoid "guest".
- **"Rank"** and **"Grade"** were used interchangeably. The canonical term is **Grade** to align with kendo federation terminology.
