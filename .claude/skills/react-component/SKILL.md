---
name: react-component
description: Add a React component that matches this codebase's conventions. Use when the user asks to add, build, or scaffold a component, UI element, card, form, dialog, or widget. Produces a component under frontend/src/components/<Group>/ using shadcn/radix primitives and Tailwind v4, plus an optional Playwright spec for interactive components.
argument-hint: "<Group>/<ComponentName>"
paths: ["frontend/src/components/**"]
---

# React Component

Follow the conventions in `frontend/src/components/`. Use shadcn/radix primitives from `components/ui/`, Tailwind v4 classes, `lucide-react` for icons, and the generated API client for data fetching.

## Where it goes

- **Feature-specific** → `components/<FeatureGroup>/<Component>.tsx`. Existing groups: `Admin/`, `Common/`, `Items/`, `Sidebar/`, `UserSettings/`, `Pending/`.
- **Generic reusable primitives** → `components/ui/` (keep shadcn-style — forwardRef, `cn()` for className merging, class-variance-authority for variants).
- **New feature group** → create a directory under `components/` and keep related components, hooks, and types together.

## Template — simple presentational

```tsx
import { cn } from "@/lib/utils"

type Props = {
  title: string
  className?: string
}

export function FeatureCard({ title, className }: Props) {
  return (
    <div className={cn("rounded-lg border p-4", className)}>
      <h3 className="text-lg font-semibold">{title}</h3>
    </div>
  )
}
```

## Template — interactive with data

Use the generated client in `@/client`, TanStack Query, and shadcn primitives:

```tsx
import { useQuery } from "@tanstack/react-query"
import { ItemsService } from "@/client"
import { Button } from "@/components/ui/button"

export function ItemList() {
  const { data, isLoading } = useQuery({
    queryKey: ["items"],
    queryFn: () => ItemsService.readItems(),
  })

  if (isLoading) return <p>Loading...</p>
  return (
    <ul>
      {data?.data.map((item) => <li key={item.id}>{item.title}</li>)}
    </ul>
  )
}
```

## Template — form

Use `react-hook-form` + `zod` via `@hookform/resolvers/zod`. See `components/UserSettings/UserInformation.tsx` for the canonical form.

```tsx
import { zodResolver } from "@hookform/resolvers/zod"
import { useForm } from "react-hook-form"
import { z } from "zod"

const schema = z.object({
  title: z.string().min(1).max(255),
})

type FormData = z.infer<typeof schema>

export function ItemForm() {
  const form = useForm<FormData>({ resolver: zodResolver(schema) })
  const onSubmit = (data: FormData) => { /* mutate via generated client */ }
  return <form onSubmit={form.handleSubmit(onSubmit)}>...</form>
}
```

## Hard rules

- **Use `cn()` from `@/lib/utils`** to merge classNames — not string concatenation.
- **Icons** come from `lucide-react`. Size via className (`size-4`, `size-5`), not props.
- **Buttons** use `<Button>` from `@/components/ui/button`, not raw `<button>` (unless inside `<Button asChild>`).
- **Forms** use react-hook-form + zod. Do not write manual `useState` + onChange handlers for multi-field forms.
- **Data fetching** uses TanStack Query + generated client. Never call `fetch()` or `axios` directly.
- **Mutations** use `useMutation` + `queryClient.invalidateQueries({ queryKey: [...] })`. Don't refetch manually.
- **Toast** messages use `sonner` via `useCustomToast` — see `frontend/src/hooks/useCustomToast.ts`.
- **No inline styles** unless the value is genuinely dynamic (e.g., computed position). Tailwind utility first.
- **Accessible primitives** — radix for dialog, dropdown, tabs, checkbox, tooltip. Don't reinvent.

## Testing

For interactive components (forms, data mutations, routes), add a Playwright spec under `frontend/tests/`:

```ts
test("ItemForm creates an item", async ({ page }) => {
  await page.goto("/items")
  await page.getByRole("button", { name: "New item" }).click()
  await page.getByLabel("Title").fill("Test item")
  await page.getByRole("button", { name: "Save" }).click()
  await expect(page.getByText("Test item")).toBeVisible()
})
```

Purely presentational components don't need tests.

## After scaffolding

1. `cd frontend && bun x biome check --write src/components/<Group>/<Component>.tsx`.
2. `cd frontend && bun x tsc --noEmit`.
3. Verify visually in the browser — render the component in its intended route.
4. If Playwright spec added: `bunx playwright test <spec>`.

## Gotchas

- Importing from `@/components/ui/button` vs `@/components/Button` — the ui/ folder holds shadcn primitives; your feature folders should not duplicate them.
- Using TanStack Query without a `queryKey` matching other components — cache invalidation then targets the wrong entries.
- Forgetting to make a form field `controlled` — react-hook-form silently drops the value.
- Passing `onClick` to a radix primitive that renders as a child — use `asChild` + a child `<button>` to receive the handler.
- `className="flex gap-2"` applied to a component that doesn't forward className — use `forwardRef` and spread rest props for primitives.
