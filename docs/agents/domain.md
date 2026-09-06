# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`UBIQUITOUS_LANGUAGE.md`** at the repo root: this repo's glossary, and the
  file `/domain-modeling` updates. There is no `CONTEXT.md` and none should be
  created — a second glossary would drift against the one that already exists.
- **`docs/adr/`**: read ADRs that touch the area you're about to work in.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

## File structure

```
/
├── UBIQUITOUS_LANGUAGE.md
├── docs/adr/
│   ├── 0001-single-origin-api-under-api-prefix.md
│   └── 0002-traefik-in-the-dev-stack.md
├── backend/
└── frontend/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `UBIQUITOUS_LANGUAGE.md`, including its "Aliases to avoid" column. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders), but worth reopening because…_
