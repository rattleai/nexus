import * as React from "react"
import {
  ShieldAlert,
  CheckCircle,
  XCircle,
  Clock,
  Loader2,
  ChevronDown,
  ChevronRight,
  Wrench,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { useResolveApproval } from "@/hooks/use-agents"
import { cn } from "@/lib/utils"

interface ApprovalItem {
  approval_id: string
  instance_id: string
  tool_name: string
  arguments: Record<string, unknown>
  created_at: string
  timeout_seconds: number
}

interface ApprovalsBannerProps {
  approvals: Array<Record<string, unknown>>
}

export function ApprovalsBanner({ approvals }: ApprovalsBannerProps) {
  const [isOpen, setIsOpen] = React.useState(true)

  if (approvals.length === 0) return null

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <Card className="border-amber-500/30 bg-amber-500/5">
        <CollapsibleTrigger asChild>
          <button className="flex w-full items-center gap-3 px-4 py-3 text-left">
            <ShieldAlert className="h-5 w-5 text-amber-600 dark:text-amber-400 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-amber-800 dark:text-amber-300">
                Agent Actions Awaiting Approval
              </p>
              <p className="text-xs text-amber-700/80 dark:text-amber-400/70">
                {approvals.length} action{approvals.length !== 1 ? "s" : ""} need your review
                before agents can proceed
              </p>
            </div>
            <Badge
              variant="outline"
              className="bg-amber-500/20 text-amber-700 dark:text-amber-300 border-amber-500/30 shrink-0"
            >
              {approvals.length}
            </Badge>
            {isOpen ? (
              <ChevronDown className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0" />
            ) : (
              <ChevronRight className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0" />
            )}
          </button>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <div className="border-t border-amber-500/20 px-4 py-3 space-y-2">
            {approvals.map((approval) => (
              <ApprovalCard
                key={(approval as ApprovalItem).approval_id}
                approval={approval as ApprovalItem}
              />
            ))}
          </div>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  )
}

function ApprovalCard({ approval }: { approval: ApprovalItem }) {
  const [showArgs, setShowArgs] = React.useState(false)
  const resolveApproval = useResolveApproval()
  const [resolved, setResolved] = React.useState<"approved" | "denied" | null>(null)

  const handleResolve = (decision: "approved" | "denied") => {
    resolveApproval.mutate(
      { approvalId: approval.approval_id, decision },
      {
        onSuccess: () => setResolved(decision),
      },
    )
  }

  const timeLeft = React.useMemo(() => {
    const created = new Date(approval.created_at).getTime()
    const expiresAt = created + approval.timeout_seconds * 1000
    const remaining = Math.max(0, Math.floor((expiresAt - Date.now()) / 1000))
    if (remaining === 0) return "Expired"
    if (remaining < 60) return `${remaining}s left`
    return `${Math.floor(remaining / 60)}m left`
  }, [approval])

  if (resolved) {
    return (
      <div className="flex items-center gap-3 rounded-md border bg-background px-3 py-2">
        {resolved === "approved" ? (
          <CheckCircle className="h-4 w-4 text-emerald-500 shrink-0" />
        ) : (
          <XCircle className="h-4 w-4 text-red-500 shrink-0" />
        )}
        <span className="text-sm">
          <span className="font-medium">{approval.tool_name}</span>{" "}
          <span className="text-muted-foreground capitalize">{resolved}</span>
        </span>
      </div>
    )
  }

  return (
    <div className="rounded-md border bg-background overflow-hidden">
      <div className="flex flex-col gap-2 px-3 py-2 sm:flex-row sm:items-center sm:gap-3">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <Wrench className="h-4 w-4 text-muted-foreground shrink-0" />
          <span className="text-sm font-medium truncate">{approval.tool_name}</span>
          <span className="text-xs text-muted-foreground font-mono hidden sm:inline">
            {approval.instance_id.slice(0, 8)}
          </span>
          <span className="text-xs text-muted-foreground flex items-center gap-1 ml-auto sm:ml-0">
            <Clock className="h-3 w-3" />
            {timeLeft}
          </span>
        </div>
        <div className="flex items-center gap-2 w-full sm:w-auto sm:shrink-0">
          <Button
            variant="ghost"
            size="sm"
            className="h-10 text-xs flex-1 sm:flex-none sm:h-7"
            onClick={() => setShowArgs(!showArgs)}
          >
            {showArgs ? "Hide" : "Args"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-10 text-xs border-red-500/30 text-red-600 hover:bg-red-500/10 flex-1 sm:flex-none sm:h-7"
            onClick={() => handleResolve("denied")}
            disabled={resolveApproval.isPending}
          >
            <XCircle className="mr-1 h-3 w-3" />
            Deny
          </Button>
          <Button
            size="sm"
            className="h-10 text-xs bg-emerald-600 hover:bg-emerald-700 text-white flex-1 sm:flex-none sm:h-7"
            onClick={() => handleResolve("approved")}
            disabled={resolveApproval.isPending}
          >
            {resolveApproval.isPending ? (
              <Loader2 className="mr-1 h-3 w-3 animate-spin" />
            ) : (
              <CheckCircle className="mr-1 h-3 w-3" />
            )}
            Approve
          </Button>
        </div>
      </div>
      {showArgs && (
        <div className="border-t px-3 py-2 bg-muted/50">
          <pre className="text-xs overflow-x-auto max-w-full">
            {JSON.stringify(approval.arguments, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}
