/**
 * Reference plugin page — copy this when scaffolding a frontend for a new
 * plugin under `frontend/src/apps/<name>/`.
 *
 * To wire a route to this component, create `frontend/src/routes/example.tsx`
 * (TanStack Router file-based) and re-run `npm run build` to regenerate
 * `routeTree.gen.ts`. See `docs/PLUGINS.md` → "Frontend layout".
 */
export function ExamplePage() {
  return (
    <div className="mx-auto max-w-2xl space-y-4 p-6">
      <h1 className="text-2xl font-semibold">Example plugin</h1>
      <p className="text-muted-foreground">
        This page is rendered by the reference plugin. It demonstrates the mirror layout between{" "}
        <code>app/apps/example/</code> and <code>frontend/src/apps/example/</code>.
      </p>
      <p>
        Replace this component with your own UI and import shared primitives from{" "}
        <code>@/components/ui/</code>.
      </p>
    </div>
  )
}
