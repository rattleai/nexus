import * as React from "react"
import { useTranslation } from "react-i18next"
import { Check, ChevronDown, Cpu } from "lucide-react"
import { cn } from "@/lib/utils"
import { formatCompactNumber } from "@/lib/format"
import { Button } from "@/components/ui/button"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command"
import { Badge } from "@/components/ui/badge"
import type { AIModel } from "@/types/ai"

export type { AIModel }

export interface ModelSelectorProps {
  models: AIModel[]
  value?: string
  onChange: (modelId: string) => void
  placeholder?: string
  className?: string
}

function ProviderBadge({ provider }: { provider: string }) {
  const letter = provider.charAt(0).toUpperCase()
  return (
    <Badge
      variant="outline"
      className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full p-0 text-[10px] font-bold"
      aria-label={provider}
    >
      {letter}
    </Badge>
  )
}

function groupModelsByProvider(models: AIModel[]): Record<string, AIModel[]> {
  return models.reduce<Record<string, AIModel[]>>((acc, model) => {
    const group = acc[model.provider] ?? []
    group.push(model)
    acc[model.provider] = group
    return acc
  }, {})
}

export function ModelSelector({
  models,
  value,
  onChange,
  placeholder,
  className,
}: ModelSelectorProps) {
  const { t } = useTranslation("ai")
  const resolvedPlaceholder = placeholder ?? t("model_selector.placeholder")
  const [open, setOpen] = React.useState(false)
  const selectedModel = models.find((m) => m.id === value)
  const grouped = React.useMemo(() => groupModelsByProvider(models), [models])

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          aria-label="Select AI model"
          className={cn("w-full justify-between", className)}
        >
          <span className="flex items-center gap-2 truncate">
            {selectedModel ? (
              <>
                <ProviderBadge provider={selectedModel.provider} />
                <span className="truncate">{selectedModel.name}</span>
              </>
            ) : (
              <>
                <Cpu className="h-4 w-4 text-muted-foreground" />
                <span className="text-muted-foreground">{resolvedPlaceholder}</span>
              </>
            )}
          </span>
          <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[340px] p-0" align="start">
        <Command>
          <CommandInput placeholder={t("model_selector.search_placeholder")} />
          <CommandList>
            <CommandEmpty>{t("model_selector.no_models")}</CommandEmpty>
            {Object.entries(grouped).map(([provider, providerModels]) => (
              <CommandGroup key={provider} heading={provider}>
                {providerModels.map((model) => (
                  <CommandItem
                    key={model.id}
                    value={`${model.provider} ${model.name}`}
                    onSelect={() => {
                      onChange(model.id)
                      setOpen(false)
                    }}
                  >
                    <div className="flex w-full items-start gap-2">
                      <ProviderBadge provider={model.provider} />
                      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-sm font-medium">
                            {model.name}
                          </span>
                          {value === model.id && (
                            <Check className="h-4 w-4 shrink-0 text-primary" />
                          )}
                        </div>
                        {model.description && (
                          <span className="text-xs text-muted-foreground line-clamp-1">
                            {model.description}
                          </span>
                        )}
                        {model.contextWindow && (
                          <span className="text-xs text-muted-foreground">
                            Context: {formatCompactNumber(model.contextWindow)} tokens
                          </span>
                        )}
                      </div>
                    </div>
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
