---
name: verify-before-done
description: Verify a change actually works before reporting it done. Use when about to claim completion, mark a task finished, or commit. Blocks "looks good to me" claims unless evidence exists — test output, a curl response, a passing assertion, a screenshot.
---

# Verify Before Done

Type checking and compilation verify code *correctness*, not *feature correctness*. Before reporting a task done, produce evidence that the change does what was asked.

## The rule

> No "done" without a verified observation.

An observation is one of:

- A test that exercises the changed path and passes (`uv run pytest <file> -k <test>`).
- A live request against the running service (`curl -sf http://localhost:8000/api/v1/...`).
- A Playwright spec that reproduces the user flow.
- A log line showing the code executed and produced the expected value.
- A manual browser walk-through (for UI changes, state explicitly: "tested in browser at http://localhost:5173/...").

Not observations:

- "It compiles."
- "Types pass."
- "Linting is clean."
- "I believe this is correct."
- "Tests should pass." (Run them.)

## Stack-specific verification

### Backend
- Unit/route test: `cd backend && uv run pytest tests/api/routes/test_<resource>.py -x`
- Full suite: `docker compose exec backend bash scripts/tests-start.sh`
- Endpoint liveness: `curl -sf http://localhost:8000/api/v1/utils/health-check/`
- Behavior: `curl -sf -X POST http://localhost:8000/api/v1/<resource> -H 'Authorization: Bearer ...' -d '...'`
- Migration applied: `docker compose exec db psql -U $POSTGRES_USER -d $POSTGRES_DB -c '\d <table>'`

### Frontend
- Type check: `cd frontend && bun x tsc --noEmit`
- Lint: `bun x biome check`
- e2e: `docker compose up -d --wait backend && bunx playwright test`
- Visual: start dev server, open http://localhost:5173, exercise the feature — **and say what you did**.

## Rules

- If you can't test a UI change in a browser, say so explicitly — do not claim success.
- If the golden path works but an edge case wasn't tested, list the untested edges. Don't hide them.
- If verification would take longer than the change itself, still do it — that's the point.
- `ultrathink` about what "working" means for this specific change before picking a verification method.

## Gotchas

- Running `pytest` with no args when the change is in one file — wastes time and may mask unrelated failures. Target the changed path first, then run the suite.
- Asserting on stdout/logs for code that was never called. Add a `print()` and verify it appears, OR run the matching test.
- Calling `/health` endpoint and calling that a verification of an unrelated change. The endpoint must exercise the changed code.
- "Tests pass" when only 1 of 47 ran due to collection error. Always check the final summary line.
- Frontend changes verified only by TypeScript compiling — tsc catches type bugs, not logic bugs.
