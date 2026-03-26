import { test, expect } from "@playwright/test"

test.describe("Smoke Tests", () => {
  test("app loads and shows login or dashboard", async ({ page }) => {
    await page.goto("/")
    await expect(page).toHaveTitle(/CAD/)
  })

  test("settings/agents page loads", async ({ page }) => {
    await page.goto("/settings/agents")
    // Should see the agent workspace heading or a login redirect
    const heading = page.getByText("Agent Workspace")
    const loginForm = page.locator("form")
    await expect(heading.or(loginForm)).toBeVisible()
  })
})
