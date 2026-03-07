"use client"

import * as React from "react"
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
  DragOverlay,
  useDroppable,
} from "@dnd-kit/core"
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable"
import { cn } from "@/lib/utils"

export interface KanbanCard {
  id: string
  title: string
  description?: string
  labels?: Array<{ text: string; color: string }>
}

export interface KanbanColumn {
  id: string
  title: string
  cards: KanbanCard[]
}

interface KanbanBoardProps {
  columns: KanbanColumn[]
  onCardMove: (
    cardId: string,
    fromColumn: string,
    toColumn: string,
    newIndex: number,
  ) => void
  renderCard?: (card: KanbanCard) => React.ReactNode
  className?: string
}

export function KanbanBoard({
  columns,
  onCardMove,
  renderCard,
  className,
}: KanbanBoardProps) {
  const [activeCard, setActiveCard] = React.useState<KanbanCard | null>(null)

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  )

  function findColumnForCard(cardId: string): KanbanColumn | undefined {
    return columns.find((col) => col.cards.some((c) => c.id === cardId))
  }

  function handleDragStart(event: DragStartEvent) {
    const card = columns
      .flatMap((col) => col.cards)
      .find((c) => c.id === event.active.id)
    setActiveCard(card ?? null)
  }

  function handleDragEnd(event: DragEndEvent) {
    setActiveCard(null)
    const { active, over } = event
    if (!over) return

    const activeId = String(active.id)
    const overId = String(over.id)
    const sourceColumn = findColumnForCard(activeId)
    if (!sourceColumn) return

    // Dropped on a column directly
    const targetColumn = columns.find((col) => col.id === overId)
    if (targetColumn) {
      onCardMove(activeId, sourceColumn.id, targetColumn.id, targetColumn.cards.length)
      return
    }

    // Dropped on another card
    const overColumn = findColumnForCard(overId)
    if (!overColumn) return

    const newIndex = overColumn.cards.findIndex((c) => c.id === overId)
    onCardMove(activeId, sourceColumn.id, overColumn.id, newIndex)
  }

  const cardRenderer = renderCard ?? defaultRenderCard

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      <div
        className={cn(
          "flex gap-4 overflow-x-auto p-1",
          className,
        )}
        role="region"
        aria-label="Kanban board"
      >
        {columns.map((column) => (
          <Column
            key={column.id}
            column={column}
            renderCard={cardRenderer}
          />
        ))}
      </div>

      <DragOverlay>
        {activeCard ? (
          <div className="rotate-2 opacity-90">
            {cardRenderer(activeCard)}
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  )
}

function Column({
  column,
  renderCard,
}: {
  column: KanbanColumn
  renderCard: (card: KanbanCard) => React.ReactNode
}) {
  const { setNodeRef, isOver } = useDroppable({ id: column.id })

  return (
    <div
      ref={setNodeRef}
      className={cn(
        "flex w-72 shrink-0 flex-col rounded-lg bg-muted/50 p-3",
        isOver && "ring-2 ring-primary/30",
      )}
    >
      {/* Column header */}
      <div className="mb-3 flex items-center justify-between px-1">
        <h3 className="text-sm font-semibold text-foreground">
          {column.title}
        </h3>
        <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-muted px-1.5 text-xs font-medium text-muted-foreground">
          {column.cards.length}
        </span>
      </div>

      {/* Cards */}
      <SortableContext
        items={column.cards.map((c) => c.id)}
        strategy={verticalListSortingStrategy}
      >
        <div className="flex flex-1 flex-col gap-2">
          {column.cards.map((card) => (
            <SortableCard key={card.id} card={card} renderCard={renderCard} />
          ))}
        </div>
      </SortableContext>
    </div>
  )
}

function SortableCard({
  card,
  renderCard,
}: {
  card: KanbanCard
  renderCard: (card: KanbanCard) => React.ReactNode
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: card.id })

  const style: React.CSSProperties = {
    transform: transform
      ? `translate3d(${transform.x}px, ${transform.y}px, 0)`
      : undefined,
    transition,
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(isDragging && "opacity-30")}
      {...attributes}
      {...listeners}
    >
      {renderCard(card)}
    </div>
  )
}

function defaultRenderCard(card: KanbanCard) {
  return (
    <div className="rounded-md border bg-background p-3 shadow-sm transition-shadow hover:shadow-md">
      <p className="text-sm font-medium text-foreground">{card.title}</p>
      {card.description && (
        <p className="mt-1 text-xs text-muted-foreground line-clamp-2">
          {card.description}
        </p>
      )}
      {card.labels && card.labels.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {card.labels.map((label) => (
            <span
              key={label.text}
              className="inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium"
              style={{
                backgroundColor: `${label.color}20`,
                color: label.color,
              }}
            >
              {label.text}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
