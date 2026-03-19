import * as React from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useCreateAgent } from "@/hooks/use-agents"
import { Bot, Sparkles, Code, FileSearch, PenTool, Brain } from "lucide-react"
import { cn } from "@/lib/utils"

interface CreateAgentDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated?: (agentId: string) => void
}

interface AgentTemplate {
  id: string
  name: string
  description: string
  icon: React.ElementType
  color: string
  defaults: {
    system_prompt: string
    model: string
    temperature?: number
    allowed_tools?: string[]
  }
}

const TEMPLATES: AgentTemplate[] = [
  {
    id: "blank",
    name: "Blank Agent",
    description: "Start from scratch with a custom configuration",
    icon: Bot,
    color: "text-muted-foreground bg-muted",
    defaults: {
      system_prompt: "",
      model: "gpt-4o",
    },
  },
  {
    id: "assistant",
    name: "General Assistant",
    description: "Helpful AI assistant for general tasks",
    icon: Sparkles,
    color: "text-purple-600 bg-purple-100 dark:bg-purple-900/30",
    defaults: {
      system_prompt:
        "You are a helpful, accurate, and concise assistant. Answer questions thoroughly but efficiently. When you're unsure, say so.",
      model: "gpt-4o",
      temperature: 0.7,
    },
  },
  {
    id: "coder",
    name: "Code Expert",
    description: "Software engineering specialist for code review and generation",
    icon: Code,
    color: "text-blue-600 bg-blue-100 dark:bg-blue-900/30",
    defaults: {
      system_prompt:
        "You are an expert software engineer. Write clean, well-documented, and efficient code. Explain your reasoning, suggest best practices, and identify bugs and security issues.",
      model: "gpt-4o",
      temperature: 0.3,
      allowed_tools: ["code_execute"],
    },
  },
  {
    id: "researcher",
    name: "Research Analyst",
    description: "Thorough research and analysis with cited sources",
    icon: FileSearch,
    color: "text-emerald-600 bg-emerald-100 dark:bg-emerald-900/30",
    defaults: {
      system_prompt:
        "You are a meticulous research analyst. Investigate topics thoroughly, cite sources, present findings clearly, and highlight key insights. Always distinguish facts from analysis.",
      model: "gpt-4o",
      temperature: 0.4,
    },
  },
  {
    id: "writer",
    name: "Content Writer",
    description: "Creative content generation and editing",
    icon: PenTool,
    color: "text-orange-600 bg-orange-100 dark:bg-orange-900/30",
    defaults: {
      system_prompt:
        "You are a skilled content writer. Create engaging, well-structured content tailored to the audience and medium. Adapt tone and style as needed.",
      model: "gpt-4o",
      temperature: 0.8,
    },
  },
  {
    id: "reasoning",
    name: "Deep Thinker",
    description: "Complex reasoning and problem-solving",
    icon: Brain,
    color: "text-rose-600 bg-rose-100 dark:bg-rose-900/30",
    defaults: {
      system_prompt:
        "You are an analytical thinker specializing in complex problem-solving. Break problems into components, consider multiple perspectives, evaluate tradeoffs, and present clear conclusions.",
      model: "gpt-4o",
      temperature: 0.2,
    },
  },
]

function slugify(str: string): string {
  return str
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 60)
}

