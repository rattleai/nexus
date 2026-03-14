import * as React from "react"
import { useTranslation } from "react-i18next"
import { useVirtualizer } from "@tanstack/react-virtual"
import { Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"

interface InfiniteListProps<T> {
  items: T[]
  renderItem: (item: T, index: number) => React.ReactNode
  estimateSize?: number
  loadMore?: () => void
  hasMore?: boolean
  isLoading?: boolean
  className?: string
}

export function InfiniteList<T>({
  items,
  renderItem,
  estimateSize = 50,
  loadMore,
  hasMore = false,
  isLoading = false,
  className,
}: InfiniteListProps<T>) {
  const { t } = useTranslation()
  const parentRef = React.useRef<HTMLDivElement>(null)
  const sentinelRef = React.useRef<HTMLDivElement>(null)

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => estimateSize,
    overscan: 5,
  })

  React.useEffect(() => {
    if (!sentinelRef.current || !loadMore || !hasMore || isLoading) return

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          loadMore()
        }
      },
      { root: parentRef.current, threshold: 0.1 },
    )

    observer.observe(sentinelRef.current)
    return () => observer.disconnect()
  }, [loadMore, hasMore, isLoading])

  return (
    <div
      ref={parentRef}
      className={cn("relative overflow-auto", className)}
      role="list"
    >
      <div
        className="relative w-full"
        style={{ height: `${virtualizer.getTotalSize()}px` }}
      >
        {virtualizer.getVirtualItems().map((virtualRow) => (
          <div
            key={virtualRow.key}
            className="absolute left-0 top-0 w-full"
            style={{
              height: `${virtualRow.size}px`,
              transform: `translateY(${virtualRow.start}px)`,
            }}
            role="listitem"
          >
            {renderItem(items[virtualRow.index], virtualRow.index)}
          </div>
        ))}
      </div>

      {/* Sentinel for intersection observer */}
      {hasMore && (
        <div ref={sentinelRef} className="h-px" aria-hidden="true" />
      )}

      {/* Loading indicator */}
      {isLoading && (
        <div className="flex items-center justify-center py-4">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          <span className="sr-only">{t("labels.loading_more")}</span>
        </div>
      )}
    </div>
  )
}
