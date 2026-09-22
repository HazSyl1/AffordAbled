---
name: "AffordAbled Frontend"
description: "Use when creating or changing React, TypeScript, Redux Toolkit, RTK Query, Tailwind CSS, atomic components, pages, hooks, API clients, or frontend tests in apps/web."
applyTo: "apps/web/**/*.{ts,tsx,css}"
---
# Frontend Guidelines

## Folder Structure (Atomic Design)

```text
apps/web/src/
  app/            # store.ts, root providers, router setup
  pages/          # route-level screens composed from features + components
  features/       # one folder per domain feature (e.g. transactions/, accounts/)
    <feature>/
      <feature>Slice.ts        # Redux Toolkit slice (local UI state only)
      <feature>Api.ts          # RTK Query endpoints for this feature
      components/              # feature-specific organisms, not reused elsewhere
  components/
    atoms/        # Button, Input, Icon, Badge — no business logic
    molecules/    # FormField, AmountInput, CategoryPill — composed from atoms
    organisms/    # TransactionList, AccountCard — composed from molecules/atoms
    templates/    # Page layout shells (e.g. DashboardLayout)
  lib/            # apiClient, auth helpers, formatters (money, date), shared types
  styles/         # global.css — Tailwind import + CSS variable design tokens (dark theme)
```

## Component Convention

Every component gets its own folder with typed props:

```text
components/atoms/Button/
  Button.tsx
  Button.types.ts   # only if props are non-trivial; otherwise inline in Button.tsx
  index.ts           # export * from './Button'
```

- Use Tailwind CSS utility classes directly in JSX for all styling. Reference the design tokens defined as CSS variables in `styles/global.css` (`--brand-primary`, `--bg-app`, `--text-primary`, etc.) via Tailwind's arbitrary-value syntax, e.g. `bg-[var(--brand-primary)]`, rather than hardcoding hex values in components.
- No CSS Modules, no separate per-component stylesheet, and no inline `style=` props except for truly dynamic values Tailwind can't express statically.
- Every component's props are an explicit TypeScript `interface` or `type`, never `any` or implicit props.
- Atoms must not import from molecules/organisms/features. Dependencies only point upward (atoms → molecules → organisms → templates → pages).

## State and Data

- Redux Toolkit owns client/UI state (modals, form drafts, capture flow steps). RTK Query owns all server data — no manual `fetch`/`axios` calls and no duplicate server-state caches.
- Model every RTK Query response with a generated or hand-written TypeScript type that mirrors the backend Pydantic schema. Treat API responses as untrusted at the boundary.
- Keep business rules and authorization decisions in FastAPI; the frontend validates only for usability.

## Forms

- Use `react-hook-form` for all form state/handling and `zod` for schema validation, wired together via `@hookform/resolvers/zod`.
- Define each form's `zod` schema next to the form (e.g. `<Form>.schema.ts`), and derive the TypeScript type from it with `z.infer<typeof schema>` instead of hand-writing a duplicate type.
- Mirror backend validation constraints (required fields, min/max, enum values) in the `zod` schema so users get instant feedback, but never treat client-side validation as a substitute for server-side validation.

## General

- Prefer accessible semantic HTML, visible labels, keyboard support, and useful loading, empty, and error states.
- Money values are transported and stored as integer paise; format to INR only at render time.
- Do not place API secrets, Azure keys, or privileged configuration in `VITE_*` variables.