export function CreateAgentDialog({
  open,
  onOpenChange,
  onCreated,
}: CreateAgentDialogProps) {
  const [step, setStep] = React.useState<"template" | "details">("template")
  const [selectedTemplate, setSelectedTemplate] = React.useState<string>("blank")
  const [name, setName] = React.useState("")
  const [slug, setSlug] = React.useState("")
  const [slugEdited, setSlugEdited] = React.useState(false)
  const [description, setDescription] = React.useState("")
  const [model, setModel] = React.useState("gpt-4o")
  const createAgent = useCreateAgent()

  React.useEffect(() => {
    if (open) {
      setStep("template")
      setSelectedTemplate("blank")
      setName("")
      setSlug("")
      setSlugEdited(false)
      setDescription("")
      setModel("gpt-4o")
    }
  }, [open])

  const handleNameChange = (value: string) => {
    setName(value)
    if (!slugEdited) {
      setSlug(slugify(value))
    }
  }

  const handleTemplateSelect = (templateId: string) => {
    setSelectedTemplate(templateId)
    const tpl = TEMPLATES.find((t) => t.id === templateId)
    if (tpl) {
      setModel(tpl.defaults.model)
    }
  }

  const handleCreate = async () => {
    const tpl = TEMPLATES.find((t) => t.id === selectedTemplate)
    if (!tpl || !name.trim() || !slug.trim()) return

    const result = await createAgent.mutateAsync({
      name: name.trim(),
      slug: slug.trim(),
      description: description.trim(),
      system_prompt: tpl.defaults.system_prompt,
      model,
      temperature: tpl.defaults.temperature,
      allowed_tools: tpl.defaults.allowed_tools ?? [],
    })

    onOpenChange(false)
    onCreated?.(result.id)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[600px]">
        <DialogHeader>
          <DialogTitle>
            {step === "template" ? "Create Agent" : "Agent Details"}
          </DialogTitle>
          <DialogDescription>
            {step === "template"
              ? "Choose a template to get started quickly, or create from scratch."
              : "Give your agent a name and configure its basics."}
          </DialogDescription>
        </DialogHeader>

        {step === "template" ? (
          <div className="grid grid-cols-2 gap-3 py-4">
            {TEMPLATES.map((tpl) => {
              const Icon = tpl.icon
              const isSelected = selectedTemplate === tpl.id
              return (
                <button
                  key={tpl.id}
                  onClick={() => handleTemplateSelect(tpl.id)}
                  className={cn(
                    "flex items-start gap-3 rounded-lg border p-3 text-left transition-all",
                    "hover:bg-accent/50",
                    isSelected && "border-primary ring-2 ring-primary/20 bg-accent/30",
                  )}
                >
                  <div
                    className={cn(
                      "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
                      tpl.color,
                    )}
                  >
                    <Icon className="h-4.5 w-4.5" />
                  </div>
                  <div className="min-w-0">
                    <div className="font-medium text-sm">{tpl.name}</div>
                    <div className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
                      {tpl.description}
                    </div>
                  </div>
                </button>
              )
            })}
          </div>
        ) : (
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="agent-name">Name</Label>
              <Input
                id="agent-name"
                value={name}
                onChange={(e) => handleNameChange(e.target.value)}
                placeholder="My Agent"
                autoFocus
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="agent-slug">
                Slug
                <span className="text-muted-foreground text-xs ml-2">
                  (URL-friendly identifier)
                </span>
              </Label>
              <Input
                id="agent-slug"
                value={slug}
                onChange={(e) => {
                  setSlug(e.target.value)
                  setSlugEdited(true)
                }}
                placeholder="my-agent"
                pattern="^[a-z0-9][a-z0-9\-]*$"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="agent-desc">Description</Label>
              <Textarea
                id="agent-desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What does this agent do?"
                rows={2}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="agent-model">Model</Label>
              <Select value={model} onValueChange={setModel}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="gpt-4o">GPT-4o</SelectItem>
                  <SelectItem value="gpt-4o-mini">GPT-4o Mini</SelectItem>
                  <SelectItem value="claude-sonnet-4-6">Claude Sonnet 4.6</SelectItem>
                  <SelectItem value="claude-opus-4-6">Claude Opus 4.6</SelectItem>
                  <SelectItem value="claude-haiku-4-5">Claude Haiku 4.5</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        )}

        <DialogFooter>
          {step === "template" ? (
            <Button onClick={() => setStep("details")}>
              Continue
            </Button>
          ) : (
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setStep("template")}>
                Back
              </Button>
              <Button
                onClick={handleCreate}
                disabled={!name.trim() || !slug.trim() || createAgent.isPending}
              >
                {createAgent.isPending ? "Creating..." : "Create Agent"}
              </Button>
            </div>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
