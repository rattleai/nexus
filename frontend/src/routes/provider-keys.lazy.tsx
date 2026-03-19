import { useState } from "react"
import { createLazyFileRoute } from "@tanstack/react-router"
import { toast } from "sonner"
import {
  Plus,
  Trash2,
  KeyRound,
  ShieldCheck,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Loader2,
  Eye,
  EyeOff,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { StatusDot } from "@/components/status-dot"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { AuthGuard } from "@/components/auth/auth-guard"
import { PageHeader } from "@/components/page-header"
import { FormDialog } from "@/components/form-dialog"
import { ConfirmDialog } from "@/components/confirm-dialog"
import {
  useProviderKeys,
  useCreateProviderKey,
  useDeleteProviderKey,
} from "@/hooks/use-provider-keys"
import { parseApiError } from "@/lib/api-client"
import { formatDate } from "@/lib/format"
import type { ProviderKey } from "@/types/api"

export const Route = createLazyFileRoute("/provider-keys")({
  component: ProviderKeysPage,
})

const PROVIDERS = [
  { value: "openai", label: "OpenAI", placeholder: "sk-..." },
  { value: "anthropic", label: "Anthropic", placeholder: "sk-ant-..." },
  { value: "google", label: "Google (Gemini)", placeholder: "AIza..." },
  { value: "mistral", label: "Mistral", placeholder: "..." },
  { value: "deepseek", label: "DeepSeek", placeholder: "sk-..." },
  { value: "qwen", label: "Qwen", placeholder: "sk-..." },
  { value: "aleph_alpha", label: "Aleph Alpha", placeholder: "..." },
] as const

function getProviderLabel(value: string) {
  return PROVIDERS.find((p) => p.value === value)?.label ?? value
}

function ProviderKeysPage() {
  const { data: keys = [], isLoading } = useProviderKeys()
  const [createOpen, setCreateOpen] = useState(false)

  const activeKeys = keys.filter((k) => k.is_active)
  const connectedProviders = new Set(activeKeys.map((k) => k.provider))

  return (
    <AuthGuard>
      <div className="space-y-8">
        <PageHeader
          title="Provider Keys"
          description="Bring your own API keys to use models from OpenAI, Anthropic, Google, and more. Your keys are encrypted at rest and never shared."
        />

        {/* Status banner */}
        <div className="flex items-center gap-3 rounded-lg border bg-muted/50 px-4 py-3">
          <ShieldCheck className="h-5 w-5 text-primary shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium">
              {connectedProviders.size === 0
                ? "No provider keys configured"
                : `${connectedProviders.size} provider${connectedProviders.size > 1 ? "s" : ""} connected`}
            </p>
            <p className="text-xs text-muted-foreground">
              {connectedProviders.size === 0
                ? "Add a key to start using your own API access. Platform keys are used as fallback."
                : "Your keys take priority over platform keys. Requests are billed directly to your provider account."}
            </p>
          </div>
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            Add Key
          </Button>
        </div>

        {/* Provider grid */}
        {isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : keys.length === 0 ? (
          <EmptyState onAdd={() => setCreateOpen(true)} />
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {keys.map((key) => (
              <ProviderKeyCard key={key.id} providerKey={key} />
            ))}

            {/* Add more card */}
            <button
              onClick={() => setCreateOpen(true)}
              className="flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-muted-foreground/25 p-8 text-muted-foreground transition-colors hover:border-primary/50 hover:text-primary"
            >
              <Plus className="h-8 w-8" />
              <span className="text-sm font-medium">Add Provider Key</span>
            </button>
          </div>
        )}

      </div>

      <AddKeyDialog open={createOpen} onOpenChange={setCreateOpen} />
    </AuthGuard>
  )
}

function ProviderKeyCard({ providerKey }: { providerKey: ProviderKey }) {
  const deleteKey = useDeleteProviderKey()

  const handleDelete = async () => {
    try {
      await deleteKey.mutateAsync(providerKey.id)
      toast.success(`${getProviderLabel(providerKey.provider)} key removed`)
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    }
  }

  return (
    <Card className="relative overflow-hidden">
      {providerKey.last_error && (
        <div className="absolute top-0 left-0 right-0 h-0.5 bg-destructive" />
      )}
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <KeyRound className="h-5 w-5" />
            </div>
            <div>
              <CardTitle className="text-base">
                {getProviderLabel(providerKey.provider)}
              </CardTitle>
              <CardDescription className="text-xs">
                {providerKey.display_name}
              </CardDescription>
            </div>
          </div>
          <StatusDot variant={providerKey.is_active ? "active" : "inactive"} />
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Status info */}
        <div className="space-y-1.5 text-xs">
          <div className="flex items-center gap-2 text-muted-foreground">
            <Clock className="h-3 w-3 shrink-0" />
            <span>Added {formatDate(providerKey.created_at)}</span>
          </div>
          {providerKey.last_used_at && (
            <div className="flex items-center gap-2 text-muted-foreground">
              <CheckCircle2 className="h-3 w-3 shrink-0 text-green-500" />
              <span>Last used {formatDate(providerKey.last_used_at)}</span>
            </div>
          )}
          {providerKey.last_error && (
            <div className="flex items-center gap-2 text-destructive">
              <AlertTriangle className="h-3 w-3 shrink-0" />
              <span className="truncate">{providerKey.last_error}</span>
            </div>
          )}
        </div>

        <Separator />

        <div className="flex justify-end">
          <ConfirmDialog
            title="Remove Provider Key"
            description={`This will permanently delete your ${getProviderLabel(providerKey.provider)} API key. Requests will fall back to platform keys.`}
            variant="destructive"
            confirmLabel="Remove Key"
            onConfirm={handleDelete}
          >
            <Button variant="ghost" size="sm" className="h-7 text-xs text-muted-foreground hover:text-destructive">
              <Trash2 className="mr-1.5 h-3 w-3" />
              Remove
            </Button>
          </ConfirmDialog>
        </div>
      </CardContent>
    </Card>
  )
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed py-16 px-8 text-center">
      <div className="relative mb-6">
        <div className="flex h-20 w-20 items-center justify-center rounded-2xl bg-gradient-to-br from-primary/20 to-primary/5 shadow-inner">
          <KeyRound className="h-10 w-10 text-primary" />
        </div>
        <div className="absolute -top-1 -right-1 flex h-6 w-6 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-md">
          <ShieldCheck className="h-3.5 w-3.5" />
        </div>
      </div>
      <h3 className="text-xl font-semibold mb-2">Bring Your Own Keys</h3>
      <p className="text-sm text-muted-foreground max-w-md mb-6">
        Connect your own API keys from providers like OpenAI, Anthropic, or Google.
        Your keys are encrypted with AES-256 and used with priority over platform keys.
      </p>
      <Button onClick={onAdd}>
        <Plus className="mr-1.5 h-4 w-4" />
        Add Your First Key
      </Button>
    </div>
  )
}

function AddKeyDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [provider, setProvider] = useState("")
  const [apiKey, setApiKey] = useState("")
  const [displayName, setDisplayName] = useState("")
  const [showKey, setShowKey] = useState(false)
  const createKey = useCreateProviderKey()

  const selectedProvider = PROVIDERS.find((p) => p.value === provider)

  const handleCreate = async () => {
    try {
      await createKey.mutateAsync({
        provider,
        api_key: apiKey,
        display_name: displayName || "default",
      })
      toast.success(`${selectedProvider?.label ?? provider} key added`)
      handleClose()
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    }
  }

  const handleClose = () => {
    onOpenChange(false)
    setProvider("")
    setApiKey("")
    setDisplayName("")
    setShowKey(false)
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={handleClose}
      title="Add Provider Key"
      description="Your API key is encrypted at rest and never exposed in API responses."
      isPending={createKey.isPending}
      onSubmit={handleCreate}
      submitLabel="Add Key"
    >
      <div className="space-y-4">
        <div className="space-y-2">
          <Label>Provider</Label>
          <Select value={provider} onValueChange={setProvider}>
            <SelectTrigger>
              <SelectValue placeholder="Select a provider..." />
            </SelectTrigger>
            <SelectContent>
              {PROVIDERS.map((p) => (
                <SelectItem key={p.value} value={p.value}>
                  {p.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label>API Key</Label>
          <div className="relative">
            <Input
              type={showKey ? "text" : "password"}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={selectedProvider?.placeholder ?? "Enter your API key..."}
              className="pr-10 font-mono text-sm"
              autoComplete="off"
            />
            <button
              type="button"
              onClick={() => setShowKey(!showKey)}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
            >
              {showKey ? (
                <EyeOff className="h-4 w-4" />
              ) : (
                <Eye className="h-4 w-4" />
              )}
            </button>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Minimum 10 characters. Get your key from your provider's dashboard.
          </p>
        </div>

        <div className="space-y-2">
          <Label>
            Label <span className="text-muted-foreground font-normal">(optional)</span>
          </Label>
          <Input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="e.g., Production, Personal, Team"
            maxLength={255}
          />
          <p className="text-[11px] text-muted-foreground">
            Useful if you have multiple keys for the same provider.
          </p>
        </div>
      </div>
    </FormDialog>
  )
}
