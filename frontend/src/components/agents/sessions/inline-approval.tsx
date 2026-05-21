import * as React from "react"
import {
  ShieldAlert,
  CheckCircle,
  XCircle,
  Loader2,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { useResolveApproval } from "@/hooks/use-agents"

interface InlineApprovalProps {
  approval: Record<string, unknown>
}

export function InlineApproval({ approval }: InlineApprovalProps) {
  const resolveApproval = useResolveApproval()
  const [resolved, setResolved] = React.useState<string | null>(null)

  const handleResolve = (decision: "approved" | "denied") => {
    resolveApproval.mutate(
      { approvalId: approval.approval_id as string, decision },
      { onSuccess: () => setResolved(decision) },
    )
  }

  if (resolved) {
    return (
      <div className="flex items-center gap-2 rounded-lg border px-3 py-2 bg-muted/30">
        {resolved === "approved" ? (
          <CheckCircle className="h-4 w-4 text-emerald-500" />
        ) : (
          <XCircle className="h-4 w-4 text-red-500" />
        )}
        <span className="text-sm capitalize">{resolved}</span>
        <span className="text-xs text-muted-foreground">
          {approval.tool_name as string}
        </span>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 overflow-hidden">
      <div className="flex flex-col gap-2 px-3 py-2.5 sm:flex-row sm:items-center sm:gap-3">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <ShieldAlert className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0" />
          <p className="text-sm font-medium truncate">
            Approval: <code className="text-xs bg-muted px-1 rounded">{approval.tool_name as string}</code>
          </p>
        </div>
        <div className="flex items-center gap-2 w-full sm:w-auto sm:shrink-0">
          <Button
            variant="outline"
            size="sm"
            className="h-10 text-xs border-red-500/30 text-red-600 hover:bg-red-500/10 flex-1 sm:flex-none sm:h-7"
            onClick={() => handleResolve("denied")}
            disabled={resolveApproval.isPending}
          >
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
      {!!approval.arguments && Object.keys(approval.arguments as Record<string, unknown>).length > 0 && (
        <div className="border-t border-amber-500/20 px-3 py-2 bg-amber-500/[0.02]">
          <pre className="text-xs overflow-x-auto max-w-full max-h-24">
            {JSON.stringify(approval.arguments, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}
