// ── Agent workspace types (mirrors backend Pydantic schemas) ──────

export type AgentStatus = "draft" | "active" | "disabled"
export type InstanceStatus = "pending" | "running" | "paused" | "completed" | "failed" | "cancelled"

// ── Agent Definition ──────────────────────────────────────────────

export interface AgentDefinition {
  id: string
  tenant_id: string
  name: string
  slug: string
  description: string
  status: AgentStatus
  version: number
  system_prompt: string
  model: string
  temperature: number | null
  max_tokens: number | null
  allowed_tools: string[]
  max_steps_per_run: number
  max_duration_seconds: number
  max_tokens_per_run: number
  sandbox_enabled: boolean
  parallel_tool_execution: boolean
  memory_config: Record<string, unknown>
  governance_policy: GovernancePolicy
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface AgentDefinitionCreate {
  name: string
  slug: string
  description?: string
  system_prompt?: string
  model?: string
  temperature?: number | null
  max_tokens?: number | null
  allowed_tools?: string[]
  max_steps_per_run?: number
  max_duration_seconds?: number
  max_tokens_per_run?: number
  sandbox_enabled?: boolean
  parallel_tool_execution?: boolean
  memory_config?: Record<string, unknown>
  governance_policy?: Record<string, unknown>
  metadata?: Record<string, unknown>
}

export interface AgentDefinitionUpdate {
  name?: string
  description?: string
  system_prompt?: string
  model?: string
  temperature?: number | null
  max_tokens?: number | null
  allowed_tools?: string[]
  max_steps_per_run?: number
  max_duration_seconds?: number
  max_tokens_per_run?: number
  sandbox_enabled?: boolean
  parallel_tool_execution?: boolean
  memory_config?: Record<string, unknown>
  governance_policy?: Record<string, unknown>
  metadata?: Record<string, unknown>
  status?: AgentStatus
  expected_version?: number
}

// ── Agent Instance ────────────────────────────────────────────────

export interface AgentInstance {
  id: string
  tenant_id: string
  definition_id: string
  status: InstanceStatus
  steps_executed: number
  tokens_used: number
  cost_usd: number
  input_data: Record<string, unknown>
  output_data: Record<string, unknown>
  error: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
}

// ── Governance Policy ─────────────────────────────────────────────

export interface GovernancePolicy {
  max_spend_per_run_usd?: number | null
  max_spend_per_day_usd?: number | null
  max_spend_per_month_usd?: number | null
  allowed_tools?: string[]
  denied_tools?: string[]
  require_approval_for?: string[]
  approval_timeout_seconds?: number
  approval_default_action?: "deny" | "approve"
  max_requests_per_minute?: number | null
  [key: string]: unknown
}

export interface AgentPolicy {
  id: string
  tenant_id: string
  name: string
  description: string
  version: number
  max_spend_per_run_usd: number | null
  max_spend_per_day_usd: number | null
  max_spend_per_month_usd: number | null
  allowed_tools: string[]
  denied_tools: string[]
  require_approval_for: string[]
  approval_timeout_seconds: number
  approval_default_action: string
  max_requests_per_minute: number | null
  max_steps_per_run: number | null
  rules: Record<string, unknown>
  created_at: string
  updated_at: string
}

// ── Tenant Tool ───────────────────────────────────────────────────

export interface TenantTool {
  id: string
  tenant_id: string
  tool_name: string
  description: string
  source: string
  input_schema: Record<string, unknown>
  output_schema: Record<string, unknown>
  endpoint_url: string | null
  auth_config: Record<string, unknown>
  is_active: boolean
  health_check_url: string | null
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

// ── Workflow ──────────────────────────────────────────────────────

export interface WorkflowDefinition {
  id: string
  tenant_id: string
  name: string
  slug: string
  description: string
  status: string
  version: number
  definition: {
    steps: WorkflowStep[]
    transitions: WorkflowTransition[]
    entry_step: string
  }
  governance: Record<string, unknown>
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface WorkflowStep {
  name: string
  agent_id: string
  pattern?: "single" | "parallel" | "supervisor"
  agent_ids?: string[]
  worker_agent_ids?: string[]
}

export interface WorkflowTransition {
  from: string
  to: string
  condition?: string
}

// ── Analytics ─────────────────────────────────────────────────────

export interface AgentAnalytics {
  period_days: number
  total_runs: number
  total_tokens: number
  total_cost_usd: number
  avg_cost_per_run: number
  avg_steps_per_run: number
  status_breakdown: Record<string, number>
  top_agents: Array<{
    agent_id: string
    name: string
    runs: number
    total_cost_usd: number
    total_tokens: number
  }>
}

// ── Approval ──────────────────────────────────────────────────────

export interface PendingApproval {
  approval_id: string
  tenant_id: string
  instance_id: string
  tool_name: string
  arguments: Record<string, unknown>
  created_at: string
  timeout_seconds: number
}

// ── SSE Stream Events ─────────────────────────────────────────────

export interface AgentStreamEvent {
  event: string
  data: {
    content?: string
    tool_name?: string
    tool_args?: Record<string, unknown>
    tool_result?: unknown
    step?: number
    tokens?: number
    cost?: number
    status?: string
    error?: string
    message?: string
    [key: string]: unknown
  }
}

// ── Paginated response ────────────────────────────────────────────

export interface PaginatedAgentResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
}
