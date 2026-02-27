import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { ServiceStatusGrid } from "./service-status-grid"

// Mock useHealth hook
vi.mock("@/hooks/use-health", () => ({
  useHealth: vi.fn(),
}))

import { useHealth } from "@/hooks/use-health"
const mockUseHealth = vi.mocked(useHealth)

function mockHealth(overrides: Partial<ReturnType<typeof useHealth>>) {
  mockUseHealth.mockReturnValue(overrides as unknown as ReturnType<typeof useHealth>)
}

describe("ServiceStatusGrid", () => {
  it("shows 'checking' state while loading", () => {
    mockHealth({ data: undefined, isLoading: true, isError: false })

    render(<ServiceStatusGrid />)

    expect(screen.getByText("Database")).toBeInTheDocument()
    expect(screen.getByText("Redis")).toBeInTheDocument()
    expect(screen.getByText("Storage")).toBeInTheDocument()
  })

  it("shows 'connected' when all services are healthy", () => {
    mockHealth({
      data: {
        status: "ok",
        version: "0.1.0",
        services: { db: true, redis: true, storage: true },
      },
      isLoading: false,
      isError: false,
    })

    render(<ServiceStatusGrid />)

    const connected = screen.getAllByText("Connected")
    expect(connected).toHaveLength(3)
  })

  it("shows 'unavailable' when a service is down", () => {
    mockHealth({
      data: {
        status: "degraded",
        version: "0.1.0",
        services: { db: true, redis: false, storage: true },
      },
      isLoading: false,
      isError: false,
    })

    render(<ServiceStatusGrid />)

    expect(screen.getAllByText("Connected")).toHaveLength(2)
    expect(screen.getByText("Unavailable")).toBeInTheDocument()
  })

  it("shows all services as 'unavailable' on network error", () => {
    mockHealth({ data: undefined, isLoading: false, isError: true })

    render(<ServiceStatusGrid />)

    const unavailable = screen.getAllByText("Unavailable")
    expect(unavailable).toHaveLength(3)
  })

  it("has accessible role and label", () => {
    mockHealth({ data: undefined, isLoading: true, isError: false })

    render(<ServiceStatusGrid />)

    const grid = screen.getByRole("status")
    expect(grid).toHaveAttribute("aria-label", "Service health status")
  })
})
