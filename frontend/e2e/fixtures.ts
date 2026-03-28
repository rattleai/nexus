import { test as base, expect, type Page } from "@playwright/test"
import { execFileSync } from "child_process"

export const TEST_USER = {
  email: "admin@test.com",
  password: "TestPass123",
  displayName: "Dev Admin",
}

/** Clear auth rate limits and lockouts from Redis. */
function clearRateLimits() {
  try {
    execFileSync("docker", [
      "exec", "cadprice_cp-redis-1",
      "redis-cli", "-a", "changeme", "--no-auth-warning",
      "EVAL",
      "for _,p in ipairs({'rl:auth*','lockout:*'}) do for _,k in ipairs(redis.call('KEYS',p)) do redis.call('DEL',k) end end return 0",
      "0",
    ], { stdio: "pipe" })
  } catch {
    // Ignore — tests may still work
  }
}

/**
 * Log in via the UI to establish a full browser session.
 * Clears rate limits before login to avoid 429s during test runs.
 */
async function login(page: Page) {
  clearRateLimits()

  await page.goto("/login")
  await page.getByLabel("Email").fill(TEST_USER.email)
  await page.getByLabel("Password").fill(TEST_USER.password)
  await page.getByRole("button", { name: "Sign In" }).click()

  await page.waitForSelector("text=Dashboard", { timeout: 20_000 })
}

/**
 * Extended test fixture that provides an authenticated page.
 */
export const test = base.extend<{ authenticatedPage: Page }>({
  authenticatedPage: async ({ page }, use) => {
    await login(page)
    await use(page)
  },
})

export { expect }
