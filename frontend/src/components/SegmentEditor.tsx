/**
 * SegmentEditor — semi-controlled multi-segment editor.
 *
 * Props:
 *   segments     — initial value (seeds internal state on mount)
 *   sessionTypes — available types to pick from (checkboxes)
 *   onChange     — called with the full updated segments array on every change
 *
 * The component owns two parallel internal state arrays:
 *   segs          — the canonical SegmentInput[] (always has valid numeric values)
 *   durationStrs  — string draft for each duration field (lets the user clear
 *                   and retype without React fighting the controlled value back
 *                   to the previous number)
 *
 * Layout: stacked cards (no <table>), mobile-first, 44px min touch targets.
 */

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { SegmentInput, SessionType } from "@/api/sessions"

// ── Types ──────────────────────────────────────────────────────────────────────

interface SegmentEditorProps {
  segments: SegmentInput[]
  sessionTypes: SessionType[]
  onChange: (segments: SegmentInput[]) => void
}

// ── Default for a newly added segment ────────────────────────────────────────

const DEFAULT_DURATION = 60
const DEFAULT_START_TIME = "19:00"

const newBlankSegment = (): SegmentInput => ({
  start_time: DEFAULT_START_TIME,
  duration_minutes: DEFAULT_DURATION,
  coach_notes: null,
  type_ids: [],
})

// ── SegmentEditor ─────────────────────────────────────────────────────────────

const SegmentEditor = ({
  segments: initialSegments,
  sessionTypes,
  onChange,
}: SegmentEditorProps) => {
  // Canonical segment data — source of truth for type_ids, start_time, coach_notes,
  // and the numeric duration_minutes.
  const [segs, setSegs] = useState<SegmentInput[]>(() =>
    initialSegments.map((s) => ({ ...s, type_ids: [...s.type_ids] })),
  )

  // String representation of each segment's duration.
  // Kept separate so the user can clear the field (momentarily NaN) without
  // React resetting the DOM value back to the previous number on each re-render.
  const [durationStrs, setDurationStrs] = useState<string[]>(() =>
    initialSegments.map((s) => String(s.duration_minutes)),
  )

  // ── Helpers ──────────────────────────────────────────────────────────────────

  const applyPatch = (idx: number, patch: Partial<SegmentInput>) => {
    const next = segs.map((s, i) => (i === idx ? { ...s, ...patch } : s))
    setSegs(next)
    onChange(next)
  }

  const handleDurationChange = (idx: number, raw: string) => {
    // Always update the string draft so the field can be emptied mid-edit.
    setDurationStrs((prev) => prev.map((d, i) => (i === idx ? raw : d)))
    const parsed = parseInt(raw, 10)
    // Only update the canonical segs when we have a valid positive number.
    if (!isNaN(parsed) && parsed > 0) {
      applyPatch(idx, { duration_minutes: parsed })
    }
  }

  const handleAdd = () => {
    const blank = newBlankSegment()
    const next = [...segs, blank]
    setSegs(next)
    setDurationStrs((prev) => [...prev, String(DEFAULT_DURATION)])
    onChange(next)
  }

  const handleRemove = (idx: number) => {
    if (segs.length <= 1) return
    const next = segs.filter((_, i) => i !== idx)
    setSegs(next)
    setDurationStrs((prev) => prev.filter((_, i) => i !== idx))
    onChange(next)
  }

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-3">
      {segs.map((seg, idx) => (
        <div
          key={idx}
          className="rounded-lg border bg-card p-3 space-y-3"
          aria-label={`Segment ${idx + 1}`}
        >
          {/* Segment header — only visible when multiple rows */}
          {segs.length > 1 && (
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Segment {idx + 1}
            </p>
          )}

          {/* Start time */}
          <div className="space-y-1.5">
            <Label htmlFor={`seg-${idx}-start`}>Start time</Label>
            <Input
              id={`seg-${idx}-start`}
              type="text"
              placeholder="HH:MM"
              value={seg.start_time}
              onChange={(e) => applyPatch(idx, { start_time: e.target.value })}
              className="min-h-[44px]"
            />
          </div>

          {/* Duration — uses string draft to allow clearing mid-edit */}
          <div className="space-y-1.5">
            <Label htmlFor={`seg-${idx}-duration`}>Duration (minutes)</Label>
            <Input
              id={`seg-${idx}-duration`}
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              value={durationStrs[idx] ?? String(seg.duration_minutes)}
              onChange={(e) => handleDurationChange(idx, e.target.value)}
              className="min-h-[44px]"
            />
          </div>

          {/* Session types — visible checkbox list */}
          {sessionTypes.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-sm font-medium leading-none">Session types</p>
              <div className="flex flex-wrap gap-3 pt-1">
                {sessionTypes.map((t) => {
                  const isChecked = seg.type_ids.includes(t.id)
                  // Prevent deselecting the last remaining type.
                  const isLastSelected = isChecked && seg.type_ids.length === 1
                  return (
                    <div key={t.id} className="flex items-center gap-1.5 min-h-[44px]">
                      <Checkbox
                        id={`seg-${idx}-type-${t.id}`}
                        checked={isChecked}
                        disabled={isLastSelected}
                        onCheckedChange={(checked) => {
                          if (checked === true) {
                            applyPatch(idx, {
                              type_ids: [...seg.type_ids, t.id],
                            })
                          } else if (!isLastSelected) {
                            applyPatch(idx, {
                              type_ids: seg.type_ids.filter((id) => id !== t.id),
                            })
                          }
                        }}
                      />
                      <Label htmlFor={`seg-${idx}-type-${t.id}`}>{t.name}</Label>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Coach notes */}
          <div className="space-y-1.5">
            <Label htmlFor={`seg-${idx}-notes`}>Coach notes</Label>
            <Input
              id={`seg-${idx}-notes`}
              value={seg.coach_notes ?? ""}
              onChange={(e) =>
                applyPatch(idx, { coach_notes: e.target.value || null })
              }
              placeholder="Optional notes for coaches"
              className="min-h-[44px]"
            />
          </div>

          {/* Remove — only present when there are multiple segments */}
          {segs.length > 1 && (
            <div className="flex justify-end">
              <Button
                type="button"
                variant="outline"
                size="sm"
                aria-label="Remove segment"
                onClick={() => handleRemove(idx)}
                className="min-h-[44px] text-destructive border-destructive hover:bg-destructive hover:text-destructive-foreground"
              >
                Remove segment
              </Button>
            </div>
          )}
        </div>
      ))}

      {/* Add segment */}
      <Button
        type="button"
        variant="outline"
        onClick={handleAdd}
        className="w-full min-h-[44px]"
      >
        Add segment
      </Button>
    </div>
  )
}

export default SegmentEditor
