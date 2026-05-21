import { describe, it, expect } from "vitest"
import { queryClient } from "./query-client"

describe("queryClient", () => {
  it("has correct default query options", () => {
    const defaults = queryClient.getDefaultOptions()
    expect(defaults.queries?.staleTime).toBe(30_000)
    expect(defaults.queries?.retry).toBeTypeOf("function")
    expect(defaults.queries?.refetchOnWindowFocus).toBe(true)
  })

  it("disables mutation retry to prevent duplicate side effects", () => {
    const defaults = queryClient.getDefaultOptions()
    expect(defaults.mutations?.retry).toBe(false)
  })
})
