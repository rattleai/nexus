import { ExternalLink } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card"
import { cn } from "@/lib/utils"

export interface Citation {
  id: string
  title: string
  source: string
  url?: string
  snippet?: string
  relevanceScore?: number
}

export interface SourceCitationProps {
  citation: Citation
  index: number
  className?: string
}

export function SourceCitation({ citation, index, className }: SourceCitationProps) {
  return (
    <HoverCard>
      <HoverCardTrigger asChild>
        <button
          className={cn(
            "inline-flex h-4 w-4 items-center justify-center rounded-full bg-primary/10 text-[10px] font-medium text-primary hover:bg-primary/20",
            className,
          )}
          aria-label={`Source ${index + 1}: ${citation.title}`}
        >
          {index + 1}
        </button>
      </HoverCardTrigger>
      <HoverCardContent className="w-80 text-sm" side="top">
        <div className="space-y-2">
          <div className="flex items-start justify-between gap-2">
            <h4 className="font-medium leading-tight">{citation.title}</h4>
            {citation.relevanceScore != null && (
              <Badge variant="outline" className="shrink-0 text-xs">
                {Math.round(citation.relevanceScore * 100)}%
              </Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground">{citation.source}</p>
          {citation.snippet && (
            <p className="text-xs leading-relaxed text-muted-foreground line-clamp-3">
              {citation.snippet}
            </p>
          )}
          {citation.url && (
            <a
              href={citation.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
            >
              Open source <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
      </HoverCardContent>
    </HoverCard>
  )
}

export interface SourceCitationListProps {
  citations: Citation[]
  className?: string
}

export function SourceCitationList({ citations, className }: SourceCitationListProps) {
  if (!citations.length) return null

  return (
    <div className={cn("space-y-2 border-t pt-3", className)}>
      <h4 className="text-xs font-medium text-muted-foreground">Sources</h4>
      <ol className="space-y-1.5">
        {citations.map((citation, i) => (
          <li key={citation.id} className="flex items-start gap-2 text-xs">
            <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-muted text-[10px] font-medium">
              {i + 1}
            </span>
            <div className="min-w-0">
              <span className="font-medium">{citation.title}</span>
              <span className="mx-1 text-muted-foreground">·</span>
              <span className="text-muted-foreground">{citation.source}</span>
              {citation.url && (
                <a
                  href={citation.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="ml-1 inline-flex items-center text-primary hover:underline"
                >
                  <ExternalLink className="h-3 w-3" />
                </a>
              )}
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}
