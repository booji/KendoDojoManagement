import type { ReactNode } from "react"

import { Button } from "@/components/ui/button"

interface EmptyStateProps {
  message: string
  icon?: ReactNode | null
  actionLabel?: string | null
  onAction?: (() => void) | null
}

const EmptyState = ({
  message,
  icon,
  actionLabel,
  onAction,
}: EmptyStateProps) => {
  return (
    <div
      data-slot="empty-state"
      className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border px-6 py-12 text-center"
    >
      {icon ? (
        <div
          data-testid="empty-state-icon"
          className="text-muted-foreground [&>svg]:size-8"
        >
          {icon}
        </div>
      ) : null}
      <p className="text-sm text-muted-foreground">{message}</p>
      {actionLabel && onAction ? (
        <Button size="lg" onClick={onAction}>
          {actionLabel}
        </Button>
      ) : null}
    </div>
  )
}

export { EmptyState }
export type { EmptyStateProps }
