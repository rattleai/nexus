import { test, expect } from "./fixtures"

test.describe("Smoke Tests", () => {
  test("app loads and shows login or dashboard", async ({ page }) => {
    await page.goto("/")
    await expect(page).toHaveTitle(/CAD/)
  })

  test("settings/agents page loads when authenticated", async ({ authenticatedPage: page }) => {
    await page.goto("/settings/agents")
    await expect(page.locator("h1").getByText("Agent Workspace")).toBeVisible({ timeout: 10_000 })
  })
})
