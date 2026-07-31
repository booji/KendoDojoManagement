import { useState } from "react"
import {
  fetchAttendanceReport,
  fetchMembersReport,
  downloadAttendanceCsv,
  downloadMembersCsv,
} from "@/api/reports"
import type { AttendanceReport, MemberReport } from "@/api/reports"
import { isApiError } from "@/api/auth"
import { formatSessionDate, formatMemberDate } from "@/lib/date"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { DownloadIcon } from "lucide-react"
import { PageHeader } from "@/components/ui/page-header"
import { EmptyState } from "@/components/ui/empty-state"

// ── Attendance tab ─────────────────────────────────────────────────────────────

const toYMD = (ms: number) => new Date(ms).toISOString().slice(0, 10)

const AttendanceSection = () => {
  const [dateFrom, setDateFrom] = useState(() =>
    toYMD(Date.now() - 30 * 24 * 60 * 60 * 1000)
  )
  const [dateTo, setDateTo] = useState(() => toYMD(Date.now()))
  const [report, setReport] = useState<AttendanceReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleGenerate = async () => {
    setError(null)
    setLoading(true)
    try {
      const data = await fetchAttendanceReport(dateFrom, dateTo)
      setReport(data)
    } catch (err) {
      setError(isApiError(err) ? err.message : "Failed to generate report")
    } finally {
      setLoading(false)
    }
  }

  const handleDownload = async () => {
    setDownloading(true)
    try {
      await downloadAttendanceCsv(dateFrom, dateTo)
    } catch (err) {
      setError(isApiError(err) ? err.message : "Failed to download CSV")
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* Date range controls */}
      <div className="flex flex-col sm:flex-row gap-3 items-end">
        <div className="space-y-1 flex-1">
          <Label htmlFor="date-from">From</Label>
          <Input
            id="date-from"
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            aria-label="Start date"
          />
        </div>
        <div className="space-y-1 flex-1">
          <Label htmlFor="date-to">To</Label>
          <Input
            id="date-to"
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            aria-label="End date"
          />
        </div>
        <Button
          size="lg"
          onClick={() => void handleGenerate()}
          disabled={loading}
          aria-label="Generate attendance report"
          className="w-full sm:w-auto"
        >
          {loading ? "Generating…" : "Generate"}
        </Button>
        <Button
          size="lg"
          variant="outline"
          onClick={() => void handleDownload()}
          disabled={report === null || downloading}
          aria-label="Download attendance CSV"
          className="w-full sm:w-auto"
        >
          <DownloadIcon aria-hidden="true" className="size-4" />
          <span>{downloading ? "Downloading…" : "Download CSV"}</span>
        </Button>
      </div>

      {error !== null && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}

      {loading && (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full rounded-lg" />
          ))}
        </div>
      )}

      {!loading && report !== null && (
        <div className="space-y-8">
          {/* Sessions table */}
          <div>
            <h2 className="text-base font-semibold mb-3">
              Sessions ({report.sessions.length})
            </h2>
            {report.sessions.length === 0 ? (
              <EmptyState message="No sessions in this date range." />
            ) : (
              <div className="rounded-xl ring-1 ring-foreground/10 overflow-x-auto">
                <table
                  className="w-full text-sm"
                  role="table"
                  aria-label="Sessions summary"
                >
                  <thead className="bg-muted/50">
                    <tr>
                      <th
                        className="py-2.5 pl-4 pr-2 text-left font-medium text-muted-foreground"
                        scope="col"
                      >
                        Date
                      </th>
                      <th
                        className="py-2.5 pl-2 pr-4 text-right font-medium text-muted-foreground"
                        scope="col"
                      >
                        Headcount
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.sessions.map((s) => (
                      <tr
                        key={s.session_id}
                        className="border-t border-foreground/5 hover:bg-muted/30"
                      >
                        <td className="py-2.5 pl-4 pr-2">
                          {formatSessionDate(s.scheduled_at)}
                        </td>
                        <td className="py-2.5 pl-2 pr-4 text-right tabular-nums">
                          {s.headcount}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Member attendance rates table */}
          <div>
            <h2 className="text-base font-semibold mb-3">
              Member attendance rates
            </h2>
            {report.member_rates.length === 0 ? (
              <EmptyState message="No member data." />
            ) : (
              <div className="rounded-xl ring-1 ring-foreground/10 overflow-x-auto">
                <table
                  className="w-full text-sm"
                  role="table"
                  aria-label="Member attendance rates"
                >
                  <thead className="bg-muted/50">
                    <tr>
                      <th
                        className="py-2.5 pl-4 pr-2 text-left font-medium text-muted-foreground"
                        scope="col"
                      >
                        Member
                      </th>
                      <th
                        className="py-2.5 px-2 text-right font-medium text-muted-foreground hidden sm:table-cell"
                        scope="col"
                      >
                        Sessions Attended
                      </th>
                      <th
                        className="py-2.5 pl-2 pr-4 text-right font-medium text-muted-foreground"
                        scope="col"
                      >
                        Rate
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.member_rates.map((m) => (
                      <tr
                        key={m.member_id}
                        className="border-t border-foreground/5 hover:bg-muted/30"
                      >
                        <td className="py-2.5 pl-4 pr-2 font-medium">
                          {m.display_name}
                        </td>
                        <td className="py-2.5 px-2 text-right tabular-nums hidden sm:table-cell">
                          {m.sessions_attended}
                        </td>
                        <td className="py-2.5 pl-2 pr-4 text-right tabular-nums">
                          {(m.attendance_rate * 100).toFixed(0)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Members tab ────────────────────────────────────────────────────────────────

const MembersSection = () => {
  const [report, setReport] = useState<MemberReport[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleGenerate = async () => {
    setError(null)
    setLoading(true)
    try {
      const data = await fetchMembersReport()
      setReport(data)
    } catch (err) {
      setError(isApiError(err) ? err.message : "Failed to generate report")
    } finally {
      setLoading(false)
    }
  }

  const handleDownload = async () => {
    setDownloading(true)
    try {
      await downloadMembersCsv()
    } catch (err) {
      setError(isApiError(err) ? err.message : "Failed to download CSV")
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* Controls */}
      <div className="flex flex-col sm:flex-row gap-3">
        <Button
          size="lg"
          onClick={() => void handleGenerate()}
          disabled={loading}
          aria-label="Generate members report"
        >
          {loading ? "Generating…" : "Generate"}
        </Button>
        <Button
          size="lg"
          variant="outline"
          onClick={() => void handleDownload()}
          disabled={report === null || downloading}
          aria-label="Download members CSV"
        >
          <DownloadIcon aria-hidden="true" className="size-4" />
          <span>{downloading ? "Downloading…" : "Download CSV"}</span>
        </Button>
      </div>

      {error !== null && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}

      {loading && (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full rounded-lg" />
          ))}
        </div>
      )}

      {!loading && report !== null && (
        <div>
          <h2 className="text-base font-semibold mb-3">
            Members ({report.length})
          </h2>
          {report.length === 0 ? (
            <EmptyState message="No members found." />
          ) : (
            <div className="rounded-xl ring-1 ring-foreground/10 overflow-x-auto">
              <table
                className="w-full text-sm"
                role="table"
                aria-label="Members report"
              >
                <thead className="bg-muted/50">
                  <tr>
                    <th
                      className="py-2.5 pl-4 pr-2 text-left font-medium text-muted-foreground"
                      scope="col"
                    >
                      Name
                    </th>
                    <th
                      className="py-2.5 px-2 text-left font-medium text-muted-foreground hidden sm:table-cell"
                      scope="col"
                    >
                      Current Grade
                    </th>
                    <th
                      className="py-2.5 pl-2 pr-4 text-right font-medium text-muted-foreground"
                      scope="col"
                    >
                      Join Date
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {report.map((m) => (
                    <tr
                      key={m.member_id}
                      className="border-t border-foreground/5 hover:bg-muted/30"
                    >
                      <td className="py-2.5 pl-4 pr-2 font-medium">
                        {m.display_name}
                      </td>
                      <td className="py-2.5 px-2 text-muted-foreground hidden sm:table-cell">
                        {m.current_grade ?? "—"}
                      </td>
                      <td className="py-2.5 pl-2 pr-4 text-right text-muted-foreground">
                        {formatMemberDate(m.join_date)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

const ReportsPage = () => (
  <div className="px-4 py-6">
    <div className="mb-6">
      <PageHeader title="Reports" />
    </div>

    <Tabs defaultValue="attendance">
      <TabsList className="mb-6">
        <TabsTrigger value="attendance">Attendance</TabsTrigger>
        <TabsTrigger value="members">Members</TabsTrigger>
      </TabsList>

      <TabsContent value="attendance">
        <AttendanceSection />
      </TabsContent>

      <TabsContent value="members">
        <MembersSection />
      </TabsContent>
    </Tabs>
  </div>
)

export default ReportsPage
