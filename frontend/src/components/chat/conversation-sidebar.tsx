"use client"

import * as React from "react"
import {
  MoreHorizontal,
  Pin,
  Pencil,
  Trash2,
  Plus,
  Search,
  MessageSquare,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { cn } from "@/lib/utils"
import { formatRelativeTime } from "@/lib/format"

export interface Conversation {
  id: string
  title: string
  lastMessage?: string
  updatedAt: string
  pinned?: boolean
  folder?: string
}

interface ConversationSidebarProps {
  conversations: Conversation[]
  activeId?: string
  onSelect: (id: string) => void
  onCreate: () => void
  onDelete?: (id: string) => void
  onPin?: (id: string) => void
  onRename?: (id: string, title: string) => void
  className?: string
}

function ConversationItem({
  conversation,
  isActive,
  onSelect,
  onDelete,
  onPin,
  onRename,
}: {
  conversation: Conversation
  isActive: boolean
  onSelect: (id: string) => void
  onDelete?: (id: string) => void
  onPin?: (id: string) => void
  onRename?: (id: string, title: string) => void
}) {
  const [isEditing, setIsEditing] = React.useState(false)
  const [editTitle, setEditTitle] = React.useState(conversation.title)
  const inputRef = React.useRef<HTMLInputElement>(null)

  React.useEffect(() => {
    if (isEditing) {
      inputRef.current?.focus()
      inputRef.current?.select()
    }
  }, [isEditing])

  const handleRenameSubmit = () => {
    const trimmed = editTitle.trim()
    if (trimmed && trimmed !== conversation.title) {
      onRename?.(conversation.id, trimmed)
    } else {
      setEditTitle(conversation.title)
    }
    setIsEditing(false)
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSelect(conversation.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter") onSelect(conversation.id)
      }}
      className={cn(
        "group flex cursor-pointer items-start gap-2 rounded-md px-3 py-2 text-sm transition-colors",
        isActive
          ? "bg-accent text-accent-foreground"
          : "hover:bg-muted/50 text-foreground",
      )}
    >
      <MessageSquare className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />

      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        {isEditing ? (
          <input
            ref={inputRef}
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            onBlur={handleRenameSubmit}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleRenameSubmit()
              if (e.key === "Escape") {
                setEditTitle(conversation.title)
                setIsEditing(false)
              }
              e.stopPropagation()
            }}
            onClick={(e) => e.stopPropagation()}
            className="h-5 w-full rounded border border-input bg-background px-1 text-sm focus-visible:outline-none"
          />
        ) : (
          <span className="truncate font-medium">{conversation.title}</span>
        )}
        {conversation.lastMessage && (
          <span className="truncate text-xs text-muted-foreground">
            {conversation.lastMessage}
          </span>
        )}
        <span className="text-xs text-muted-foreground/60">
          {formatRelativeTime(conversation.updatedAt)}
        </span>
      </div>

      {(onDelete || onPin || onRename) && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6 shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
              onClick={(e) => e.stopPropagation()}
            >
              <MoreHorizontal className="h-3.5 w-3.5" />
              <span className="sr-only">Actions</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-40">
            {onRename && (
              <DropdownMenuItem
                onClick={(e) => {
                  e.stopPropagation()
                  setIsEditing(true)
                }}
              >
                <Pencil className="mr-2 h-3.5 w-3.5" />
                Rename
              </DropdownMenuItem>
            )}
            {onPin && (
              <DropdownMenuItem
                onClick={(e) => {
                  e.stopPropagation()
                  onPin(conversation.id)
                }}
              >
                <Pin className="mr-2 h-3.5 w-3.5" />
                {conversation.pinned ? "Unpin" : "Pin"}
              </DropdownMenuItem>
            )}
            {onDelete && (
              <DropdownMenuItem
                onClick={(e) => {
                  e.stopPropagation()
                  onDelete(conversation.id)
                }}
                className="text-destructive focus:text-destructive"
              >
                <Trash2 className="mr-2 h-3.5 w-3.5" />
                Delete
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  )
}

export function ConversationSidebar({
  conversations,
  activeId,
  onSelect,
  onCreate,
  onDelete,
  onPin,
  onRename,
  className,
}: ConversationSidebarProps) {
  const [search, setSearch] = React.useState("")

  const filtered = React.useMemo(() => {
    if (!search.trim()) return conversations
    const query = search.toLowerCase()
    return conversations.filter(
      (c) =>
        c.title.toLowerCase().includes(query) ||
        c.lastMessage?.toLowerCase().includes(query),
    )
  }, [conversations, search])

  const pinned = React.useMemo(
    () => filtered.filter((c) => c.pinned),
    [filtered],
  )
  const recent = React.useMemo(
    () => filtered.filter((c) => !c.pinned),
    [filtered],
  )

  return (
    <div
      className={cn(
        "flex h-full flex-col border-r border-border bg-background",
        className,
      )}
    >
      <div className="flex flex-col gap-2 p-3">
        <Button onClick={onCreate} className="w-full gap-2">
          <Plus className="h-4 w-4" />
          New Chat
        </Button>
        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search conversations..."
            className="h-8 pl-8 text-sm"
          />
        </div>
      </div>

      <ScrollArea className="flex-1 px-2">
        {pinned.length > 0 && (
          <div className="mb-2">
            <span className="flex items-center gap-1 px-3 pb-1 text-xs font-medium text-muted-foreground">
              <Pin className="h-3 w-3" />
              Pinned
            </span>
            {pinned.map((conversation) => (
              <ConversationItem
                key={conversation.id}
                conversation={conversation}
                isActive={conversation.id === activeId}
                onSelect={onSelect}
                onDelete={onDelete}
                onPin={onPin}
                onRename={onRename}
              />
            ))}
          </div>
        )}

        {recent.length > 0 && (
          <div>
            {pinned.length > 0 && (
              <span className="px-3 pb-1 text-xs font-medium text-muted-foreground">
                Recent
              </span>
            )}
            {recent.map((conversation) => (
              <ConversationItem
                key={conversation.id}
                conversation={conversation}
                isActive={conversation.id === activeId}
                onSelect={onSelect}
                onDelete={onDelete}
                onPin={onPin}
                onRename={onRename}
              />
            ))}
          </div>
        )}

        {filtered.length === 0 && (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">
            {search ? "No conversations found." : "No conversations yet."}
          </div>
        )}
      </ScrollArea>
    </div>
  )
}
