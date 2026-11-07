import { useEffect, useState } from "react"
import { Bar, BarChart, CartesianGrid, LabelList, XAxis, YAxis } from "recharts"

import { isApiError } from "@/api/auth"
import type { MembershipStatus } from "@/api/members"
import { fetchTopAttendanceRates, type MemberAttendanceRate } from "@/api/reports"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { EmptyState } from "@/components/ui/empty-state"
import { Section } from "@/components/ui/section"
import { Skeleton } from "@/components/ui/skeleton"

// One series, so one hue and no legend: the heading names what is plotted.
const config = {
  percent: { label: "Attendance Rate", color: "var(--chart-3)" },
} satisfies ChartConfig

const ROW_HEIGHT = 32

const percent = (r: MemberAttendanceRate) => Math.round(r.attendance_rate * 100)

/**
 * The 10 highest Attendance Rates (GLOSSARY.md) over the tab's From/To range,
 * for the Charts tab (#562). The server leaves out Members with fewer than 4
 * eligible held Sessions.
 */
const AttendanceRatesChart = ({
  dateFrom,
  dateTo,
  statuses,
}: {
  dateFrom: string
  dateTo: string
  statuses: MembershipStatus[]
}) => {
  const [rates, setRates] = useState<MemberAttendanceRate[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // An emptied date input: wait for a whole date rather than ask for none.
    if (dateFrom === "" || dateTo === "") return
    let stale = false
    fetchTopAttendanceRates(dateFrom, dateTo, statuses)
      .then((data) => {
        if (stale) return
        setRates(data)
        setError(null)
      })
      .catch((err: unknown) => {
        if (stale) return
        setError(isApiError(err) ? err.message : "Failed to load Attendance Rates")
      })
    return () => {
      stale = true
    }
  }, [dateFrom, dateTo, statuses])

  return (
    <Section heading="Attendance Rate">
      <p className="text-sm text-muted-foreground">
        Highest share of held Sessions attended in the range, among Members
        with 4 or more held Sessions since joining.
      </p>
      {error !== null ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : rates === null ? (
        <Skeleton className="h-64 w-full rounded-lg" />
      ) : rates.length === 0 ? (
        <EmptyState message="No Member had 4 or more held Sessions in this range." />
      ) : (
        <>
          <ChartContainer
            config={config}
            className="aspect-auto w-full"
            style={{ height: rates.length * ROW_HEIGHT + 40 }}
            aria-hidden="true"
          >
            <BarChart
              data={rates.map((r) => ({ ...r, percent: percent(r), label: `${percent(r)}%` }))}
              layout="vertical"
              margin={{ left: 0, right: 48 }}
            >
              <CartesianGrid horizontal={false} />
              <XAxis
                type="number"
                domain={[0, 100]}
                tickFormatter={(v: number) => `${v}%`}
                tickLine={false}
                axisLine={false}
              />
              <YAxis
                type="category"
                dataKey="display_name"
                width={140}
                tickLine={false}
                axisLine={false}
              />
              <ChartTooltip
                cursor={false}
                content={<ChartTooltipContent indicator="line" />}
              />
              <Bar
                dataKey="percent"
                fill="var(--color-percent)"
                radius={[0, 4, 4, 0]}
                maxBarSize={24}
              >
                <LabelList
                  dataKey="label"
                  position="right"
                  className="fill-muted-foreground"
                  fontSize={12}
                />
              </Bar>
            </BarChart>
          </ChartContainer>
          <table className="sr-only" aria-label="Attendance Rate">
            <thead>
              <tr>
                <th scope="col">Member</th>
                <th scope="col">Attendance Rate</th>
                <th scope="col">Sessions attended</th>
              </tr>
            </thead>
            <tbody>
              {rates.map((r) => (
                <tr key={r.member_id}>
                  <th scope="row">{r.display_name}</th>
                  <td>{percent(r)}%</td>
                  <td>
                    {r.sessions_attended} of {r.total_sessions}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </Section>
  )
}

export default AttendanceRatesChart
