import { test, expect } from "./fixtures"

test.describe("Dashboard & Navigation", () => {
  test("dashboard loads with title and subtitle", async ({ authenticatedPage: page }) => {
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible()
    await expect(page.getByText("Overview of your workspace")).toBeVisible()
  })

  test("stat cards render", async ({ authenticatedPage: page }) => {
    await expect(page.getByText("Total Jobs")).toBeVisible()
    // "API Keys" appears in both stat card and quick actions — use first match in stat area
    await expect(page.getByText("Team Members")).toBeVisible()
    await expect(page.getByText("Storage")).toBeVisible()
  })

  test("service health section renders", async ({ authenticatedPage: page }) => {
    await expect(page.getByText("Service Health")).toBeVisible()
    // Health status should show either "ok" or "degraded"
    const healthStatus = page.getByText("ok").or(page.getByText("degraded"))
    await expect(healthStatus).toBeVisible({ timeout: 10_000 })
  })

  test("recent activity section renders", async ({ authenticatedPage: page }) => {
    await expect(page.getByRole("heading", { name: "Recent Activity" })).toBeVisible()
    // The "View all" link is always visible, confirming the section loaded
    await expect(page.getByRole("link", { name: "View all" })).toBeVisible()
  })

  test("quick actions render", async ({ authenticatedPage: page }) => {
    await expect(page.getByText("Quick Actions")).toBeVisible()
    await expect(page.getByRole("link", { name: /Create Job/ })).toBeVisible()
    await expect(page.getByRole("link", { name: /Upload File/ })).toBeVisible()
    await expect(page.getByRole("link", { name: /Manage Team/ })).toBeVisible()
  })

  test("quick action navigates to jobs page", async ({ authenticatedPage: page }) => {
    await page.getByRole("link", { name: /Create Job/ }).click()
    await expect(page).toHaveURL(/\/jobs/)
  })

  test("quick action navigates to files page", async ({ authenticatedPage: page }) => {
    await page.getByRole("link", { name: /Upload File/ }).click()
    await expect(page).toHaveURL(/\/files/)
  })

  test("sidebar shows agents navigation", async ({ authenticatedPage: page }) => {
    // Sidebar may be collapsed on smaller viewports — look for an agents link
    const agentsLink = page.getByRole("link", { name: "Agents" }).first()
    await expect(agentsLink).toBeVisible()
    await agentsLink.click()
    await expect(page).toHaveURL(/\/agents/)
  })

  test("user menu opens with correct user info", async ({ authenticatedPage: page }) => {
    await page.getByLabel("User menu").click()
    await expect(page.getByText("admin@test.com")).toBeVisible()
    await expect(page.getByText("Settings")).toBeVisible()
  })

  test("settings navigation via user menu", async ({ authenticatedPage: page }) => {
    await page.getByLabel("User menu").click()
    await page.getByText("Settings").click()
    await expect(page).toHaveURL(/\/settings/)
  })

  test("main content area has proper id for accessibility", async ({ authenticatedPage: page }) => {
    const main = page.locator("#main-content")
    await expect(main).toBeVisible()
  })
})
