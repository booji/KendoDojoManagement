---
name: frontend
description: React/TypeScript frontend specialist for KendoDojoManagement. Knows the stack (React 19, Vite, TypeScript strict, shadcn/ui, Tailwind v4), mobile-first design requirements, API proxy config, and shadcn component patterns. Use when working on any frontend file, building UI components, adding pages, wiring API calls, or fixing TypeScript errors.
---

# Frontend

## Stack
- React 19, Vite, TypeScript strict mode
- shadcn/ui components + Tailwind v4 via `@tailwindcss/vite`
- Path alias: `@/` → `src/`
- API proxy: `/health` and `/api` → `http://localhost:8000` (dev)

## Adding components
```bash
cd frontend
npx shadcn@latest add <component>   # button, card, form, input, table, etc.
```

## API calls
- Keep all fetch/axios calls in `src/api/` — never inline in components
- Base path `/api/` — the Vite proxy handles dev routing

## Mobile-first rules
- All layouts must work at 375px width (iPhone SE)
- Check-in button must be in the thumb zone (bottom half of screen)
- Use `shadcn` `Button` with `size="lg"` for primary touch targets
- Test layouts at 375px and 1280px before finishing

## Workflow

1. **Read first.** Load relevant source files before any change.
2. Use shadcn/ui components — don't build primitives from scratch.
3. Tailwind utilities only — no custom CSS unless shadcn theme tokens are insufficient.
4. TypeScript strict — no `any`, no unused vars/params.
5. After changes run — must pass with zero errors:
   ```
   npm run build
   ```

## Style rules
- `X | null` not `X | undefined` for optional API fields
- Favour `const` arrow functions for components
- Co-locate component-specific types in the same file
