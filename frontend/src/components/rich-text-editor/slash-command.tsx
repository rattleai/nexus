import { Extension } from "@tiptap/react"
import type { Editor, Range } from "@tiptap/react"
import { ReactRenderer } from "@tiptap/react"
import Suggestion from "@tiptap/suggestion"
import type { SuggestionOptions, SuggestionProps } from "@tiptap/suggestion"
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useState,
} from "react"
import {
  Heading1,
  Heading2,
  Heading3,
  List,
  ListOrdered,
  Quote,
  Code2,
  Image,
  Minus,
  type LucideIcon,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { ScrollArea } from "@/components/ui/scroll-area"

export interface SlashCommandItem {
  title: string
  description: string
  icon: LucideIcon
  command: (editor: Editor) => void
}

const defaultSlashCommands: SlashCommandItem[] = [
  {
    title: "Heading 1",
    description: "Large section heading",
    icon: Heading1,
    command: (editor) =>
      editor.chain().focus().toggleHeading({ level: 1 }).run(),
  },
  {
    title: "Heading 2",
    description: "Medium section heading",
    icon: Heading2,
    command: (editor) =>
      editor.chain().focus().toggleHeading({ level: 2 }).run(),
  },
  {
    title: "Heading 3",
    description: "Small section heading",
    icon: Heading3,
    command: (editor) =>
      editor.chain().focus().toggleHeading({ level: 3 }).run(),
  },
  {
    title: "Bullet List",
    description: "Create a simple bullet list",
    icon: List,
    command: (editor) => editor.chain().focus().toggleBulletList().run(),
  },
  {
    title: "Ordered List",
    description: "Create a numbered list",
    icon: ListOrdered,
    command: (editor) => editor.chain().focus().toggleOrderedList().run(),
  },
  {
    title: "Quote",
    description: "Add a blockquote",
    icon: Quote,
    command: (editor) => editor.chain().focus().toggleBlockquote().run(),
  },
  {
    title: "Code Block",
    description: "Add a code block",
    icon: Code2,
    command: (editor) => editor.chain().focus().toggleCodeBlock().run(),
  },
  {
    title: "Image",
    description: "Insert an image from URL",
    icon: Image,
    command: (editor) => {
      const url = window.prompt("Enter image URL")
      if (url) {
        editor.chain().focus().setImage({ src: url }).run()
      }
    },
  },
  {
    title: "Divider",
    description: "Insert a horizontal divider",
    icon: Minus,
    command: (editor) => editor.chain().focus().setHorizontalRule().run(),
  },
]

interface SlashCommandListProps {
  items: SlashCommandItem[]
  command: (item: SlashCommandItem) => void
}

interface SlashCommandListRef {
  onKeyDown: (props: { event: KeyboardEvent }) => boolean
}

const SlashCommandList = forwardRef<SlashCommandListRef, SlashCommandListProps>(
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
      return (
        <div className="z-50 overflow-hidden rounded-md border bg-popover p-2 shadow-md">
          <p className="text-sm text-muted-foreground">No results</p>
        </div>
      )
    }

    return (
      <div className="z-50 min-w-[200px] overflow-hidden rounded-md border bg-popover shadow-md">
        <ScrollArea className="max-h-72">
          <div className="p-1">
            {items.map((item, index) => {
              const Icon = item.icon
              return (
                <button
                  key={item.title}
                  type="button"
                  className={cn(
                    "flex w-full items-center gap-3 rounded-sm px-2 py-1.5 text-left text-sm outline-none",
                    index === selectedIndex
                      ? "bg-accent text-accent-foreground"
                      : "text-popover-foreground hover:bg-accent hover:text-accent-foreground",
                  )}
                  onClick={() => selectItem(index)}
                >
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border bg-background">
                    <Icon className="h-4 w-4" />
                  </div>
                  <div className="flex flex-col">
                    <span className="font-medium">{item.title}</span>
                    <span className="text-xs text-muted-foreground">
                      {item.description}
                    </span>
                  </div>
                </button>
              )
            })}
          </div>
        </ScrollArea>
      </div>
    )
  },
)

SlashCommandList.displayName = "SlashCommandList"

function createSlashCommandSuggestion(
  commands: SlashCommandItem[] = defaultSlashCommands,
): Omit<SuggestionOptions<SlashCommandItem>, "editor"> {
  return {
    char: "/",
    allowSpaces: false,
    startOfLine: false,
    items: ({ query }: { query: string }) => {
      return commands.filter((item) =>
        item.title.toLowerCase().includes(query.toLowerCase()),
      )
    },
    render: () => {
      let component: ReactRenderer<SlashCommandListRef> | null = null
      let popup: HTMLDivElement | null = null

      return {
        onStart: (props: SuggestionProps<SlashCommandItem>) => {
          component = new ReactRenderer(SlashCommandList, {
            props: {
              ...props,
              command: (item: SlashCommandItem) => {
                // Delete the slash command text
                props.editor
                  .chain()
                  .focus()
                  .deleteRange(props.range)
                  .run()
                // Then run the actual command
                item.command(props.editor)
              },
            },
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

        onUpdate: (props: SuggestionProps<SlashCommandItem>) => {
          component?.updateProps({
            ...props,
            command: (item: SlashCommandItem) => {
              props.editor
                .chain()
                .focus()
                .deleteRange(props.range)
                .run()
              item.command(props.editor)
            },
          })

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
  }
}

export const SlashCommand = Extension.create({
  name: "slashCommand",

  addOptions() {
    return {
      commands: defaultSlashCommands,
    }
  },

  addProseMirrorPlugins() {
    return [
      Suggestion({
        editor: this.editor,
        ...createSlashCommandSuggestion(this.options.commands),
      }),
    ]
  },
})

export { SlashCommandList, defaultSlashCommands, createSlashCommandSuggestion }
