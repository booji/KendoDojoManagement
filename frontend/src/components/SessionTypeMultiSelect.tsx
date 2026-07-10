/**
 * SessionTypeMultiSelect — compact multi-select control for session types.
 *
 * Deep module: callers pass options/selectedIds/onChange and get a
 * self-contained trigger + popover. No cmdk/Command dependency — built only
 * on the existing Popover + Badge primitives.
 *
 * The trigger has a STABLE accessible name ("Session types") regardless of
 * selection state, so it can be reliably queried in tests and by assistive
 * tech. Selected types render as colour-dot badges inside the trigger.
 */

import { useState } from "react"
import { Check } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import type { SessionType } from "@/api/sessions"
import { cn } from "@/lib/utils"

// ── Types ──────────────────────────────────────────────────────────────────────

interface SessionTypeMultiSelectProps {
  options: SessionType[]
  selectedIds: string[]
  onChange: (ids: string[]) => void
  requireOne?: boolean
}

const FILTER_THRESHOLD = 10

// ── Colour dot ────────────────────────────────────────────────────────────────

const ColourDot = ({ colour }: { colour: string | null }) => (
  <span
    data-testid="colour-dot"
    className="inline-block size-2.5 shrink-0 rounded-full bg-muted-foreground/40"
    style={colour ? { backgroundColor: colour } : undefined}
  />
)

// ── SessionTypeMultiSelect ───────────────────────────────────────────────────

const SessionTypeMultiSelect = ({
  options,
  selectedIds,
  onChange,
  requireOne = false,
}: SessionTypeMultiSelectProps) => {
  const [filter, setFilter] = useState("")

  const selectedOptions = options.filter((o) => selectedIds.includes(o.id))
  const showFilter = options.length > FILTER_THRESHOLD
  const visibleOptions = showFilter
    ? options.filter((o) =>
        o.name.toLowerCase().includes(filter.trim().toLowerCase()),
      )
    : options

  const toggle = (id: string) => {
    const isSelected = selectedIds.includes(id)
    if (isSelected) {
      if (requireOne && selectedIds.length === 1) return
      onChange(selectedIds.filter((sid) => sid !== id))
    } else {
      onChange([...selectedIds, id])
    }
  }

  return (
    <Popover>
      <PopoverTrigger
        render={
          <button
            type="button"
            aria-label="Session types"
            className="flex min-h-[44px] w-full flex-wrap items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 py-1.5 text-left text-sm hover:bg-muted"
          />
        }
      >
        {selectedOptions.length === 0 ? (
          <span className="text-muted-foreground">
            Select session types…
          </span>
        ) : (
          selectedOptions.map((t) => (
            <Badge key={t.id} variant="outline" className="gap-1.5">
              <ColourDot colour={t.colour} />
              {t.name}
            </Badge>
          ))
        )}
      </PopoverTrigger>
      <PopoverContent className="w-72 p-2">
        {showFilter && (
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter session types…"
            className="mb-2 w-full min-h-[44px] rounded-md border border-border bg-background px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
          />
        )}
        <div className="max-h-64 space-y-1 overflow-y-auto">
          {visibleOptions.map((t) => {
            const isChecked = selectedIds.includes(t.id)
            const isDisabled =
              requireOne && isChecked && selectedIds.length === 1
            return (
              <div
                key={t.id}
                role="checkbox"
                aria-checked={isChecked}
                aria-disabled={isDisabled || undefined}
                aria-label={t.name}
                tabIndex={isDisabled ? -1 : 0}
                onClick={() => {
                  if (isDisabled) return
                  toggle(t.id)
                }}
                onKeyDown={(e) => {
                  if (isDisabled) return
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault()
                    toggle(t.id)
                  }
                }}
                className={cn(
                  "flex min-h-[44px] cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted",
                  isDisabled && "cursor-not-allowed opacity-50",
                )}
              >
                <ColourDot colour={t.colour} />
                <span className="flex-1">{t.name}</span>
                {isChecked && <Check className="size-4 shrink-0" />}
              </div>
            )
          })}
        </div>
      </PopoverContent>
    </Popover>
  )
}

export default SessionTypeMultiSelect
