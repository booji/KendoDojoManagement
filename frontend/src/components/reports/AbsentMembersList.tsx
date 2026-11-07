import { useCallback } from "react"
import { Link } from "react-router-dom"

import type { MembershipStatus } from "@/api/members"
import { fetchAbsentMembers } from "@/api/reports"
import { EmptyState } from "@/components/ui/empty-state"
import { Section } from "@/components/ui/section"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useReport } from "@/hooks/useReport"
import { formatMemberDate } from "@/lib/date"

/**
 * Absent Members (GLOSSARY.md) for a wellbeing check (#564): a list, not a
 * chart, as of today. No phone column: the only phone stored is the
 * emergency contact's, which is not for this.
 */
const AbsentMembersList = ({ statuses }: { statuses: MembershipStatus[] }) => {
  const { data: members, error } = useReport(
    useCallback(() => fetchAbsentMembers(statuses), [statuses]),
    "Failed to load Absent Members",
  )

  return (
    <Section heading="Absent Members">
      <p className="text-sm text-muted-foreground">
        Members with no Attendance in the last 14 days, as of today.
      </p>
      {error !== null ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : members === null ? (
        <Skeleton className="h-32 w-full rounded-lg" />
      ) : members.length === 0 ? (
        <EmptyState message="No Absent Members." />
      ) : (
        <Table aria-label="Absent Members">
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Last attended</TableHead>
              <TableHead className="text-right">Days absent</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {members.map((m) => (
              <TableRow key={m.member_id}>
                <TableCell className="font-medium">
                  <Link
                    to={`/members/${m.member_id}`}
                    className="text-primary underline-offset-4 hover:underline"
                  >
                    {m.display_name}
                  </Link>
                </TableCell>
                <TableCell>{m.email}</TableCell>
                <TableCell>
                  {m.last_attended ? formatMemberDate(m.last_attended) : "Never"}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {m.days_absent}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Section>
  )
}

export default AbsentMembersList
