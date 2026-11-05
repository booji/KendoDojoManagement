import { useEffect, useState } from "react"

import { isApiError } from "@/api/auth"
import { MEMBERSHIP_STATUSES, type MembershipStatus } from "@/api/members"
import { fetchGradeDistribution, type GradeCount } from "@/api/reports"
import AbsentMembersList from "@/components/reports/AbsentMembersList"
import GradeDistributionChart from "@/components/reports/GradeDistributionChart"
import { Checkbox } from "@/components/ui/checkbox"
import { EmptyState } from "@/components/ui/empty-state"
import { Label } from "@/components/ui/label"
import { Section } from "@/components/ui/section"
import { Skeleton } from "@/components/ui/skeleton"

/**
 * The Charts tab on /reports (#558). One Membership Status filter scopes every
 * member-centric chart below it; the server validates each value.
 */
const ChartsTab = () => {
  const [statuses, setStatuses] = useState<MembershipStatus[]>(["active"])
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

  const toggle = (value: MembershipStatus, checked: boolean) =>
    setStatuses(
      MEMBERSHIP_STATUSES.map((s) => s.value).filter((v) =>
        v === value ? checked : statuses.includes(v),
      ),
    )

  return (
    <div className="space-y-6">
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

      {statuses.length === 0 ? (
        <EmptyState message="Choose at least one Membership Status." />
      ) : (
        <Section heading="Grade distribution">
          <p className="text-sm text-muted-foreground">
            Members by current Grade, as of today.
          </p>
          {error !== null ? (
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
      )}

      {statuses.length > 0 && <AbsentMembersList statuses={statuses} />}
    </div>
  )
}

export default ChartsTab
