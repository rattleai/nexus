---
name: root-cause
description: Find and fix the root cause instead of the symptom. Use when debugging a bug, failing test, hook rejection, or unexpected behavior. Blocks bypass shortcuts (--no-verify, || true, try/except-swallow, skipping tests, deleting assertions) until the underlying cause is understood.
---

# Root Cause

When something is failing, the instinct is often to make the failure go away. Don't. Understand *why* it fails, then fix the real cause.

ultrathink about the failure before typing.

## The 5-whys loop

1. **Observe** the failure. Exact error, exact command, exact file.
2. **Ask why** it happened.
3. **Answer** with a concrete mechanism (not a guess — a mechanism you can point to in the code or logs).
4. Ask **why that** happened. Repeat until the "why" bottoms out on a design decision, an unchecked assumption, or a bug you can fix.
5. Fix the deepest layer you control.

## Banned shortcuts

These make the failure vanish without fixing it. Reject them unless the user explicitly asks:

- `git commit --no-verify` — hooks exist for a reason. If a hook fails, fix the input, not the hook.
- `pytest -k "not broken_test"` — skipping a failing test hides the signal.
- Deleting an assertion that "just keeps failing."
- `try: ... except Exception: pass` — catches everything, surfaces nothing.
- `|| true` appended to a failing command.
- Commenting out code "to get past this."
- Downgrading a dependency because the new version "is buggy" without reading the changelog.
- `@pytest.mark.skip` without an issue link and a return condition.
- Restarting until it passes. Flakiness is a bug.

## Exception-handling discipline

- Catch the *specific* exception type that can realistically happen.
- Catch only at a boundary where you have a meaningful recovery (retry, fall back to default, surface to user). Otherwise, let it propagate.
- Every `except` must either re-raise, transform to a domain-specific error with `raise X from e`, or record a metric. No silent swallows.

## Workaround policy

Workarounds are acceptable when:

1. The real cause is outside your blast radius (third-party bug, infrastructure) **and**
2. You've identified it **and**
3. You leave a breadcrumb: a TODO with the upstream issue, or a test that will fail when the workaround is no longer needed.

Never workaround something you own.

## Gotchas

- "It works on my machine" usually means an environment assumption. Trace the difference — don't dismiss.
- A flaky test points to a race, a shared-state bug, or time-dependent logic. Rerunning until green is not a fix.
- Pre-commit hook rejecting a file isn't a hook bug — fix the file. If the hook is wrong, fix the hook config in a separate commit.
- `docker compose up` says "healthy" while the app 500s — the healthcheck is too shallow. Read the actual endpoint, not just the status line.
- `alembic upgrade` succeeding doesn't mean the migration is correct — verify the schema and run a query.
