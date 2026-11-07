import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { getMyMember } from "@/api/accounts"
import { isApiError } from "@/api/auth"
import AttendanceHistoryCard from "@/components/AttendanceHistoryCard"
import { PageHeader } from "@/components/ui/page-header"
import { Skeleton } from "@/components/ui/skeleton"

/** My Attendance: the signed-in Member's own Attendance history (#572). */
const AttendancePage = () => {
  // undefined while loading; null when the Account has no Member.
  const [memberId, setMemberId] = useState<string | null | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getMyMember()
      .then((member) => setMemberId(member?.id ?? null))
      .catch((err: unknown) => {
        setError(isApiError(err) ? err.message : "Failed to load your attendance")
      })
  }, [])

  return (
    <div className="px-4 py-6 space-y-6">
      <PageHeader title="My Attendance" />
      <p className="text-sm text-muted-foreground">
        Check in to a session on the{" "}
        <Link to="/sessions" className="underline underline-offset-4 hover:text-foreground">
          Sessions page
        </Link>
        .
      </p>
      {error !== null ? (
        <p className="text-sm text-destructive" role="alert">{error}</p>
      ) : memberId ? (
        <AttendanceHistoryCard memberId={memberId} />
      ) : (
        <Skeleton className="h-24 w-full" />
      )}
    </div>
  )
}

export default AttendancePage
