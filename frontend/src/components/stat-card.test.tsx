import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { StatCard } from "./stat-card"

describe("StatCard", () => {
  it("renders title and value", () => {
    render(<StatCard title="Total Jobs" value={42} />)

    expect(screen.getByText("Total Jobs")).toBeInTheDocument()
    expect(screen.getByText("42")).toBeInTheDocument()
  })

  it("renders string value", () => {
    render(<StatCard title="Storage" value="1.5 GB" />)

    expect(screen.getByText("1.5 GB")).toBeInTheDocument()
  })

  it("renders description when provided", () => {
    render(<StatCard title="Jobs" value={10} description="of 100 limit" />)

    expect(screen.getByText("of 100 limit")).toBeInTheDocument()
  })

  it("renders positive trend", () => {
    render(<StatCard title="Revenue" value="$1,000" trend={{ value: 12, label: "vs last month" }} />)

    expect(screen.getByText("+12%")).toBeInTheDocument()
    expect(screen.getByText("vs last month")).toBeInTheDocument()
  })

  it("renders negative trend", () => {
    render(<StatCard title="Errors" value={5} trend={{ value: -8, label: "vs last week" }} />)

    expect(screen.getByText("-8%")).toBeInTheDocument()
  })

  it("renders without optional props", () => {
    render(<StatCard title="Metric" value={0} />)

    expect(screen.getByText("Metric")).toBeInTheDocument()
    expect(screen.getByText("0")).toBeInTheDocument()
  })
})
