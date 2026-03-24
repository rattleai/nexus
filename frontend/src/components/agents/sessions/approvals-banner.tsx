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
      <div className="flex items-center gap-3 px-3 py-2">
        <Wrench className="h-4 w-4 text-muted-foreground shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">{approval.tool_name}</span>
            <span className="text-xs text-muted-foreground font-mono">
              {approval.instance_id.slice(0, 8)}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-muted-foreground flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {timeLeft}
          </span>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs"
            onClick={() => setShowArgs(!showArgs)}
          >
            {showArgs ? "Hide" : "Args"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs border-red-500/30 text-red-600 hover:bg-red-500/10"
            onClick={() => handleResolve("denied")}
            disabled={resolveApproval.isPending}
          >
            <XCircle className="mr-1 h-3 w-3" />
            Deny
          </Button>
          <Button
            size="sm"
            className="h-7 text-xs bg-emerald-600 hover:bg-emerald-700 text-white"
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
          <pre className="text-xs overflow-x-auto">
            {JSON.stringify(approval.arguments, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}
