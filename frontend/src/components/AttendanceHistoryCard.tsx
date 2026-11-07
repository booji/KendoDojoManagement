import { useEffect, useState } from "react"
import { ChevronDownIcon, ChevronUpIcon } from "lucide-react"
import { getMemberAttendanceHistory } from "@/api/attendance"
import type { AttendanceRecord } from "@/api/attendance"
import { isApiError } from "@/api/auth"
import { formatMemberDate } from "@/lib/date"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

type AttendanceHistoryCardProps = {
  memberId: string
}

const AttendanceHistoryCard = ({ memberId }: AttendanceHistoryCardProps) => {
  const [records, setRecords] = useState<AttendanceRecord[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    getMemberAttendanceHistory(memberId)
      .then(setRecords)
      .catch((err: unknown) => {
        setError(isApiError(err) ? err.message : "Failed to load attendance history")
      })
  }, [memberId])

  return (
    <Card>
      <CardHeader>
        <CardTitle>Attendance History</CardTitle>
      </CardHeader>
      <CardContent>
        {error !== null ? (
          <p className="text-sm text-destructive" role="alert">{error}</p>
        ) : records === null ? (
          <div className="space-y-2">
            <Skeleton className="h-5 w-full" />
            <Skeleton className="h-5 w-3/4" />
          </div>
        ) : records.length === 0 ? (
          <p className="text-sm text-muted-foreground">No attendance records yet</p>
        ) : (
          <div>
            <button
              type="button"
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
              onClick={() => setOpen((o) => !o)}
              aria-expanded={open}
              aria-controls="attendance-history-list"
            >
              {open ? (
                <ChevronUpIcon className="h-3 w-3" aria-hidden="true" />
              ) : (
                <ChevronDownIcon className="h-3 w-3" aria-hidden="true" />
              )}
              {open ? "Hide" : "Show"} attendance ({records.length} sessions)
            </button>

            {open && (
              <ol
                id="attendance-history-list"
                className="mt-2 space-y-1 border-l-2 border-border pl-3"
              >
                {records.map((record) => (
                  <li key={record.id} className="text-sm">
                    <span className="font-mono text-xs">{record.session_id.slice(0, 8)}…</span>
                    <span className="text-muted-foreground ml-2 text-xs">
                      {formatMemberDate(record.checked_in_at)}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default AttendanceHistoryCard
