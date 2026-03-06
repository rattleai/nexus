import type { Editor } from "@tiptap/react"
import { useCallback, useState } from "react"
import {
  Bold,
  Italic,
  Strikethrough,
  Code,
  Heading1,
  Heading2,
  Heading3,
  List,
  ListOrdered,
  Quote,
  Link,
  Image,
  Undo,
  Redo,
  Unlink,
  Check,
} from "lucide-react"
import { Toggle } from "@/components/ui/toggle"
import { Separator } from "@/components/ui/separator"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

export interface EditorToolbarProps {
  editor: Editor | null
  className?: string
}

function ToolbarToggle({
  pressed,
  onPressedChange,
  disabled,
  title,
  children,
}: {
  pressed: boolean
  onPressedChange: () => void
  disabled?: boolean
  title: string
  children: React.ReactNode
}) {
  return (
    <Toggle
      size="sm"
      pressed={pressed}
      onPressedChange={onPressedChange}
      disabled={disabled}
      aria-label={title}
      title={title}
    >
      {children}
    </Toggle>
  )
}

function LinkPopover({ editor }: { editor: Editor }) {
  const [url, setUrl] = useState("")
  const [open, setOpen] = useState(false)

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault()
      if (url.trim()) {
        editor
          .chain()
          .focus()
          .extendMarkRange("link")
          .setLink({ href: url.trim() })
          .run()
      }
      setUrl("")
      setOpen(false)
    },
    [editor, url],
  )

  const handleRemoveLink = useCallback(() => {
    editor.chain().focus().extendMarkRange("link").unsetLink().run()
    setOpen(false)
  }, [editor])

  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      setOpen(nextOpen)
      if (nextOpen) {
        const existingHref = editor.getAttributes("link").href as
          | string
          | undefined
        setUrl(existingHref ?? "")
      }
    },
    [editor],
  )

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Toggle
          size="sm"
          pressed={editor.isActive("link")}
          aria-label="Link"
          title="Link"
        >
          <Link className="h-4 w-4" />
        </Toggle>
      </PopoverTrigger>
      <PopoverContent className="w-80" align="start">
        <form onSubmit={handleSubmit} className="flex flex-col gap-2">
          <p className="text-sm font-medium">Insert Link</p>
          <div className="flex gap-2">
            <Input
              placeholder="https://example.com"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
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
  )
}

function ImagePopover({ editor }: { editor: Editor }) {
  const [url, setUrl] = useState("")
  const [open, setOpen] = useState(false)

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault()
      if (url.trim()) {
        editor.chain().focus().setImage({ src: url.trim() }).run()
      }
      setUrl("")
      setOpen(false)
    },
    [editor, url],
  )

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Toggle size="sm" pressed={false} aria-label="Image" title="Image">
          <Image className="h-4 w-4" />
        </Toggle>
      </PopoverTrigger>
      <PopoverContent className="w-80" align="start">
        <form onSubmit={handleSubmit} className="flex flex-col gap-2">
          <p className="text-sm font-medium">Insert Image</p>
          <div className="flex gap-2">
            <Input
              placeholder="https://example.com/image.png"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="h-8 text-sm"
              autoFocus
            />
            <Button type="submit" size="sm" className="h-8 px-2">
              <Check className="h-4 w-4" />
            </Button>
          </div>
        </form>
      </PopoverContent>
    </Popover>
  )
}

export function EditorToolbar({ editor, className }: EditorToolbarProps) {
  if (!editor) {
    return null
  }

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-0.5 border-b bg-muted/30 px-1 py-1",
        className,
      )}
    >
      {/* Text formatting */}
      <ToolbarToggle
        pressed={editor.isActive("bold")}
        onPressedChange={() => editor.chain().focus().toggleBold().run()}
        disabled={!editor.can().chain().focus().toggleBold().run()}
        title="Bold"
      >
        <Bold className="h-4 w-4" />
      </ToolbarToggle>

      <ToolbarToggle
        pressed={editor.isActive("italic")}
        onPressedChange={() => editor.chain().focus().toggleItalic().run()}
        disabled={!editor.can().chain().focus().toggleItalic().run()}
        title="Italic"
      >
        <Italic className="h-4 w-4" />
      </ToolbarToggle>

      <ToolbarToggle
        pressed={editor.isActive("strike")}
        onPressedChange={() => editor.chain().focus().toggleStrike().run()}
        disabled={!editor.can().chain().focus().toggleStrike().run()}
        title="Strikethrough"
      >
        <Strikethrough className="h-4 w-4" />
      </ToolbarToggle>

      <ToolbarToggle
        pressed={editor.isActive("code")}
        onPressedChange={() => editor.chain().focus().toggleCode().run()}
        disabled={!editor.can().chain().focus().toggleCode().run()}
        title="Inline code"
      >
        <Code className="h-4 w-4" />
      </ToolbarToggle>

      <Separator orientation="vertical" className="mx-1 h-6" />

      {/* Headings */}
      <ToolbarToggle
        pressed={editor.isActive("heading", { level: 1 })}
        onPressedChange={() =>
          editor.chain().focus().toggleHeading({ level: 1 }).run()
        }
        title="Heading 1"
      >
        <Heading1 className="h-4 w-4" />
      </ToolbarToggle>

      <ToolbarToggle
        pressed={editor.isActive("heading", { level: 2 })}
        onPressedChange={() =>
          editor.chain().focus().toggleHeading({ level: 2 }).run()
        }
        title="Heading 2"
      >
        <Heading2 className="h-4 w-4" />
      </ToolbarToggle>

      <ToolbarToggle
        pressed={editor.isActive("heading", { level: 3 })}
        onPressedChange={() =>
          editor.chain().focus().toggleHeading({ level: 3 }).run()
        }
        title="Heading 3"
      >
        <Heading3 className="h-4 w-4" />
      </ToolbarToggle>

      <Separator orientation="vertical" className="mx-1 h-6" />

      {/* Lists */}
      <ToolbarToggle
        pressed={editor.isActive("bulletList")}
        onPressedChange={() =>
          editor.chain().focus().toggleBulletList().run()
        }
        title="Bullet list"
      >
        <List className="h-4 w-4" />
      </ToolbarToggle>

      <ToolbarToggle
        pressed={editor.isActive("orderedList")}
        onPressedChange={() =>
          editor.chain().focus().toggleOrderedList().run()
        }
        title="Ordered list"
      >
        <ListOrdered className="h-4 w-4" />
      </ToolbarToggle>

      <ToolbarToggle
        pressed={editor.isActive("blockquote")}
        onPressedChange={() =>
          editor.chain().focus().toggleBlockquote().run()
        }
        title="Blockquote"
      >
        <Quote className="h-4 w-4" />
      </ToolbarToggle>

      <Separator orientation="vertical" className="mx-1 h-6" />

      {/* Link & Image */}
      <LinkPopover editor={editor} />
      <ImagePopover editor={editor} />

      <Separator orientation="vertical" className="mx-1 h-6" />

      {/* Undo/Redo */}
      <ToolbarToggle
        pressed={false}
        onPressedChange={() => editor.chain().focus().undo().run()}
        disabled={!editor.can().chain().focus().undo().run()}
        title="Undo"
      >
        <Undo className="h-4 w-4" />
      </ToolbarToggle>

      <ToolbarToggle
        pressed={false}
        onPressedChange={() => editor.chain().focus().redo().run()}
        disabled={!editor.can().chain().focus().redo().run()}
        title="Redo"
      >
        <Redo className="h-4 w-4" />
      </ToolbarToggle>
    </div>
  )
}
