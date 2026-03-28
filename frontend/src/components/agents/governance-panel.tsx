import * as React from "react"
import { Save, Shield, DollarSign, Clock, Lock, AlertTriangle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useUpdateAgent, useCapabilityCatalog } from "@/hooks/use-agents"
import type { AgentDefinition, GovernancePolicy } from "@/types/agents"
import { toast } from "sonner"

const TOOL_NAME_PATTERN = /^[a-z][a-z0-9_]{0,63}$/
const RISK_COLORS: Record<string, string> = {
  low: "border-green-500/50 text-green-600 dark:text-green-400",
  medium: "border-yellow-500/50 text-yellow-600 dark:text-yellow-400",
  high: "border-orange-500/50 text-orange-600 dark:text-orange-400",
  critical: "border-red-500/50 text-red-600 dark:text-red-400",
}

interface GovernancePanelProps {
  agent: AgentDefinition
}

export function GovernancePanel({ agent }: GovernancePanelProps) {
  const updateAgent = useUpdateAgent()
  const { data: catalog } = useCapabilityCatalog()
  const policy = (agent.governance_policy ?? {}) as GovernancePolicy

  const [maxRunSpend, setMaxRunSpend] = React.useState(
    policy.max_spend_per_run_usd?.toString() ?? "",
  )
  const [maxDaySpend, setMaxDaySpend] = React.useState(
    policy.max_spend_per_day_usd?.toString() ?? "",
  )
  const [maxMonthSpend, setMaxMonthSpend] = React.useState(
    policy.max_spend_per_month_usd?.toString() ?? "",
  )
  const [deniedTools, setDeniedTools] = React.useState<string[]>(
    policy.denied_tools ?? [],
  )
  const [requireApproval, setRequireApproval] = React.useState<string[]>(
    policy.require_approval_for ?? [],
  )
  const [approvalTimeout, setApprovalTimeout] = React.useState(
    policy.approval_timeout_seconds?.toString() ?? "300",
  )
  const [approvalDefault, setApprovalDefault] = React.useState(
    policy.approval_default_action ?? "deny",
  )
  const [maxRpm, setMaxRpm] = React.useState(
    policy.max_requests_per_minute?.toString() ?? "",
  )
  const [deniedCapabilities, setDeniedCapabilities] = React.useState<string[]>(
    (policy as Record<string, unknown>).denied_capabilities as string[] ?? [],
  )
  const [approvalCapabilities, setApprovalCapabilities] = React.useState<string[]>(
    (policy as Record<string, unknown>).require_approval_for_capabilities as string[] ?? [],
  )
  const [toolInput, setToolInput] = React.useState("")
  const [approvalInput, setApprovalInput] = React.useState("")

  React.useEffect(() => {
    const p = (agent.governance_policy ?? {}) as GovernancePolicy
    setMaxRunSpend(p.max_spend_per_run_usd?.toString() ?? "")
    setMaxDaySpend(p.max_spend_per_day_usd?.toString() ?? "")
    setMaxMonthSpend(p.max_spend_per_month_usd?.toString() ?? "")
    setDeniedTools(p.denied_tools ?? [])
    setRequireApproval(p.require_approval_for ?? [])
    setApprovalTimeout(p.approval_timeout_seconds?.toString() ?? "300")
    setApprovalDefault(p.approval_default_action ?? "deny")
    setMaxRpm(p.max_requests_per_minute?.toString() ?? "")
    setDeniedCapabilities((p as Record<string, unknown>).denied_capabilities as string[] ?? [])
    setApprovalCapabilities((p as Record<string, unknown>).require_approval_for_capabilities as string[] ?? [])
  }, [agent])

  const isDirty =
    maxRunSpend !== (policy.max_spend_per_run_usd?.toString() ?? "") ||
    maxDaySpend !== (policy.max_spend_per_day_usd?.toString() ?? "") ||
    maxMonthSpend !== (policy.max_spend_per_month_usd?.toString() ?? "") ||
    JSON.stringify([...deniedTools].sort()) !== JSON.stringify([...(policy.denied_tools ?? [])].sort()) ||
    JSON.stringify([...requireApproval].sort()) !== JSON.stringify([...(policy.require_approval_for ?? [])].sort()) ||
    approvalTimeout !== (policy.approval_timeout_seconds?.toString() ?? "300") ||
    approvalDefault !== (policy.approval_default_action ?? "deny") ||
    maxRpm !== (policy.max_requests_per_minute?.toString() ?? "") ||
    JSON.stringify([...deniedCapabilities].sort()) !== JSON.stringify([...((policy as Record<string, unknown>).denied_capabilities as string[] ?? [])].sort()) ||
    JSON.stringify([...approvalCapabilities].sort()) !== JSON.stringify([...((policy as Record<string, unknown>).require_approval_for_capabilities as string[] ?? [])].sort())

  const handleSave = async () => {
    const timeoutVal = Number(approvalTimeout)
    const newPolicy: GovernancePolicy = {
      ...policy,
      max_spend_per_run_usd: maxRunSpend ? Number(maxRunSpend) : null,
      max_spend_per_day_usd: maxDaySpend ? Number(maxDaySpend) : null,
      max_spend_per_month_usd: maxMonthSpend ? Number(maxMonthSpend) : null,
      denied_tools: deniedTools,
      require_approval_for: requireApproval,
      approval_timeout_seconds: timeoutVal >= 1 ? timeoutVal : 300,
      approval_default_action: approvalDefault as "deny" | "approve",
      max_requests_per_minute: maxRpm ? Number(maxRpm) : null,
      denied_capabilities: deniedCapabilities,
      require_approval_for_capabilities: approvalCapabilities,
    }

    try {
      await updateAgent.mutateAsync({
        id: agent.id,
        data: {
          governance_policy: newPolicy,
          expected_version: agent.version,
        },
      })
    } catch {
      // Error toast handled by mutation onError
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <Shield className="h-5 w-5 text-primary" />
            Governance & Policies
          </h3>
          <p className="text-sm text-muted-foreground mt-0.5">
            Control spending, access, and approval workflows for this agent.
          </p>
        </div>
        <Button onClick={handleSave} disabled={updateAgent.isPending || !isDirty} size="sm">
          <Save className="mr-1.5 h-3.5 w-3.5" />
          {updateAgent.isPending ? "Saving..." : "Save Policies"}
        </Button>
      </div>

      {/* Spending Limits */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <DollarSign className="h-4 w-4" />
            Spending Limits
          </CardTitle>
          <CardDescription className="text-xs">
            Set cost guardrails to prevent runaway spending. Leave empty for
            unlimited.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label htmlFor="gov-run-spend">Per Run ($)</Label>
              <Input
                id="gov-run-spend"
                type="number"
                step="0.01"
                min="0"
                value={maxRunSpend}
                onChange={(e) => setMaxRunSpend(e.target.value)}
                placeholder="No limit"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="gov-day-spend">Per Day ($)</Label>
              <Input
                id="gov-day-spend"
                type="number"
                step="0.01"
                min="0"
                value={maxDaySpend}
                onChange={(e) => setMaxDaySpend(e.target.value)}
                placeholder="No limit"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="gov-month-spend">Per Month ($)</Label>
              <Input
                id="gov-month-spend"
                type="number"
                step="0.01"
                min="0"
                value={maxMonthSpend}
                onChange={(e) => setMaxMonthSpend(e.target.value)}
                placeholder="No limit"
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Rate Limits */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <Clock className="h-4 w-4" />
            Rate Limits
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <Label htmlFor="gov-rpm">Max Requests per Minute</Label>
            <Input
              id="gov-rpm"
              type="number"
              min="1"
              max="10000"
              value={maxRpm}
              onChange={(e) => setMaxRpm(e.target.value)}
              placeholder="No limit"
              className="max-w-xs"
            />
          </div>
        </CardContent>
      </Card>

      {/* Capability Access Control */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <Lock className="h-4 w-4" />
            Denied Capabilities
          </CardTitle>
          <CardDescription className="text-xs">
            Block entire capability groups or individual tools from being used.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {catalog && (
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Block by capability</Label>
              <div className="flex flex-wrap gap-1.5">
                {catalog.domains.flatMap((d) =>
                  d.capabilities.map((cap) => {
                    const isDenied = deniedCapabilities.includes(cap.slug)
                    return (
                      <Badge
                        key={cap.slug}
                        variant={isDenied ? "destructive" : "outline"}
                        className={`cursor-pointer text-[10px] transition-colors ${
                          !isDenied ? "hover:bg-destructive/10" : ""
                        }`}
                        onClick={() => {
                          if (isDenied) {
                            setDeniedCapabilities(deniedCapabilities.filter((c) => c !== cap.slug))
                          } else {
                            setDeniedCapabilities([...deniedCapabilities, cap.slug])
                          }
                        }}
                      >
                        {cap.label}
                        {isDenied && <span className="ml-1">&times;</span>}
                      </Badge>
                    )
                  })
                )}
              </div>
            </div>
          )}

          <Separator />
          <Label className="text-xs text-muted-foreground">Block individual tools</Label>
          <div className="flex gap-2">
            <Input
              value={toolInput}
              onChange={(e) => setToolInput(e.target.value)}
              placeholder="Tool name to deny..."
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault()
                  const trimmed = toolInput.trim()
                  if (!trimmed) return
                  if (!TOOL_NAME_PATTERN.test(trimmed)) {
                    toast.error("Tool name must be lowercase alphanumeric with underscores, starting with a letter (max 64 chars)")
                    return
                  }
                  if (!deniedTools.includes(trimmed)) {
                    setDeniedTools([...deniedTools, trimmed])
                  }
                  setToolInput("")
                }
              }}
            />
            <Button
              variant="outline"
              onClick={() => {
                const trimmed = toolInput.trim()
                if (!trimmed) return
                if (!TOOL_NAME_PATTERN.test(trimmed)) {
                  toast.error("Tool name must be lowercase alphanumeric with underscores, starting with a letter (max 64 chars)")
                  return
                }
                if (!deniedTools.includes(trimmed)) {
                  setDeniedTools([...deniedTools, trimmed])
                }
                setToolInput("")
              }}
            >
              Add
            </Button>
          </div>
          {deniedTools.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {deniedTools.map((tool) => (
                <Badge
                  key={tool}
                  variant="destructive"
                  className="cursor-pointer"
                  onClick={() => setDeniedTools(deniedTools.filter((t) => t !== tool))}
                >
                  {tool} &times;
                </Badge>
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              No denied tools. All allowed tools can be used.
            </p>
          )}
        </CardContent>
      </Card>

      {/* Human-in-the-Loop Approval */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <AlertTriangle className="h-4 w-4" />
            Approval Requirements
          </CardTitle>
          <CardDescription className="text-xs">
            Require human approval before the agent uses certain capabilities or tools.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {catalog && (
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Require approval by capability</Label>
              <div className="flex flex-wrap gap-1.5">
                {catalog.domains.flatMap((d) =>
                  d.capabilities
                    .filter((cap) => cap.risk_level !== "low")
                    .map((cap) => {
                      const isRequired = approvalCapabilities.includes(cap.slug)
                      return (
                        <Badge
                          key={cap.slug}
                          variant="outline"
                          className={`cursor-pointer text-[10px] transition-colors ${
                            isRequired
                              ? "border-yellow-500/50 text-yellow-600 dark:text-yellow-400 bg-yellow-50 dark:bg-yellow-950/20"
                              : "hover:bg-yellow-50 dark:hover:bg-yellow-950/10"
                          }`}
                          onClick={() => {
                            if (isRequired) {
                              setApprovalCapabilities(approvalCapabilities.filter((c) => c !== cap.slug))
                            } else {
                              setApprovalCapabilities([...approvalCapabilities, cap.slug])
                            }
                          }}
                        >
                          {cap.label}
                          {isRequired && <span className="ml-1">&times;</span>}
                        </Badge>
                      )
                    })
                )}
              </div>
            </div>
          )}

          <Separator />
          <Label className="text-xs text-muted-foreground">Require approval for individual tools</Label>
          <div className="flex gap-2">
            <Input
              value={approvalInput}
              onChange={(e) => setApprovalInput(e.target.value)}
              placeholder="Tool name requiring approval..."
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault()
                  const trimmed = approvalInput.trim()
                  if (!trimmed) return
                  if (!TOOL_NAME_PATTERN.test(trimmed)) {
                    toast.error("Tool name must be lowercase alphanumeric with underscores, starting with a letter (max 64 chars)")
                    return
                  }
                  if (!requireApproval.includes(trimmed)) {
                    setRequireApproval([...requireApproval, trimmed])
                  }
                  setApprovalInput("")
                }
              }}
            />
            <Button
              variant="outline"
              onClick={() => {
                const trimmed = approvalInput.trim()
                if (!trimmed) return
                if (!TOOL_NAME_PATTERN.test(trimmed)) {
                  toast.error("Tool name must be lowercase alphanumeric with underscores, starting with a letter (max 64 chars)")
                  return
                }
                if (!requireApproval.includes(trimmed)) {
                  setRequireApproval([...requireApproval, trimmed])
                }
                setApprovalInput("")
              }}
            >
              Add
            </Button>
          </div>

          {requireApproval.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {requireApproval.map((tool) => (
                <Badge
                  key={tool}
                  variant="outline"
                  className="cursor-pointer border-yellow-500/50 text-yellow-600 dark:text-yellow-400"
                  onClick={() =>
                    setRequireApproval(requireApproval.filter((t) => t !== tool))
                  }
                >
                  {tool} &times;
                </Badge>
              ))}
            </div>
          )}

          <Separator />

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="gov-timeout">Approval Timeout (seconds)</Label>
              <Input
                id="gov-timeout"
                type="number"
                min="1"
                max="86400"
                value={approvalTimeout}
                onChange={(e) => setApprovalTimeout(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="gov-default">Default on Timeout</Label>
              <Select value={approvalDefault} onValueChange={(v) => setApprovalDefault(v as "deny" | "approve")}>
                <SelectTrigger id="gov-default">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="deny">Deny (safer)</SelectItem>
                  <SelectItem value="approve">Auto-approve</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
