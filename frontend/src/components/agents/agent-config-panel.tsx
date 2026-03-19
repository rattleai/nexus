import * as React from "react"
import { Save, RotateCcw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Switch } from "@/components/ui/switch"
import { Slider } from "@/components/ui/slider"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useUpdateAgent } from "@/hooks/use-agents"
import { useModels } from "@/hooks/use-models"
import type { AgentDefinition, AgentStatus } from "@/types/agents"
import { toast } from "sonner"

interface AgentConfigPanelProps {
  agent: AgentDefinition
}

export function AgentConfigPanel({ agent }: AgentConfigPanelProps) {
  const updateAgent = useUpdateAgent()
  const { data: models = [] } = useModels()

  const modelsByProvider = React.useMemo(() => {
    const grouped = new Map<string, typeof models>()
    for (const m of models) {
      const list = grouped.get(m.provider) ?? []
      list.push(m)
      grouped.set(m.provider, list)
    }
    return grouped
  }, [models])

  const [name, setName] = React.useState(agent.name)
  const [description, setDescription] = React.useState(agent.description)
  const [systemPrompt, setSystemPrompt] = React.useState(agent.system_prompt)
  const [model, setModel] = React.useState(agent.model)
  const [temperature, setTemperature] = React.useState(agent.temperature ?? 0.7)
  const [maxTokens, setMaxTokens] = React.useState(agent.max_tokens ?? 4096)
  const [maxSteps, setMaxSteps] = React.useState(agent.max_steps_per_run)
  const [maxDuration, setMaxDuration] = React.useState(agent.max_duration_seconds)
  const [maxTokensPerRun, setMaxTokensPerRun] = React.useState(agent.max_tokens_per_run)
  const [parallelTools, setParallelTools] = React.useState(agent.parallel_tool_execution)
  const [sandboxEnabled, setSandboxEnabled] = React.useState(agent.sandbox_enabled)
  const [status, setStatus] = React.useState<AgentStatus>(agent.status)
  const [toolInput, setToolInput] = React.useState("")
  const [allowedTools, setAllowedTools] = React.useState<string[]>(agent.allowed_tools)

  // Reset when agent changes
  React.useEffect(() => {
    setName(agent.name)
    setDescription(agent.description)
    setSystemPrompt(agent.system_prompt)
    setModel(agent.model)
    setTemperature(agent.temperature ?? 0.7)
    setMaxTokens(agent.max_tokens ?? 4096)
    setMaxSteps(agent.max_steps_per_run)
    setMaxDuration(agent.max_duration_seconds)
    setMaxTokensPerRun(agent.max_tokens_per_run)
    setParallelTools(agent.parallel_tool_execution)
    setSandboxEnabled(agent.sandbox_enabled)
    setStatus(agent.status)
    setAllowedTools(agent.allowed_tools)
  }, [agent])

  const isDirty =
    name !== agent.name ||
    description !== agent.description ||
    systemPrompt !== agent.system_prompt ||
    model !== agent.model ||
    temperature !== (agent.temperature ?? 0.7) ||
    maxTokens !== (agent.max_tokens ?? 4096) ||
    maxSteps !== agent.max_steps_per_run ||
    maxDuration !== agent.max_duration_seconds ||
    maxTokensPerRun !== agent.max_tokens_per_run ||
    parallelTools !== agent.parallel_tool_execution ||
    sandboxEnabled !== agent.sandbox_enabled ||
    status !== agent.status ||
    JSON.stringify([...allowedTools].sort()) !== JSON.stringify([...agent.allowed_tools].sort())

  const handleSave = async () => {
    await updateAgent.mutateAsync({
      id: agent.id,
      data: {
        name,
        description,
        system_prompt: systemPrompt,
        model,
        temperature,
        max_tokens: maxTokens,
        max_steps_per_run: maxSteps,
        max_duration_seconds: maxDuration,
        max_tokens_per_run: maxTokensPerRun,
        parallel_tool_execution: parallelTools,
        sandbox_enabled: sandboxEnabled,
        status,
        allowed_tools: allowedTools,
        expected_version: agent.version,
      },
    })
  }

  const handleReset = () => {
    setName(agent.name)
    setDescription(agent.description)
    setSystemPrompt(agent.system_prompt)
    setModel(agent.model)
    setTemperature(agent.temperature ?? 0.7)
    setMaxTokens(agent.max_tokens ?? 4096)
    setMaxSteps(agent.max_steps_per_run)
    setMaxDuration(agent.max_duration_seconds)
    setMaxTokensPerRun(agent.max_tokens_per_run)
    setParallelTools(agent.parallel_tool_execution)
    setSandboxEnabled(agent.sandbox_enabled)
    setStatus(agent.status)
    setAllowedTools(agent.allowed_tools)
  }

  const TOOL_NAME_PATTERN = /^[a-z][a-z0-9_]{0,63}$/
  const addTool = () => {
    const trimmed = toolInput.trim()
    if (!trimmed) return
    if (!TOOL_NAME_PATTERN.test(trimmed)) {
      toast.error("Tool name must be lowercase alphanumeric with underscores, starting with a letter (max 64 chars)")
      return
    }
    if (!allowedTools.includes(trimmed)) {
      setAllowedTools([...allowedTools, trimmed])
      setToolInput("")
    }
  }

  const removeTool = (tool: string) => {
    setAllowedTools(allowedTools.filter((t) => t !== tool))
  }

  return (
    <div className="space-y-6">
      {/* Sticky save bar */}
      {isDirty && (
        <div className="sticky top-0 z-10 flex items-center justify-between rounded-lg border bg-background/95 backdrop-blur p-3 shadow-sm">
          <span className="text-sm text-muted-foreground">
            You have unsaved changes
          </span>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={handleReset}>
              <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
              Reset
            </Button>
            <Button
              size="sm"
              onClick={handleSave}
              disabled={updateAgent.isPending}
              variant={updateAgent.isError ? "destructive" : "default"}
            >
              <Save className="mr-1.5 h-3.5 w-3.5" />
              {updateAgent.isPending ? "Saving..." : updateAgent.isError ? "Retry Save" : "Save Changes"}
            </Button>
          </div>
        </div>
      )}

      {/* Basic Info */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Basic Information</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="cfg-name">Name</Label>
              <Input
                id="cfg-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="cfg-status">Status</Label>
              <Select value={status} onValueChange={(v) => setStatus(v as AgentStatus)}>
                <SelectTrigger id="cfg-status">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="draft">Draft</SelectItem>
                  <SelectItem value="active">Active</SelectItem>
                  <SelectItem value="disabled">Disabled</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="cfg-desc">Description</Label>
            <Textarea
              id="cfg-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
            />
          </div>
        </CardContent>
      </Card>

      {/* System Prompt */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">System Prompt</CardTitle>
        </CardHeader>
        <CardContent>
          <Textarea
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            placeholder="Define the agent's behavior, personality, and capabilities..."
            rows={8}
            className="font-mono text-xs"
          />
          <div className="flex justify-end mt-1.5">
            <span className="text-[11px] text-muted-foreground">
              {systemPrompt.length.toLocaleString()} / 100,000 characters
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Model Settings */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Model Configuration</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="cfg-model">Model</Label>
              <Select value={model} onValueChange={setModel}>
                <SelectTrigger id="cfg-model">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {[...modelsByProvider.entries()].map(([provider, providerModels]) => (
                    <SelectGroup key={provider}>
                      <SelectLabel className="capitalize">{provider}</SelectLabel>
                      {providerModels.map((m) => (
                        <SelectItem key={m.model_id} value={m.model_id}>
                          {m.display_name}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="cfg-max-tokens">Max Output Tokens</Label>
              <Input
                id="cfg-max-tokens"
                type="number"
                value={maxTokens}
                onChange={(e) => setMaxTokens(Number(e.target.value))}
                min={1}
                max={1000000}
              />
            </div>
          </div>

          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Label>Temperature</Label>
              <span className="text-sm font-mono text-muted-foreground">
                {temperature.toFixed(2)}
              </span>
            </div>
            <Slider
              value={[temperature]}
              onValueChange={([v]) => setTemperature(v)}
              min={0}
              max={2}
              step={0.05}
            />
            <div className="flex justify-between text-[10px] text-muted-foreground">
              <span>Precise</span>
              <span>Balanced</span>
              <span>Creative</span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Execution Limits */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Execution Limits</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label htmlFor="cfg-max-steps">Max Steps</Label>
              <Input
                id="cfg-max-steps"
                type="number"
                value={maxSteps}
                onChange={(e) => setMaxSteps(Number(e.target.value))}
                min={1}
                max={1000}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="cfg-max-duration">Max Duration (s)</Label>
              <Input
                id="cfg-max-duration"
                type="number"
                value={maxDuration}
                onChange={(e) => setMaxDuration(Number(e.target.value))}
                min={10}
                max={3600}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="cfg-max-tokens-run">Max Tokens/Run</Label>
              <Input
                id="cfg-max-tokens-run"
                type="number"
                value={maxTokensPerRun}
                onChange={(e) => setMaxTokensPerRun(Number(e.target.value))}
                min={100}
                max={10000000}
              />
            </div>
          </div>

          <Separator />

          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <Label>Parallel Tool Execution</Label>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Run multiple tool calls concurrently
                </p>
              </div>
              <Switch
                checked={parallelTools}
                onCheckedChange={setParallelTools}
              />
            </div>
            <div className="flex items-center justify-between">
              <div>
                <Label>Sandbox Mode</Label>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Execute code in an isolated sandbox
                </p>
              </div>
              <Switch
                checked={sandboxEnabled}
                onCheckedChange={setSandboxEnabled}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Tools */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Allowed Tools</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2">
            <Input
              value={toolInput}
              onChange={(e) => setToolInput(e.target.value)}
              placeholder="Tool name (e.g., code_execute)"
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault()
                  addTool()
                }
              }}
            />
            <Button variant="outline" onClick={addTool}>
              Add
            </Button>
          </div>
          {allowedTools.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {allowedTools.map((tool) => (
                <Badge
                  key={tool}
                  variant="secondary"
                  className="cursor-pointer hover:bg-destructive/20 transition-colors"
                  onClick={() => removeTool(tool)}
                >
                  {tool}
                  <span className="ml-1 text-muted-foreground">&times;</span>
                </Badge>
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              No tools configured. The agent will only generate text responses.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
