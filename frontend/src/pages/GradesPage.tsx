import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  type PendingGradeEntry,
  listPendingGrades,
  approveGrade,
  rejectGrade,
} from "@/api/grades"

const formatDate = (value: string | null): string => {
  if (!value) return "Not provided"
  const d = new Date(value)
  if (isNaN(d.getTime())) return "Not provided"
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })
}

const TableSkeleton = () => (
  <div className="space-y-2" aria-busy="true" aria-label="Loading pending submissions">
    {Array.from({ length: 3 }).map((_, i) => (
      <Skeleton key={i} className="h-10 w-full" />
    ))}
  </div>
)

const GradesPage = () => {
  const [entries, setEntries] = useState<PendingGradeEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionErrors, setActionErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<Record<string, boolean>>({})

  useEffect(() => {
    listPendingGrades()
      .then((data) => {
        setEntries(data)
        setError(null)
      })
      .catch((err: unknown) => {
        const msg =
          err !== null &&
          typeof err === "object" &&
          "message" in err &&
          typeof (err as { message: unknown }).message === "string"
            ? (err as { message: string }).message
            : "Failed to load pending submissions"
        setError(msg)
      })
      .finally(() => setLoading(false))
  }, [])

  const removeEntry = (id: string) =>
    setEntries((prev) => prev.filter((e) => e.id !== id))

  const clearActionError = (id: string) =>
    setActionErrors((prev) => {
      const next = { ...prev }
      delete next[id]
      return next
    })

  const handleApprove = (entry: PendingGradeEntry) => {
    setBusy((prev) => ({ ...prev, [entry.id]: true }))
    clearActionError(entry.id)
    approveGrade(entry.member_id, entry.id)
      .then(() => removeEntry(entry.id))
      .catch((err: unknown) => {
        const msg =
          err !== null &&
          typeof err === "object" &&
          "message" in err &&
          typeof (err as { message: unknown }).message === "string"
            ? (err as { message: string }).message
            : "Failed to approve"
        setActionErrors((prev) => ({ ...prev, [entry.id]: msg }))
      })
      .finally(() => setBusy((prev) => ({ ...prev, [entry.id]: false })))
  }

  const handleReject = (entry: PendingGradeEntry) => {
    setBusy((prev) => ({ ...prev, [entry.id]: true }))
    clearActionError(entry.id)
    rejectGrade(entry.member_id, entry.id)
      .then(() => removeEntry(entry.id))
      .catch((err: unknown) => {
        const msg =
          err !== null &&
          typeof err === "object" &&
          "message" in err &&
          typeof (err as { message: unknown }).message === "string"
            ? (err as { message: string }).message
            : "Failed to reject"
        setActionErrors((prev) => ({ ...prev, [entry.id]: msg }))
      })
      .finally(() => setBusy((prev) => ({ ...prev, [entry.id]: false })))
  }

  return (
    <div className="px-4 py-6 space-y-6">
      <h1 className="text-xl font-semibold">Grade management</h1>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Pending submissions</CardTitle>
        </CardHeader>
        <CardContent>
          {loading && <TableSkeleton />}

          {!loading && error !== null && (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          )}

          {!loading && error === null && entries.length === 0 && (
            <p className="text-sm text-muted-foreground">No pending submissions</p>
          )}

          {!loading && error === null && entries.length > 0 && (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Member</TableHead>
                    <TableHead>Proposed grade</TableHead>
                    <TableHead>Proposed date</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {entries.map((entry) => (
                    <TableRow key={entry.id}>
                      <TableCell className="font-medium">{entry.member_name}</TableCell>
                      <TableCell>{entry.display_name}</TableCell>
                      <TableCell>{formatDate(entry.promoted_at)}</TableCell>
                      <TableCell>
                        <div className="flex flex-col items-end gap-1">
                          <div className="flex items-center justify-end gap-2">
                            <Button
                              variant="destructive"
                              size="sm"
                              disabled={busy[entry.id] === true}
                              onClick={() => handleReject(entry)}
                              aria-label={`Reject grade submission for ${entry.member_name}`}
                            >
                              Reject
                            </Button>
                            <Button
                              size="sm"
                              disabled={busy[entry.id] === true}
                              onClick={() => handleApprove(entry)}
                              aria-label={`Approve grade submission for ${entry.member_name}`}
                            >
                              Approve
                            </Button>
                          </div>
                          {actionErrors[entry.id] !== undefined && (
                            <p className="text-xs text-destructive" role="alert">
                              {actionErrors[entry.id]}
                            </p>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

export default GradesPage
