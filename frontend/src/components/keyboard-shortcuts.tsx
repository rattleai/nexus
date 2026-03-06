import { cn } from "@/lib/utils"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"

export interface ShortcutGroup {
  title: string
  shortcuts: Array<{ keys: string[]; description: string }>
}

interface KeyboardShortcutsDialogProps {
  groups: ShortcutGroup[]
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function KeyboardShortcutsDialog({
  groups,
  open,
  onOpenChange,
}: KeyboardShortcutsDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Keyboard Shortcuts</DialogTitle>
          <DialogDescription>
            Quick reference for available keyboard shortcuts.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-6 pt-2">
          {groups.map((group) => (
            <div key={group.title}>
              <h3 className="mb-3 text-sm font-medium text-muted-foreground">
                {group.title}
              </h3>
              <div className="space-y-2">
                {group.shortcuts.map((shortcut) => (
                  <div
                    key={shortcut.description}
                    className="flex items-center justify-between"
                  >
                    <span className="text-sm text-foreground">
                      {shortcut.description}
                    </span>
                    <div className="flex items-center gap-1">
                      {shortcut.keys.map((key, index) => (
                        <span key={index}>
                          <kbd
                            className={cn(
                              "inline-flex h-6 min-w-6 items-center justify-center rounded border border-border bg-muted px-1.5 text-xs font-medium text-muted-foreground",
                            )}
                          >
                            {key}
                          </kbd>
                          {index < shortcut.keys.length - 1 && (
                            <span className="mx-0.5 text-xs text-muted-foreground">
                              +
                            </span>
                          )}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
