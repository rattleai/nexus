# Example plugin frontend

Mirror of `app/apps/example/` on the frontend side.

```
frontend/src/apps/example/
├── components/
│   └── example-page.tsx
├── hooks/                  (add your own)
└── stores/                 (add your own)
```

Wiring a route is up to your plugin: create
`frontend/src/routes/example.tsx` (TanStack Router file-based) and re-run
`npm run build` to regenerate `routeTree.gen.ts`. See
[`docs/PLUGINS.md`](../../../../docs/PLUGINS.md) for the full layout
contract.
