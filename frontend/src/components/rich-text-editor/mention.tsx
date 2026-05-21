import { ReactRenderer } from "@tiptap/react"
import Mention from "@tiptap/extension-mention"
import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useState,
  useCallback,
} from "react"
import { cn } from "@/lib/utils"
import { ScrollArea } from "@/components/ui/scroll-area"

export interface MentionSuggestion {
  id: string
  label: string
}

interface MentionListProps {
  items: MentionSuggestion[]
  command: (item: MentionSuggestion) => void
}

interface MentionListRef {
  onKeyDown: (props: { event: KeyboardEvent }) => boolean
}

const MentionList = forwardRef<MentionListRef, MentionListProps>(
  ({ items, command }, ref) => {
    const [selectedIndex, setSelectedIndex] = useState(0)

    useEffect(() => {
      setSelectedIndex(0)
    }, [items])

    const selectItem = useCallback(
      (index: number) => {
        const item = items[index]
        if (item) {
          command(item)
        }
      },
      [items, command],
    )

    useImperativeHandle(ref, () => ({
      onKeyDown: ({ event }: { event: KeyboardEvent }) => {
        if (event.key === "ArrowUp") {
          setSelectedIndex((prev) =>
            prev <= 0 ? items.length - 1 : prev - 1,
          )
          return true
        }

        if (event.key === "ArrowDown") {
          setSelectedIndex((prev) =>
            prev >= items.length - 1 ? 0 : prev + 1,
          )
          return true
        }

        if (event.key === "Enter") {
          selectItem(selectedIndex)
          return true
        }

        return false
      },
    }))

    if (items.length === 0) {
      return null
    }

    return (
      <div className="z-50 overflow-hidden rounded-md border bg-popover shadow-md">
        <ScrollArea className="max-h-48">
          <div className="p-1">
            {items.map((item, index) => (
              <button
                key={item.id}
                type="button"
                className={cn(
                  "flex w-full items-center rounded-sm px-2 py-1.5 text-sm outline-none",
                  index === selectedIndex
                    ? "bg-accent text-accent-foreground"
                    : "text-popover-foreground hover:bg-accent hover:text-accent-foreground",
                )}
                onClick={() => selectItem(index)}
              >
                <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary">
                  {item.label.charAt(0).toUpperCase()}
                </span>
                <span className="ml-2 truncate">{item.label}</span>
              </button>
            ))}
          </div>
        </ScrollArea>
      </div>
    )
  },
)

MentionList.displayName = "MentionList"

export function createMentionExtension(items: MentionSuggestion[]) {
  return Mention.configure({
    HTMLAttributes: {
      class:
        "mention inline-flex items-center rounded-md bg-primary/10 px-1.5 py-0.5 text-sm font-medium text-primary no-underline",
    },
    suggestion: {
      items: ({ query }: { query: string }) => {
        return items
          .filter((item) =>
            item.label.toLowerCase().startsWith(query.toLowerCase()),
          )
          .slice(0, 8)
      },
      render: () => {
        let component: ReactRenderer<MentionListRef> | null = null
        let popup: HTMLDivElement | null = null

        return {
          onStart: (props) => {
            component = new ReactRenderer(MentionList, {
              props,
              editor: props.editor,
            })

            if (!props.clientRect) return

            popup = document.createElement("div")
            popup.style.position = "absolute"
            popup.style.zIndex = "50"
            document.body.appendChild(popup)

            const rect = props.clientRect?.()
            if (rect && popup) {
              popup.style.left = `${rect.left}px`
              popup.style.top = `${rect.bottom + 4}px`
            }

            popup.appendChild(component.element)
          },

          onUpdate: (props) => {
            component?.updateProps(props)

            if (!props.clientRect) return

            const rect = props.clientRect?.()
            if (rect && popup) {
              popup.style.left = `${rect.left}px`
              popup.style.top = `${rect.bottom + 4}px`
            }
          },

          onKeyDown: (props) => {
            if (props.event.key === "Escape") {
              popup?.remove()
              popup = null
              component?.destroy()
              component = null
              return true
            }

            return component?.ref?.onKeyDown(props) ?? false
          },

          onExit: () => {
            popup?.remove()
            popup = null
            component?.destroy()
            component = null
          },
        }
      },
    },
  })
}

export { MentionList }
