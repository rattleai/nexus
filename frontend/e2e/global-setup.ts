/**
 * Global setup for Playwright E2E tests.
 * Clears rate limit and lockout keys from Redis to ensure clean test state.
 * Also sets a high rate limit counter TTL to prevent mid-run rate limiting.
 */
import { execFileSync } from "child_process"

export default function globalSetup() {
  try {
    // Clear ALL rate limit and lockout keys so tests start completely fresh
    execFileSync("docker", [
      "exec",
      "cadprice_cp-redis-1",
      "redis-cli",
      "-a", "changeme",
      "--no-auth-warning",
      "EVAL",
      [
        "local deleted = 0",
        "for _, pattern in ipairs({'rl:*', 'lockout:*'}) do",
        "  local keys = redis.call('KEYS', pattern)",
        "  for _, k in ipairs(keys) do",
        "    redis.call('DEL', k)",
        "    deleted = deleted + 1",
        "  end",
        "end",
        "return deleted",
      ].join("\n"),
      "0",
    ], { stdio: "pipe" })
    console.log("Global setup: Cleared Redis rate limits and lockouts")
  } catch {
    console.warn("Warning: Could not clear Redis rate limits.")
  }
}
