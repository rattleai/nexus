import { useEditor, EditorContent } from "@tiptap/react"
import { BubbleMenu } from "@tiptap/react/menus"
import StarterKit from "@tiptap/starter-kit"
import Placeholder from "@tiptap/extension-placeholder"
import Link from "@tiptap/extension-link"
import Image from "@tiptap/extension-image"
import { useCallback, useState } from "react"
import {
  Bold,
  Italic,
  Strikethrough,
  Link as LinkIcon,
  Unlink,
  Check,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { Toggle } from "@/components/ui/toggle"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { EditorToolbar } from "./toolbar"
import { createMentionExtension } from "./mention"
import { SlashCommand } from "./slash-command"
import type { MentionSuggestion } from "./mention"

export interface RichTextEditorProps {
  content?: string
  onChange?: (html: string) => void
  placeholder?: string
  editable?: boolean
  className?: string
  toolbar?: boolean
  mentions?: MentionSuggestion[]
}

function BubbleLinkEditor({ editor }: { editor: ReturnType<typeof useEditor> }) {
  const [linkUrl, setLinkUrl] = useState("")
  const [linkPopoverOpen, setLinkPopoverOpen] = useState(false)

  const handleSetLink = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault()
      if (!editor) return
      if (linkUrl.trim()) {
        editor
          .chain()
          .focus()
          .extendMarkRange("link")
          .setLink({ href: linkUrl.trim() })
          .run()
      }
      setLinkUrl("")
      setLinkPopoverOpen(false)
    },
    [editor, linkUrl],
  )

  const handleRemoveLink = useCallback(() => {
    if (!editor) return
    editor.chain().focus().extendMarkRange("link").unsetLink().run()
    setLinkPopoverOpen(false)
  }, [editor])

  if (!editor) return null

  return (
    <BubbleMenu
      editor={editor}
      className="flex items-center gap-0.5 overflow-hidden rounded-md border bg-background p-0.5 shadow-md"
    >
      <Toggle
        size="sm"
        pressed={editor.isActive("bold")}
        onPressedChange={() => editor.chain().focus().toggleBold().run()}
        aria-label="Bold"
      >
        <Bold className="h-3.5 w-3.5" />
      </Toggle>
      <Toggle
        size="sm"
        pressed={editor.isActive("italic")}
        onPressedChange={() => editor.chain().focus().toggleItalic().run()}
        aria-label="Italic"
      >
        <Italic className="h-3.5 w-3.5" />
      </Toggle>
      <Toggle
        size="sm"
        pressed={editor.isActive("strike")}
        onPressedChange={() => editor.chain().focus().toggleStrike().run()}
        aria-label="Strikethrough"
      >
        <Strikethrough className="h-3.5 w-3.5" />
      </Toggle>

      <Popover open={linkPopoverOpen} onOpenChange={(open) => {
        setLinkPopoverOpen(open)
        if (open) {
          const existingHref = editor.getAttributes("link").href as string | undefined
          setLinkUrl(existingHref ?? "")
        }
      }}>
        <PopoverTrigger asChild>
          <Toggle
            size="sm"
            pressed={editor.isActive("link")}
            aria-label="Link"
          >
            <LinkIcon className="h-3.5 w-3.5" />
          </Toggle>
        </PopoverTrigger>
        <PopoverContent className="w-72" align="start" side="top">
          <form onSubmit={handleSetLink} className="flex flex-col gap-2">
            <p className="text-sm font-medium">Edit Link</p>
            <div className="flex gap-2">
              <Input
                placeholder="https://example.com"
                value={linkUrl}
                onChange={(e) => setLinkUrl(e.target.value)}
                className="h-8 text-sm"
                autoFocus
              />
              <Button type="submit" size="sm" className="h-8 px-2">
                <Check className="h-4 w-4" />
              </Button>
            </div>
            {editor.isActive("link") && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-8 justify-start text-destructive hover:text-destructive"
                onClick={handleRemoveLink}
              >
                <Unlink className="mr-2 h-4 w-4" />
                Remove link
              </Button>
            )}
          </form>
        </PopoverContent>
      </Popover>
    </BubbleMenu>
  )
}

export function RichTextEditor({
  content = "",
  onChange,
  placeholder = "Start writing...",
  editable = true,
  className,
  toolbar = true,
  mentions,
}: RichTextEditorProps) {
  const extensions = [
    StarterKit.configure({
      heading: {
        levels: [1, 2, 3],
      },
    }),
    Placeholder.configure({
      placeholder,
      emptyEditorClass:
        "before:content-[attr(data-placeholder)] before:text-muted-foreground before:float-left before:h-0 before:pointer-events-none",
    }),
    Link.configure({
      openOnClick: false,
      HTMLAttributes: {
        class: "text-primary underline underline-offset-4 hover:text-primary/80 cursor-pointer",
      },
    }),
    Image.configure({
      HTMLAttributes: {
        class: "rounded-md border max-w-full h-auto",
      },
    }),
    SlashCommand,
    ...(mentions ? [createMentionExtension(mentions)] : []),
  ]

  const editor = useEditor({
    extensions,
    content,
    editable,
    immediatelyRender: true,
    onUpdate: ({ editor: currentEditor }) => {
      onChange?.(currentEditor.getHTML())
    },
    editorProps: {
      attributes: {
        class: cn(
          "prose prose-sm dark:prose-invert max-w-none focus:outline-none",
          "min-h-[120px] px-3 py-2",
          "[&_h1]:text-2xl [&_h1]:font-bold [&_h1]:mt-4 [&_h1]:mb-2",
          "[&_h2]:text-xl [&_h2]:font-semibold [&_h2]:mt-3 [&_h2]:mb-1.5",
          "[&_h3]:text-lg [&_h3]:font-medium [&_h3]:mt-2 [&_h3]:mb-1",
          "[&_ul]:list-disc [&_ul]:pl-6 [&_ul]:my-1.5",
          "[&_ol]:list-decimal [&_ol]:pl-6 [&_ol]:my-1.5",
          "[&_li]:my-0.5",
          "[&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-4 [&_blockquote]:italic [&_blockquote]:text-muted-foreground",
          "[&_pre]:rounded-md [&_pre]:bg-muted [&_pre]:p-3 [&_pre]:font-mono [&_pre]:text-sm",
          "[&_code]:rounded [&_code]:bg-muted [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-sm",
          "[&_hr]:border-border [&_hr]:my-4",
          "[&_img]:rounded-md [&_img]:border [&_img]:max-w-full",
          "[&_p]:my-1",
        ),
      },
    },
  })

  return (
    <div
      className={cn(
        "rounded-md border border-input bg-background ring-offset-background",
        "focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2",
        "overflow-hidden",
        className,
      )}
    >
      {toolbar && editable && <EditorToolbar editor={editor} />}
      {editor && editable && <BubbleLinkEditor editor={editor} />}
      <EditorContent editor={editor} />
    </div>
  )
}
