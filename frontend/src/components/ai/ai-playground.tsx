import { useState } from "react"
import { Play, RotateCcw, Split, Columns2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { cn } from "@/lib/utils"
import { ModelSelector, type AIModel } from "./model-selector"
import { ModelParameterControls, type ModelParameters } from "./model-parameter-controls"
import { TokenUsageDisplay } from "./token-usage-display"

interface PlaygroundResponse {
  content: string
  model: string
  duration?: number
  usage?: { inputTokens: number; outputTokens: number; totalTokens: number }
}

interface PlaygroundPanel {
  modelId: string
  response: PlaygroundResponse | null
  isLoading: boolean
}

interface PlaygroundProps {
  models: AIModel[]
  onSubmit?: (prompt: string, modelId: string, params: ModelParameters) => Promise<PlaygroundResponse>
  className?: string
}

const defaultParams: ModelParameters = {
  temperature: 1,
  topP: 1,
  maxTokens: 4096,
  frequencyPenalty: 0,
  presencePenalty: 0,
}

export function AIPlayground({
  models,
  onSubmit,
  className,
}: PlaygroundProps) {
  const [prompt, setPrompt] = useState("")
  const [comparisonMode, setComparisonMode] = useState(false)
  const [params, setParams] = useState(defaultParams)
  const [panels, setPanels] = useState<[PlaygroundPanel, PlaygroundPanel]>([
    { modelId: models[0]?.id ?? "", response: null, isLoading: false },
    { modelId: models[1]?.id ?? models[0]?.id ?? "", response: null, isLoading: false },
  ])

  const updatePanel = (index: 0 | 1, updates: Partial<PlaygroundPanel>) => {
    setPanels((prev) => {
      const next = [...prev] as [PlaygroundPanel, PlaygroundPanel]
      next[index] = { ...next[index], ...updates }
      return next
    })
  }

  const handleSubmit = async () => {
    if (!prompt.trim() || !onSubmit) return

    const panelsToRun = comparisonMode ? [0, 1] as const : [0] as const

    for (const i of panelsToRun) {
      updatePanel(i, { isLoading: true, response: null })
    }

    await Promise.allSettled(
      panelsToRun.map(async (i) => {
        try {
          const response = await onSubmit(prompt, panels[i].modelId, params)
          updatePanel(i, { response, isLoading: false })
        } catch {
          updatePanel(i, {
            response: { content: "Error generating response", model: panels[i].modelId },
            isLoading: false,
          })
        }
      }),
    )
  }

  const handleReset = () => {
    setPrompt("")
    setPanels([
      { ...panels[0], response: null, isLoading: false },
      { ...panels[1], response: null, isLoading: false },
    ])
    setParams(defaultParams)
  }

  const renderPanel = (index: 0 | 1) => {
    const panel = panels[index]
    return (
      <div className="flex flex-1 flex-col gap-3">
        <ModelSelector
          models={models}
          value={panel.modelId}
          onChange={(id) => updatePanel(index, { modelId: id })}
        />
        <div className="flex-1 rounded-lg border bg-muted/30 p-3">
          {panel.isLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              Generating...
            </div>
          ) : panel.response ? (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="text-xs">
                  {panel.response.model}
                </Badge>
                {panel.response.duration && (
                  <span className="text-xs text-muted-foreground">
                    {(panel.response.duration / 1000).toFixed(1)}s
                  </span>
                )}
              </div>
              <p className="whitespace-pre-wrap text-sm">{panel.response.content}</p>
              {panel.response.usage && (
                <TokenUsageDisplay usage={panel.response.usage} variant="inline" />
              )}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Response will appear here</p>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className={cn("flex flex-col gap-4", className)}>
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">AI Playground</h2>
        <div className="flex items-center gap-2">
          <Button
            variant={comparisonMode ? "default" : "outline"}
            size="sm"
            onClick={() => setComparisonMode(!comparisonMode)}
          >
            {comparisonMode ? <Columns2 className="mr-1 h-4 w-4" /> : <Split className="mr-1 h-4 w-4" />}
            {comparisonMode ? "Comparing" : "Compare"}
          </Button>
          <Button variant="outline" size="sm" onClick={handleReset}>
            <RotateCcw className="mr-1 h-4 w-4" />
            Reset
          </Button>
        </div>
      </div>

      <ModelParameterControls params={params} onChange={setParams} />

      <div>
        <Textarea
          placeholder="Enter your prompt..."
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={4}
          className="resize-none"
        />
        <Button
          className="mt-2 w-full"
          onClick={handleSubmit}
          disabled={!prompt.trim() || panels.some((p) => p.isLoading)}
        >
          <Play className="mr-1 h-4 w-4" />
          Run
        </Button>
      </div>

      <Separator />

      <div className={cn("flex gap-4", comparisonMode ? "flex-row" : "flex-col")}>
        {renderPanel(0)}
        {comparisonMode && (
          <>
            <Separator orientation="vertical" className="h-auto" />
            {renderPanel(1)}
          </>
        )}
      </div>
    </div>
  )
}
