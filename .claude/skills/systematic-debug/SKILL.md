---
name: systematic-debug
description: Debug a failing system with a 4-phase method. Use when a test fails intermittently, a service is behaving unexpectedly, an integration is producing wrong results, or when the user says "something's wrong but I don't know what". Enforces reproduce → hypothesize → isolate → verify, with a reproducing test written before any fix.
---

# Systematic Debug

The fastest way to fix a bug is to find it. The fastest way to find it is a method. ultrathink about what you observe before typing.

## Phase 1 — Reproduce

Goal: a deterministic way to trigger the bug. Without this, any "fix" is a guess.

- Write down **exactly** what the user did, what happened, and what was expected.
- Collapse into the smallest input that still reproduces. Fewer moving parts = less to blame.
- **Write it as a failing test.** This is non-negotiable for any non-trivial bug. The test:
  - Fails on `main` / before your fix.
  - Passes after your fix.
  - Stays in the suite permanently as a regression guard.

If you cannot reproduce, stop — you don't understand the bug yet. Gather more information (logs, user steps, environment) before moving on.

## Phase 2 — Hypothesize

State, in one sentence, what you think is wrong and why. Concrete mechanism, not vibes:

- **Weak**: "Probably a race condition."
- **Strong**: "`useEffect` in `ItemForm.tsx:42` runs before `queryClient.invalidateQueries` resolves, so the refetch reads stale data."

If you have multiple hypotheses, rank them by likelihood × ease-to-test. Pick the cheapest one to falsify first.

## Phase 3 — Isolate

Test one hypothesis at a time. Methods, cheapest first:

- **Read the code.** Often the bug is right there once you look.
- **Add a log line** at the suspected site. Re-run the reproducing test. Did the line execute? What was the value?
- **Bisect** — revert half the change, test, iterate. `git bisect` if the bug crossed a commit boundary.
- **Disable half the system.** Comment out one branch, the other, a middleware, a dependency. The one whose absence fixes the bug is the culprit's neighborhood.
- **Run under a debugger** — `pdb.set_trace()` (backend), `debugger;` + browser devtools (frontend), `playwright --debug` (e2e).

When a step refutes the hypothesis, go back to Phase 2 and pick the next one. Don't keep twisting a falsified hypothesis to fit new data.

## Phase 4 — Verify

- The reproducing test now passes.
- The full test suite still passes (run it).
- The bug does not reproduce via the original user steps.
- You can explain, in one sentence, **why** the fix works — i.e. the mechanism of the bug and how the fix blocks it.

If you can't explain why, you patched a symptom. Go back to Phase 2.

## Anti-patterns

- "Fix" that works by coincidence (added a `sleep`, reordered code, retried). Symptom masking.
- Fixing the bug and the reproducing test in the same commit without seeing the test fail. You have no evidence the test would catch a regression.
- Multiple changes bundled together. If the bug returns, you can't bisect.
- "It works now, not sure why" → not done. Understand or mark as unresolved.

## Output format

```
Bug: <one sentence>

Reproduce: <exact steps or test command>

Cause: <mechanism, file:line>

Fix: <what changed and why>

Verification: <commands run, results>
```

## Gotchas

- Heisenbug (goes away when observed) usually means printf/logs changed timing — the real bug is concurrency. Don't "fix" by adding the log permanently.
- Bug reproduces in CI but not locally → environment difference. Compare images, versions, env vars, TZ.
- Reading logs top-down when the real signal is at the bottom — always start with the last error.
- Trusting the error message too literally — the exception site is often downstream of the cause.
- "Not my code" — if it's in the call stack and blocking work, it's your problem until proven otherwise.
