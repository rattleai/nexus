---
name: tdd-loop
description: Test-driven development loop. Use when adding a new feature, fixing a bug, or when asked to write tests first. Enforces RED (write a failing test) → GREEN (minimal code to pass) → REFACTOR (clean up, tests still pass). Stack-aware: pytest for backend, Playwright for frontend.
---

# TDD Loop

Write the test first. Let it fail for the right reason. Write the minimum code to make it pass. Clean up. Repeat.

## The cycle

### RED — write a failing test

Write a test that asserts the new behavior. Run it. **The test must fail**, and it must fail for the reason you expect (not a `NameError` or `ImportError` — an actual assertion).

If the test passes without any implementation, the test is wrong.

### GREEN — minimum code

Write the smallest possible implementation that makes the test pass. Do not write anything the test doesn't require. If you find yourself writing code that isn't driven by the test, stop and add another test first.

### REFACTOR — clean up

With the test green, improve the code without changing behavior. Run tests after every refactor. If a refactor requires loosening a test, the test was wrong — fix it deliberately.

## Backend cycle (pytest)

### RED

```python
# backend/tests/api/routes/test_<resource>.py
def test_create_foo_requires_authentication(client: TestClient) -> None:
    response = client.post("/api/v1/foos/", json={"title": "x"})
    assert response.status_code == 401
```

Run: `docker compose exec backend bash scripts/tests-start.sh tests/api/routes/test_<resource>.py -x`.

Expect: `AssertionError` or 404 (endpoint missing). Not an import error.

### GREEN

Add the route, wire it up, make the test pass. Nothing else.

### REFACTOR

Remove duplication, extract helpers if needed. Tests stay green.

## Frontend cycle (Playwright)

### RED

```ts
// frontend/tests/<feature>.spec.ts
test("user can create an item", async ({ page }) => {
  await page.goto("/items")
  await page.getByRole("button", { name: "New item" }).click()
  await page.getByLabel("Title").fill("My item")
  await page.getByRole("button", { name: "Save" }).click()
  await expect(page.getByText("My item")).toBeVisible()
})
```

Run: `docker compose up -d --wait backend && bunx playwright test <spec>`.

Expect: the locator doesn't find the button or the text never appears.

### GREEN

Build the component and wire the form. Test passes.

### REFACTOR

Extract helpers, hoist repeated locators. Tests stay green.

## Rules

- **One behavior per test.** If it's hard to name the test, the behavior isn't clear — break it up.
- **Arrange-Act-Assert** structure. Make each section obvious.
- **Fixtures over inline setup.** Use `conftest.py` fixtures (backend) and Playwright fixtures (frontend).
- **No conditionals in tests** (`if result:`). If behavior branches, write two tests.
- **No test of implementation detail.** Test observable behavior (HTTP response, rendered DOM, logged message). A refactor should rarely break a test.
- **Fast feedback loops.** Run only the one test file while iterating: `pytest <file> -x` or `playwright test <spec>`.

## Bug-fix variant

For fixing a bug, the RED phase is: write a test that reproduces the bug. It must fail on `main` and pass after your fix. This test lives permanently — the bug regressing means the test breaks.

## Gotchas

- Running the full suite before the one test passes — floods output, hides the real failure. Use `-x` and target the file.
- Writing a test that passes trivially (asserts nothing, or asserts something always true). Red phase must produce a real failure.
- Mocking the thing under test — you're testing your mock, not the code. Mock only true external boundaries (network, clock, random).
- Refactoring while tests are red — you can't tell whether the refactor broke something. Get to green first.
- "The test passes locally" with no record of it having failed first — you wrote green-first without noticing. Delete and rewrite the test.
- Adding `time.sleep()` or `page.waitForTimeout()` to make a test pass — you're papering over a race. Use real waits (`waitFor`, `expect(...).toBeVisible()`).
