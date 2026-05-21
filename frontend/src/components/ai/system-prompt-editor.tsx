import * as React from "react"
import { X } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

export interface SystemPromptPreset {
  id: string
  name: string
  prompt: string
  description?: string
}

export interface SystemPromptEditorProps {
  value: string
  onChange: (value: string) => void
  presets?: SystemPromptPreset[]
  className?: string
}

const DEFAULT_PRESETS: SystemPromptPreset[] = [
  {
    id: "helpful-assistant",
    name: "Helpful Assistant",
    prompt:
      "You are a helpful, harmless, and honest assistant. You answer questions accurately and concisely. If you are unsure about something, you say so.",
    description: "General-purpose helpful assistant",
  },
  {
    id: "code-expert",
    name: "Code Expert",
    prompt:
      "You are an expert software engineer. You write clean, well-documented, and efficient code. You explain your reasoning and suggest best practices. When reviewing code, you identify bugs, security issues, and performance improvements.",
    description: "Software engineering specialist",
  },
  {
    id: "creative-writer",
    name: "Creative Writer",
    prompt:
      "You are a creative writing assistant. You help craft engaging narratives, develop compelling characters, and refine prose. You adapt your style to match the desired tone and genre.",
    description: "Creative writing and storytelling",
  },
]

export function SystemPromptEditor({
  value,
  onChange,
  presets = DEFAULT_PRESETS,
  className,
}: SystemPromptEditorProps) {
  const textareaRef = React.useRef<HTMLTextAreaElement>(null)

  const adjustHeight = React.useCallback(() => {
    const textarea = textareaRef.current
    if (textarea) {
      textarea.style.height = "auto"
      textarea.style.height = `${Math.max(80, textarea.scrollHeight)}px`
    }
  }, [])

  React.useEffect(() => {
    adjustHeight()
  }, [value, adjustHeight])

  function handlePresetSelect(presetId: string) {
    const preset = presets.find((p) => p.id === presetId)
    if (preset) {
      onChange(preset.prompt)
    }
  }

  return (
    <div className={cn("space-y-3", className)}>
      <div className="flex items-center justify-between">
        <Label htmlFor="system-prompt">System Prompt</Label>
        <div className="flex items-center gap-2">
          {presets.length > 0 && (
            <Select onValueChange={handlePresetSelect}>
              <SelectTrigger className="h-8 w-[160px] text-xs">
                <SelectValue placeholder="Load preset..." />
              </SelectTrigger>
              <SelectContent>
                {presets.map((preset) => (
                  <SelectItem key={preset.id} value={preset.id}>
                    <div className="flex flex-col">
                      <span>{preset.name}</span>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          {value.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              className="h-8 px-2 text-xs text-muted-foreground"
              onClick={() => onChange("")}
              aria-label="Clear system prompt"
            >
              <X className="mr-1 h-3 w-3" />
              Clear
            </Button>
          )}
        </div>
      </div>

      <textarea
        ref={textareaRef}
        id="system-prompt"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onInput={adjustHeight}
        placeholder="Enter a system prompt to set the AI's behavior and personality..."
        className="flex min-h-[80px] w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        aria-label="System prompt"
      />

      <div className="flex justify-end">
        <span className="text-xs text-muted-foreground">
          {value.length.toLocaleString()} characters
        </span>
      </div>
    </div>
  )
}
