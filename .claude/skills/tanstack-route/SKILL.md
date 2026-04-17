---
name: tanstack-route
description: Add a TanStack Router file-based route to the frontend. Use when the user asks to add a page, route, screen, or nav entry. Produces a route file under frontend/src/routes/ following the __root/_layout structure, adds an auth guard where required, and updates the sidebar/nav. Triggers routeTree.gen.ts regeneration on save.
argument-hint: "<path> [--public|--admin]"
paths: ["frontend/src/routes/**", "frontend/src/components/Sidebar/**"]
---

# TanStack Route

Add a route that matches the file-based routing conventions. See `frontend/src/routes/_layout/index.tsx` for the canonical authenticated page and `frontend/src/routes/login.tsx` for a public one.

## File layout

```
frontend/src/routes/
├── __root.tsx               # Top-level layout (don't touch)
├── _layout.tsx              # Auth-guarded layout with sidebar
├── _layout/
│   ├── index.tsx            # "/" dashboard
│   ├── items.tsx            # "/items"
│   ├── admin.tsx            # "/admin"
│   └── settings.tsx         # "/settings"
├── login.tsx                # Public route
├── signup.tsx               # Public route
├── recover-password.tsx
└── reset-password.tsx
```

Rules:

- **Authenticated page** → file goes in `routes/_layout/` so it inherits the sidebar and auth guard from `_layout.tsx`.
- **Public page** → file goes directly in `routes/` (same level as `login.tsx`).
- **Admin-only page** → place in `_layout/` and add a superuser guard in `beforeLoad`.

## Template — authenticated page

`frontend/src/routes/_layout/<name>.tsx`:

```tsx
import { createFileRoute } from "@tanstack/react-router"

export const Route = createFileRoute("/_layout/<name>")({
  component: <Name>,
  head: () => ({
    meta: [{ title: "<Name> - FastAPI Template" }],
  }),
})

function <Name>() {
  return (
    <div>
      {/* content */}
    </div>
  )
}
```

## Template — public page

`frontend/src/routes/<name>.tsx`:

```tsx
import { createFileRoute, redirect } from "@tanstack/react-router"

import { isLoggedIn } from "@/hooks/useAuth"

export const Route = createFileRoute("/<name>")({
  component: <Name>,
  beforeLoad: async () => {
    if (isLoggedIn()) {
      throw redirect({ to: "/" })
    }
  },
})

function <Name>() {
  return <>...</>
}
```

## Template — admin-only page

Add this `beforeLoad` to an authenticated route:

```tsx
beforeLoad: async () => {
  const user = await queryClient.ensureQueryData(userQueryOptions)
  if (!user.is_superuser) {
    throw redirect({ to: "/" })
  }
},
```

See `frontend/src/routes/_layout/admin.tsx` for how existing admin routes do this.

## Sidebar link

Add an entry in `frontend/src/components/Sidebar/AppSidebar.tsx` (or the relevant nav list). Icons come from `lucide-react`. Preserve the existing group structure.

## After scaffolding

1. Vite dev server picks up the new file and regenerates `routeTree.gen.ts` automatically. Verify it did: `git diff frontend/src/routeTree.gen.ts`.
2. `cd frontend && bun x tsc --noEmit` — catches typos in the route string.
3. `cd frontend && bun x biome check --write src/routes/`.
4. Test in browser at http://localhost:5173/<path> — exercise the page, confirm redirects.
5. For behavior-critical routes: add a Playwright spec in `frontend/tests/`.

## Hard rules

- **Route string must match file path.** `routes/_layout/items.tsx` → `createFileRoute("/_layout/items")`.
- **Don't edit `routeTree.gen.ts` by hand** — it's regenerated.
- **Use `@/` aliases** for imports; relative paths (`../..`) are inconsistent with the rest of the codebase.
- **Use the generated client** in `frontend/src/client/` for API calls — never raw `axios`.
- **Auth-dependent data loading** uses TanStack Query's `useQuery` with `queryClient.ensureQueryData` in `beforeLoad` for SSR-like prefetching.

## Gotchas

- Adding a route to `_layout/` but forgetting the underscore → route renders without the sidebar and bypasses the auth guard.
- `beforeLoad` that does async work without awaiting it — redirect fires after the page already renders.
- Hardcoded paths in nav links instead of `<Link to="/route">` — breaks type-safety and causes full-page reloads.
- Saving the new route file but Vite didn't pick it up — restart `bun run dev` and re-check `routeTree.gen.ts`.
- Placing a public route under `_layout/` — it inherits the auth guard and silently redirects logged-out users.
- Using `redirect({ to: "/" })` from inside a component body — only works inside `beforeLoad`/`loader`. In components, use `const navigate = useNavigate()`.
