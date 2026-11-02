# KendoDojoManagement

The language of running one kendo dojo: its members, their grades, the training sessions they attend, and the people who administer it.

## Language

### People

**Member**:
A person on the dojo's roster, with their personal details, grade and membership data. Holds the person's one email address, used both to contact them and to sign in.
_Avoid_: Student, practitioner, kendoka, Member Profile, profile

**Admin**:
A **Member** whose **Account** has full management rights over members, sessions and configuration.
_Avoid_: Sensei, manager, owner

**Visitor**:
A person who attends a **Session** without an **Account**, recorded by an **Admin**.
_Avoid_: Guest, drop-in

**Coach**:
A **Member** flagged as having a coaching role within the dojo.
_Avoid_: Instructor, teacher

**First Aider**:
A **Member** flagged as holding a first aid qualification.

### Authentication and identity

**Account**:
A **Member's** means of signing in: their **Passkeys**, recovery codes and **Role**. Not a person: it always belongs to exactly one **Member**.
_Avoid_: User, login

**Role**:
The permission level of an **Account**: admin or member.
_Avoid_: Permission, access level

**Passkey**:
A credential stored on a device, used to sign in without a password.
_Avoid_: Biometric login, FIDO key

**Auth Session**:
One signed-in device: an **Account** and the **Passkey** it signed in with, until logout, expiry or revocation.
_Avoid_: Session, login session, token

**First-registered Admin**:
The first **Member** on a fresh instance, whose **Member** and **Account** are created together when they claim it, with the admin **Role**.
_Avoid_: Superuser, root user

### Membership

**Membership Status**:
A **Member's** current standing: active, inactive, suspended or archived. Active and inactive **Members** can sign in; suspended and archived ones cannot.
_Avoid_: Account status

**Deactivation**:
Setting a **Member's** **Membership Status** to inactive. The **Member** is kept, not removed.
_Avoid_: Delete, remove, archive

**Federation Number**:
A **Member's** identifier with a national kendo federation.
_Avoid_: Licence number, membership number

**Federation Membership**:
A **Member's** registration with one federation: the federation, their **Federation Number**, and an optional renewal date.
_Avoid_: Affiliation, federation link, member federation

**Emergency Contact**:
A person, not a **Member**, to be contacted on a **Member's** behalf in an emergency.
_Avoid_: Next of kin

**Parental Consent**:
Confirmation that a parent or guardian has consented for a **Minor** to train.
_Avoid_: Guardian consent

**Minor**:
A **Member** under 18, judged from their date of birth at the time it matters.
_Avoid_: Under-18, child, junior

### Grading

**Grade**:
A **Member's** current rank in the standard kendo grading system.
_Avoid_: Rank, level, belt

**Mukyū**:
The **Grade** of a **Member** who has not yet achieved 6-kyū.
_Avoid_: Ungraded, beginner

**Kyū**:
A kyū-level **Grade**, from 6-kyū (lowest) to 1-kyū.
_Avoid_: Kyu grade

**Dan**:
A dan-level **Grade**, from 1-dan to 8-dan (the highest in this system).
_Avoid_: Dan grade

**Promotion**:
Advancing a **Member** from their current **Grade** to the next one.
_Avoid_: Grading, upgrade, advancement

**Grade History**:
The ordered record of every **Promotion** a **Member** has received, with its date and the **Admin** who awarded it.
_Avoid_: Grading history, grade log

### Sessions

**Session**:
A single scheduled training event at the dojo.
_Avoid_: Class, training, practice

**Session Template**:
A recurring rule that generates **Sessions** on a fixed schedule.
_Avoid_: Recurring session, schedule

**Ad-hoc Session**:
A one-off **Session** created directly, not from a **Session Template**.
_Avoid_: Extra session, special session

**Segment**:
A timed block within a **Session**, with a start time and duration, carrying one or more **Session Types**.
_Avoid_: Part, block, section

**Session Type**:
An admin-configured label describing the nature of a **Segment**, such as General Training or Grading.
_Avoid_: Session category, class type

**Cancellation**:
Marking a specific **Session** as not taking place.

### Attendance

**Attendance**:
The record of who was present at a **Session**.
_Avoid_: Register, roll call

**Check-in**:
A **Member** recording their own presence at a **Session**.
_Avoid_: Sign-in, mark attendance

**Check-in Link**:
A **Session's** one public link for checking in. It grants nothing by itself: the **Member** still signs in, and the check-in window still applies.
_Avoid_: Check-in token, sign-in code

