import { useState, useMemo } from "react"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ClipboardList, Pencil, Save, Check } from "lucide-react"
import { useCompleteSession, useCreateTemplate } from "@/hooks/use-configurator"
import { toast } from "sonner"
import type { Characteristic, CharacteristicGroup } from "@/types/configurator"

interface ConfigurationSummaryProps {
  sessionId: string
  productId: string
  selections: Record<string, string>
  characteristics: Characteristic[]
  characteristicGroups: CharacteristicGroup[]
  onStepJump: (stepIndex: number) => void
}

// ── Currency formatter ────────────────────────────────────

const currencyFormatter = new Intl.NumberFormat("de-DE", {
  style: "currency",
  currency: "EUR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

function formatCurrency(value: number): string {
  return currencyFormatter.format(value)
}

// ── Main component ────────────────────────────────────────

export function ConfigurationSummary({
  sessionId,
  productId,
  selections,
  characteristics,
  characteristicGroups,
  onStepJump,
}: ConfigurationSummaryProps) {
  const [open, setOpen] = useState(false)
  const [templateDialogOpen, setTemplateDialogOpen] = useState(false)
  const [templateName, setTemplateName] = useState("")
  const [templateDescription, setTemplateDescription] = useState("")

  const completeSession = useCompleteSession()
  const createTemplate = useCreateTemplate()

  // Build a map of characteristics by group
  const sortedGroups = useMemo(
    () => [...characteristicGroups].sort((a, b) => a.display_order - b.display_order),
    [characteristicGroups],
  )

  const charMap = useMemo(
    () => new Map(characteristics.map((c) => [c.slug, c])),
    [characteristics],
  )

  const charsByGroup = useMemo(() => {
    const map = new Map<string | null, Characteristic[]>()
    for (const char of characteristics) {
      const key = char.group_id
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(char)
    }
    for (const [, chars] of map) {
      chars.sort((a, b) => a.display_order - b.display_order)
    }
    return map
  }, [characteristics])

  // Find the step index for a group
  const groupStepIndex = useMemo(() => {
    const indexMap = new Map<string, number>()
    let idx = 0
    for (const group of sortedGroups) {
      const chars = charsByGroup.get(group.id) ?? []
      if (chars.length > 0) {
        indexMap.set(group.id, idx)
        idx++
      }
    }
    // Ungrouped gets the last index
    const ungrouped = charsByGroup.get(null) ?? []
    if (ungrouped.length > 0) {
      indexMap.set("_ungrouped", idx)
    }
    return indexMap
  }, [sortedGroups, charsByGroup])

  // Count selections
  const totalRequired = characteristics.filter((c) => c.is_required).length
  const totalSelected = Object.keys(selections).length
  const totalCharacteristics = characteristics.length

  // Build grouped summary data
  const groupedSummary = useMemo(() => {
    const result: {
      groupId: string | null
      groupName: string
      stepIndex: number
      items: {
        charName: string
        selectedLabel: string
        priceAdjustment: number | null
      }[]
    }[] = []

    for (const group of sortedGroups) {
      const chars = charsByGroup.get(group.id) ?? []
      if (chars.length === 0) continue

      const items = chars
        .filter((c) => selections[c.slug] !== undefined)
        .map((c) => {
          const selectedValue = selections[c.slug]
          const valueObj = c.values.find((v) => v.value === selectedValue)
          return {
            charName: c.name,
            selectedLabel: valueObj?.label ?? selectedValue,
            priceAdjustment: valueObj?.price_adjustment ?? null,
          }
        })

      result.push({
        groupId: group.id,
        groupName: group.name,
        stepIndex: groupStepIndex.get(group.id) ?? 0,
        items,
      })
    }

    // Ungrouped characteristics
    const ungrouped = charsByGroup.get(null) ?? []
    if (ungrouped.length > 0) {
      const items = ungrouped
        .filter((c) => selections[c.slug] !== undefined)
        .map((c) => {
          const selectedValue = selections[c.slug]
          const valueObj = c.values.find((v) => v.value === selectedValue)
          return {
            charName: c.name,
            selectedLabel: valueObj?.label ?? selectedValue,
            priceAdjustment: valueObj?.price_adjustment ?? null,
          }
        })

      result.push({
        groupId: null,
        groupName: "General",
        stepIndex: groupStepIndex.get("_ungrouped") ?? 0,
        items,
      })
    }

    return result
  }, [sortedGroups, charsByGroup, selections, groupStepIndex])

  // ── Handlers ────────────────────────────────────────────

  const handleComplete = () => {
    completeSession.mutate(sessionId, {
      onSuccess: () => {
        setOpen(false)
      },
      onError: () => {
        toast.error("Cannot complete configuration. Please ensure all required selections are made.")
      },
    })
  }

  const handleSaveTemplate = () => {
    if (!templateName.trim()) {
      toast.error("Please enter a template name")
      return
    }

    // Convert selections to the template format
    const templateSelections = Object.entries(selections).map(([slug, value]) => {
      const char = charMap.get(slug)
      return {
        characteristic_id: char?.id ?? slug,
        value,
      }
    })

    createTemplate.mutate(
      {
        product_id: productId,
        name: templateName.trim(),
        description: templateDescription.trim() || undefined,
        is_partial: totalSelected < totalCharacteristics,
        selections: templateSelections as unknown as Record<string, string>[],
      },
      {
        onSuccess: () => {
          setTemplateDialogOpen(false)
          setTemplateName("")
          setTemplateDescription("")
        },
        onError: () => {
          toast.error("Failed to save template")
        },
      },
    )
  }

  const handleStepJump = (stepIndex: number) => {
    onStepJump(stepIndex)
    setOpen(false)
  }

  return (
    <>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
          <Button variant="outline" size="sm">
            <ClipboardList className="h-3.5 w-3.5 mr-1.5" />
            Summary
            {totalSelected > 0 && (
              <Badge variant="secondary" className="ml-1.5 h-5 px-1.5 text-[10px]">
                {totalSelected}
              </Badge>
            )}
          </Button>
        </SheetTrigger>

        <SheetContent side="right" className="w-full sm:max-w-md flex flex-col">
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2">
              <ClipboardList className="h-5 w-5" />
              Configuration Summary
            </SheetTitle>
          </SheetHeader>

          {/* Progress indicator */}
          <div className="flex items-center justify-between text-sm px-1 mt-2">
            <span className="text-muted-foreground">Selections</span>
            <span className="font-medium tabular-nums">
              {totalSelected} / {totalCharacteristics}
              {totalRequired > 0 && (
                <span className="text-muted-foreground ml-1">
                  ({totalRequired} required)
                </span>
              )}
            </span>
          </div>

          <Separator className="my-3" />

          {/* Grouped selections */}
          <div className="flex-1 overflow-y-auto space-y-5 pr-1">
            {groupedSummary.map((group) => (
              <div key={group.groupId ?? "_ungrouped"}>
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-sm font-semibold">{group.groupName}</h4>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-xs"
                    onClick={() => handleStepJump(group.stepIndex)}
                  >
                    <Pencil className="h-3 w-3 mr-1" />
                    Edit
                  </Button>
                </div>

                {group.items.length === 0 ? (
                  <p className="text-xs text-muted-foreground italic pl-1">
                    No selections made
                  </p>
                ) : (
                  <div className="space-y-1.5">
                    {group.items.map((item) => (
                      <div
                        key={item.charName}
                        className="flex items-center justify-between rounded-md border bg-muted/30 px-3 py-2"
                      >
                        <div className="min-w-0">
                          <p className="text-xs text-muted-foreground truncate">
                            {item.charName}
                          </p>
                          <p className="text-sm font-medium truncate">
                            {item.selectedLabel}
                          </p>
                        </div>
                        {item.priceAdjustment != null && item.priceAdjustment !== 0 && (
                          <Badge
                            variant={item.priceAdjustment > 0 ? "default" : "secondary"}
                            className="ml-2 shrink-0 text-[10px]"
                          >
                            {item.priceAdjustment > 0 ? "+" : ""}
                            {formatCurrency(item.priceAdjustment)}
                          </Badge>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}

            {groupedSummary.every((g) => g.items.length === 0) && (
              <div className="flex items-center justify-center h-32 text-muted-foreground text-sm">
                No selections have been made yet.
              </div>
            )}
          </div>

          <Separator className="my-3" />

          {/* Action buttons */}
          <div className="flex flex-col gap-2 pb-2">
            <Button
              variant="outline"
              className="w-full"
              onClick={() => setTemplateDialogOpen(true)}
              disabled={totalSelected === 0}
            >
              <Save className="h-4 w-4 mr-2" />
              Save as Template
            </Button>
            <Button
              className="w-full"
              onClick={handleComplete}
              disabled={completeSession.isPending || totalSelected === 0}
            >
              <Check className="h-4 w-4 mr-2" />
              {completeSession.isPending ? "Completing..." : "Complete Configuration"}
            </Button>
          </div>
        </SheetContent>
      </Sheet>

      {/* Save as Template dialog */}
      <Dialog open={templateDialogOpen} onOpenChange={setTemplateDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Save as Template</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label htmlFor="template-name">Template Name</Label>
              <Input
                id="template-name"
                placeholder="e.g. Standard Configuration"
                value={templateName}
                onChange={(e) => setTemplateName(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="template-description">Description (optional)</Label>
              <Input
                id="template-description"
                placeholder="Brief description of this template..."
                value={templateDescription}
                onChange={(e) => setTemplateDescription(e.target.value)}
              />
            </div>
            <p className="text-xs text-muted-foreground">
              This template will save {totalSelected} selection{totalSelected !== 1 ? "s" : ""}.
              {totalSelected < totalCharacteristics && " It will be marked as a partial template."}
            </p>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setTemplateDialogOpen(false)
                setTemplateName("")
                setTemplateDescription("")
              }}
            >
              Cancel
            </Button>
            <Button
              onClick={handleSaveTemplate}
              disabled={createTemplate.isPending || !templateName.trim()}
            >
              {createTemplate.isPending ? "Saving..." : "Save Template"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
