---
name: pre-pr-review
description: Self-review a change before pushing or opening a PR. Use after finishing a task and before running commit-push-pr. Catches dead imports, debug prints, missing migrations, stale generated clients, secrets in diffs, and scope creep before a reviewer sees them.
---

# Pre-PR Review

Read your own diff as if a reviewer wrote it. Catch your own mistakes before someone else has to.

## The checklist

Run through every bullet. If any fails, fix it before proceeding.

### Diff hygiene

- [ ] `git diff --stat` — is the file count proportional to the task? A bugfix touching 40 files is a refactor, not a fix.
- [ ] `git diff` — every changed line traces directly to the task. No "while I was here" edits unless scoped in the task.
- [ ] No debug statements: `print(`, `console.log(`, `pdb.set_trace()`, `debugger`, `# XXX`, `// TODO FIX`.
- [ ] No commented-out code. Delete it; git remembers.
- [ ] No leftover scaffolding: placeholder strings like `"FIXME"`, `"foo"`, `"bar"`, `"TODO"` unless intentional.

### Imports and dead code

- [ ] No unused imports (ruff/biome catch these — confirm they ran).
- [ ] No orphaned functions/variables introduced by this change.
- [ ] Removed imports that your deletion made unused.

### Types

- [ ] Backend: `cd backend && uv run mypy app` clean on changed files.
- [ ] Frontend: `cd frontend && bun x tsc --noEmit` clean.

### Tests

- [ ] New behavior has at least one test exercising it.
- [ ] Bug fix has a test that fails on `main` and passes with the fix.
- [ ] Full suite: `bash scripts/test.sh` passes locally.
- [ ] No `@pytest.mark.skip` or `test.skip()` added without an issue link.

### Backend-specific

- [ ] Model change → `alembic revision --autogenerate` ran, migration file exists, `alembic upgrade head` applied, downgrade tested.
- [ ] New endpoint → registered in `api/main.py`, response model present, auth dep (`SessionDep`, `CurrentUser`) matches the route's intended access.
- [ ] OpenAPI schema changed → `bash scripts/generate-client.sh` ran, `frontend/src/client/` diff is included.
- [ ] No raw SQL where a `sqlmodel.select()` fits.
- [ ] No `session.commit()` outside the expected pattern in `crud.py`.

### Frontend-specific

- [ ] New route → appears in `routeTree.gen.ts`, `beforeLoad` auth guard if behind auth.
- [ ] New component → no inline styles where Tailwind classes fit, shadcn/radix primitives reused where possible.
- [ ] Hooks follow the `use*` naming convention.
- [ ] No direct `axios` calls — use the generated client in `src/client/`.

### Secrets and data

- [ ] No hardcoded credentials, tokens, URLs with auth params, or real user data.
- [ ] `.env` and `.env.*` are untracked (git diff against ignore list).
- [ ] No fixture data includes real emails/names/addresses.

### Commits

- [ ] Commit message describes *why*, not just *what*.
- [ ] No giant "wip" commits that should be squashed first.
- [ ] Co-author trailer present if applicable.

## Output format

When reporting the review:

```
Pre-PR review: <N> items flagged

FAIL: <path>:<line> — <description> — <fix>
WARN: <path>:<line> — <description>
```

If nothing flagged, say `Pre-PR review: clean.`

## Gotchas

- Running `ruff`/`biome` catches style, not logic. Re-read the diff line-by-line anyway.
- A clean `git diff` against origin doesn't mean the branch is clean — check `git diff main...HEAD` for the full branch scope.
- Generated files (`frontend/src/client/`, `routeTree.gen.ts`) often look scary in diffs. Don't revert them — they should match the regenerated state.
- A passing test suite doesn't mean coverage is sufficient. Ask: "did I test the error paths?"
- "It's only a hotfix" is the phrase that precedes the skipped review.