**Admin Override**:
An **Admin** adding or removing a **Member's** **Attendance** after the fact.
_Avoid_: Manual attendance, correction

### Settings

**User Settings**:
The configuration every signed-in **Member** has for themselves: **Personal Details** and **Appearance**.
_Avoid_: Settings, when **Dojo Settings** are also in scope

**Personal Details**:
The **Member** details a **Member** can edit themselves: name, date of birth, **Emergency Contact** and **Federation Number**.
_Avoid_: Profile settings

**Appearance**:
The part of **User Settings** holding visual preferences, namely the **Theme**.
_Avoid_: Display settings

**Theme**:
A **Member's** preferred colour scheme: light, dark, or system (following the device).
_Avoid_: Dark mode, colour scheme

**Dojo Settings**:
Configuration for the whole dojo, managed by **Admins**: its name, primary colour and logo.
_Avoid_: Settings, when **User Settings** are also in scope

### Deployment

Environment names rather than domain concepts, pinned here because "production" was ambiguous between two stacks.

**Quick self-host**:
The single-file Compose setup of the app and its database. A supported production path for one dojo, and the one the install docs lead with.
_Avoid_: Prod compose, docker prod

**Hardened deployment**:
The rootless Podman and Quadlet setup, with TLS termination, secrets and automated backups. What an operator graduates to from the **Quick self-host**.
_Avoid_: The Quadlet thing, systemd deploy

**Release image**:
The published application container, pinned by its **Release line**. The app and nothing else: it holds no operator configuration.
_Avoid_: The container, the GHCR image, the build

**Deployment bundle**:
The configuration a host needs beside the **Release image**, extracted from the image itself so the two are always on the same version.
_Avoid_: The repo files, the deploy directory, the checkout

**Release line**:
The series of releases an operator pins to and upgrades within without a **Breaking change**: `0.3` before 1.0, `1` after. Only the latest Release line is supported.
_Avoid_: Major, version, branch

**Breaking change**:
A change an operator cannot take by the routine upgrade alone: it needs a manual step, or it cannot be undone by returning to the previous **Release image**. The REST API is not part of this promise; it ships with its only client.
_Avoid_: Major change, incompatible change

## Relationships

- Every **Account** belongs to exactly one **Member**; a **Member** has at most one **Account**. A **Member** has none until they redeem an invite (or, for the **First-registered Admin**, claim the instance), and none again after erasure.
- An **Account** has exactly one **Role**.
- Only an **Admin** can change a **Member's** email: the dojo cannot verify a self-service change.
- A **Member** holds exactly one current **Grade** and accumulates a **Grade History** over time.
- **Grades** progress in strict order: Mukyū, 6-kyū to 1-kyū, then 1-dan to 8-dan.
- A **Session** is either generated from a **Session Template** or created as an **Ad-hoc Session**.
- A **Session** has one or more **Segments**, and each **Segment** carries one or more **Session Types**, so one evening's keiko can be both Kihon and Keiko.
- **Attendance** at a **Session** is a collection of **Check-ins** by **Members** and named **Visitors**.
- A **Session** has exactly one **Check-in Link**, and it never changes.
- A **Minor** needs **Parental Consent** before being fully registered.
- A **Deactivation** never removes the **Member** or their **Account**.
- When a **Member** becomes suspended or archived, every **Auth Session** they hold stops working.
- A **Member** may hold a **Federation Membership** with each of several federations. An **Admin** manages any **Member's**; a **Member** manages their own.

## Flagged ambiguities

- **"User"** is retired: it sounds like a person, and the person is always the **Member**. The sign-in is the **Account**; "the user's name" means "the **Member's** name". **User Settings** stays as a page name.
- **"Settings"** alone covers both per-member preferences and dojo-wide configuration. Always say **User Settings** or **Dojo Settings**.
- **"Delete"** is never the word for a **Deactivation**, in user-facing text, documentation or discussion, even where an operation is technically called delete.
- **"Profile"** has meant the **Account**, the **Member**, or both. Say **Member**; avoid bare "profile" and the retired "Member Profile".
- **"Session"** is a training event. Signed-in state is an **Auth Session**, always qualified.
- **"Grading"** has meant both the event where grades are awarded and the act of awarding one. Say **Session Type** Grading for the event and **Promotion** for the act.
- **"Guest"** and **"Visitor"** were used interchangeably. Say **Visitor**.
- **"Rank"** and **"Grade"**: say **Grade**, in line with kendo federation terminology.
- **"Production"** meant two different stacks, both supported production paths. Never use it to tell them apart: say **Quick self-host** or **Hardened deployment**.
