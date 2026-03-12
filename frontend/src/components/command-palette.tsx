import * as React from "react"
import type { LucideIcon } from "lucide-react"
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from "@/components/ui/command"

export interface CommandAction {
  id: string
  label: string
  icon?: LucideIcon
  shortcut?: string
  group?: string
  onSelect: () => void
}

interface CommandPaletteProps {
  actions: CommandAction[]
  open?: boolean
  onOpenChange?: (open: boolean) => void
  placeholder?: string
}

export function CommandPalette({
  actions,
  open: controlledOpen,
  onOpenChange,
  placeholder = "Type a command or search...",
}: CommandPaletteProps) {
  const [internalOpen, setInternalOpen] = React.useState(false)

  const isControlled = controlledOpen !== undefined
  const open = isControlled ? controlledOpen : internalOpen

  const handleOpenChange = React.useCallback(
    (value: boolean) => {
      if (!isControlled) {
        setInternalOpen(value)
      }
      onOpenChange?.(value)
    },
    [isControlled, onOpenChange],
  )

  React.useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault()
        handleOpenChange(!open)
      }
    }
    document.addEventListener("keydown", handleKeyDown)
    return () => document.removeEventListener("keydown", handleKeyDown)
  }, [open, handleOpenChange])

  const grouped = React.useMemo(() => {
    const groups = new Map<string, CommandAction[]>()
    for (const action of actions) {
      const key = action.group ?? ""
      const existing = groups.get(key)
      if (existing) {
        existing.push(action)
      } else {
        groups.set(key, [action])
      }
    }
    return groups
  }, [actions])

  return (
    <CommandDialog open={open} onOpenChange={handleOpenChange}>
      <CommandInput placeholder={placeholder} />
      <CommandList>
        <CommandEmpty>No results found.</CommandEmpty>
        {[...grouped.entries()].map(([group, items]) => (
          <CommandGroup key={group} heading={group || undefined}>
            {items.map((action) => {
              const Icon = action.icon
              return (
                <CommandItem
                  key={action.id}
                  value={action.label}
                  onSelect={() => {
                    action.onSelect()
                    handleOpenChange(false)
                  }}
                >
                  {Icon && <Icon className="mr-2 h-4 w-4" />}
                  <span>{action.label}</span>
                  {action.shortcut && (
                    <CommandShortcut>{action.shortcut}</CommandShortcut>
                  )}
                </CommandItem>
              )
            })}
          </CommandGroup>
        ))}
      </CommandList>
    </CommandDialog>
  )
}
