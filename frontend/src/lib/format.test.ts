import { describe, it, expect } from "vitest"
import { formatBytes, formatCompactNumber, formatCurrency, formatDuration, formatDate, formatDateTime, formatPercent } from "./format"

describe("formatBytes", () => {
  it("formats 0 bytes", () => {
    expect(formatBytes(0)).toBe("0 B")
  })

  it("formats bytes", () => {
    expect(formatBytes(500)).toBe("500.0 B")
  })

  it("formats kilobytes", () => {
    expect(formatBytes(1024)).toBe("1.0 KB")
  })

  it("formats megabytes", () => {
    expect(formatBytes(1024 * 1024)).toBe("1.0 MB")
  })

  it("formats gigabytes", () => {
    expect(formatBytes(1024 * 1024 * 1024)).toBe("1.0 GB")
  })

  it("respects precision parameter", () => {
    expect(formatBytes(1536, 2)).toBe("1.50 KB")
  })
})

describe("formatCompactNumber", () => {
  it("formats zero", () => {
    expect(formatCompactNumber(0)).toBe("0")
  })

  it("formats small numbers without abbreviation", () => {
    expect(formatCompactNumber(42)).toBe("42")
  })

  it("formats thousands", () => {
    expect(formatCompactNumber(1500)).toBe("1.5K")
  })

  it("formats millions", () => {
    expect(formatCompactNumber(1_000_000)).toBe("1M")
  })
})

describe("formatCurrency", () => {
  it("formats USD by default", () => {
    const result = formatCurrency(1999)
    expect(result).toContain("1,999")
    expect(result).toContain("$")
  })

  it("formats zero", () => {
    const result = formatCurrency(0)
    expect(result).toContain("0")
  })
})

describe("formatDuration", () => {
  it("returns -- when startedAt is null", () => {
    expect(formatDuration(null, null)).toBe("--")
  })

  it("formats milliseconds", () => {
    const start = "2024-01-01T00:00:00.000Z"
    const end = "2024-01-01T00:00:00.500Z"
    expect(formatDuration(start, end)).toBe("500ms")
  })

  it("formats seconds", () => {
    const start = "2024-01-01T00:00:00Z"
    const end = "2024-01-01T00:00:30Z"
    expect(formatDuration(start, end)).toBe("30s")
  })

  it("formats minutes and seconds", () => {
    const start = "2024-01-01T00:00:00Z"
    const end = "2024-01-01T00:01:30Z"
    expect(formatDuration(start, end)).toBe("1m 30s")
  })
})

describe("formatDate", () => {
  it("formats a date string", () => {
    const result = formatDate("2024-03-15T00:00:00Z")
    expect(result).toContain("Mar")
    expect(result).toContain("15")
    expect(result).toContain("2024")
  })
})

describe("formatDateTime", () => {
  it("formats a datetime string with time", () => {
    const result = formatDateTime("2024-03-15T14:30:00Z")
    expect(result).toContain("Mar")
    expect(result).toContain("15")
    expect(result).toContain("2024")
  })
})

describe("formatPercent", () => {
  it("formats a percentage", () => {
    expect(formatPercent(0.75)).toBe("75%")
  })

  it("formats with precision", () => {
    expect(formatPercent(0.756, 1)).toBe("75.6%")
  })
})
