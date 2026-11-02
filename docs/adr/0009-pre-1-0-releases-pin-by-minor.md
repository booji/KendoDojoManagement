# Before 1.0, releases pin by minor, not major

The project goes public on `0.x`, not `1.0.0`. Until 1.0, `0.Y` stands in for
the major in ADR-0004's promise: a **Breaking change** bumps Y, everything else
(fixes and features alike) bumps the patch, and the documented operator pin is
`:0.Y`. Docs publish as `0.Y.x`. From `1.0.0` on, ADR-0004's major pin (`:1`)
applies unchanged. This amends ADR-0004's pin rule; it does not replace it.

## Context

ADR-0004 makes the pinned tag a promise about when an operator's database and
configuration change shape under them. In SemVer the major is always `0`
before 1.0, so a `:0` pin promises nothing: every breaking change in the 0.x
series would reach an operator on `pull && up -d`. The release workflow and the
docs versioning both derive the pin from the major alone, which is right for
1.x and wrong for 0.x.

## Considered options

**Start at 1.0.0.** Keeps ADR-0004 exactly as written. Rejected: going public
invites contributors and the first outside operators, and the project wants room
to make breaking changes while that settles, without spending a major number on
each.

**0.x pinned by major (`:0`).** No workflow change. Rejected: it is the
`:latest` failure ADR-0004 already rejected, under a different name.

**0.x pinned by minor (chosen).** The common pre-1.0 reading of SemVer.
Features go in the patch, not the minor, so the only reason Y moves is a
Breaking change and `:0.Y` means exactly what `:1` will mean later.

## Consequences

The release workflow's pin and the docs version are computed from major.minor
while the major is `0`, and from the major alone afterwards. Both must switch at
1.0 without anyone remembering to edit them.

Only the latest `0.Y` is supported. A security fix ships as a patch on it, even
when it has to break; such a release says so under a Security heading, and the
upgrade refuses to run until the operator has acted, rather than degrading
silently.

In 0.x a Breaking change may rename or remove a setting outright, provided the
upgrade stops hard on the old one. From 1.0 a rename keeps accepting the old
name with a warning until the next major.

There is no exit criterion for 1.0 yet. Without one, 0.x has no natural end;
deciding it is deferred, not forgotten.
