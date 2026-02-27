import { cn } from "@/lib/utils"

function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("animate-pulse rounded-btn bg-muted", className)}
      {...props}
    />
  )
}

export { Skeleton }
