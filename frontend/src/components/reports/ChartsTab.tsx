import { useEffect, useState } from "react"
import { format, subDays } from "date-fns"

import { isApiError } from "@/api/auth"
import { MEMBERSHIP_STATUSES, type MembershipStatus } from "@/api/members"
import {
  fetchGradeDistribution,
  fetchHeadcount,
  type GradeCount,
  type SessionHeadcount,
} from "@/api/reports"
import GradeDistributionChart from "@/components/reports/GradeDistributionChart"
import HeadcountChart from "@/components/reports/HeadcountChart"
import { Checkbox } from "@/components/ui/checkbox"
import { EmptyState } from "@/components/ui/empty-state"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Section } from "@/components/ui/section"
import { Skeleton } from "@/components/ui/skeleton"

const ymd = (d: Date) => format(d, "yyyy-MM-dd")

/**
 * The Charts tab on /reports (#558). One Membership Status filter scopes every
 * member-centric chart below it, and one From/To range every chart over a
 * period; the server validates both.
 */
const ChartsTab = () => {
  const [statuses, setStatuses] = useState<MembershipStatus[]>(["active"])
  const [dateFrom, setDateFrom] = useState(() => ymd(subDays(new Date(), 90)))
  const [dateTo, setDateTo] = useState(() => ymd(new Date()))
  const [headcount, setHeadcount] = useState<SessionHeadcount[] | null>(null)
  const [headcountError, setHeadcountError] = useState<string | null>(null)
  const [grades, setGrades] = useState<GradeCount[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (statuses.length === 0) return
    let stale = false
    fetchGradeDistribution(statuses)
      .then((data) => {
        if (stale) return
        setGrades(data)
        setError(null)
      })
      .catch((err: unknown) => {
        if (stale) return
        setError(isApiError(err) ? err.message : "Failed to load grade distribution")
      })
    return () => {
      stale = true
    }
  }, [statuses])

  useEffect(() => {
    // An emptied date input: wait for a whole date rather than ask for none.
    if (dateFrom === "" || dateTo === "") return
    let stale = false
    fetchHeadcount(dateFrom, dateTo)
      .then((data) => {
        if (stale) return
        setHeadcount(data)
        setHeadcountError(null)
      })
      .catch((err: unknown) => {
        if (stale) return
        setHeadcountError(isApiError(err) ? err.message : "Failed to load headcount")
      })
    return () => {
      stale = true
    }
  }, [dateFrom, dateTo])

  const toggle = (value: MembershipStatus, checked: boolean) =>
    setStatuses(
      MEMBERSHIP_STATUSES.map((s) => s.value).filter((v) =>
        v === value ? checked : statuses.includes(v),
      ),
    )

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-4">
        <div className="flex gap-3">
          <div className="space-y-1">
            <Label htmlFor="charts-date-from">From</Label>
            <Input
              id="charts-date-from"
              type="date"
              value={dateFrom}
              max={dateTo}
              onChange={(e) => setDateFrom(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="charts-date-to">To</Label>
            <Input
              id="charts-date-to"
              type="date"
              value={dateTo}
              min={dateFrom}
              onChange={(e) => setDateTo(e.target.value)}
            />
          </div>
        </div>
        <fieldset className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <legend className="mb-2 text-sm font-medium">Membership Status</legend>
          {MEMBERSHIP_STATUSES.map(({ value, label }) => (
            <div key={value} className="flex items-center gap-2">
              <Checkbox
                id={`charts-status-${value}`}
                checked={statuses.includes(value)}
                onCheckedChange={(checked) => toggle(value, checked)}
              />
              <Label htmlFor={`charts-status-${value}`}>{label}</Label>
            </div>
          ))}
        </fieldset>
      </div>

      <Section heading="Headcount per Session">
        <p className="text-sm text-muted-foreground">
          Members and Visitors at each held Session in the range. Every Member
          counts, whatever their Membership Status today.
        </p>
        {headcountError !== null ? (
          <p className="text-sm text-destructive" role="alert">
            {headcountError}
          </p>
        ) : headcount === null ? (
          <Skeleton className="h-72 w-full rounded-lg" />
        ) : headcount.length === 0 ? (
          <EmptyState message="No held Sessions in this range." />
        ) : (
          <HeadcountChart sessions={headcount} />
        )}
      </Section>

      <Section heading="Grade distribution">
        <p className="text-sm text-muted-foreground">
          Members by current Grade, as of today.
        </p>
        {statuses.length === 0 ? (
          <EmptyState message="Choose at least one Membership Status." />
        ) : error !== null ? (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        ) : grades === null ? (
          <Skeleton className="h-64 w-full rounded-lg" />
        ) : grades.length === 0 ? (
          <EmptyState message="No Members with these Membership Statuses." />
        ) : (
          <GradeDistributionChart grades={grades} />
        )}
      </Section>
    </div>
  )
}

export default ChartsTab
