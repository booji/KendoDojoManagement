import { useCallback } from "react"
import { Bar, BarChart, CartesianGrid, LabelList, XAxis, YAxis } from "recharts"

import type { MembershipStatus } from "@/api/members"
import { fetchAttendanceStreaks, type AttendanceStreak } from "@/api/reports"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { EmptyState } from "@/components/ui/empty-state"
import { Section } from "@/components/ui/section"
import { Skeleton } from "@/components/ui/skeleton"
import { useReport } from "@/hooks/useReport"

// One series, so one hue and no legend: the heading names what is plotted.
const config = {
  weeks: { label: "Weeks", color: "var(--chart-2)" },
} satisfies ChartConfig

const ROW_HEIGHT = 32

// An unbroken Attendance Streak is marked in the bar's label, so it never rests on colour.
const label = (s: AttendanceStreak) => (s.running ? `${s.weeks} · unbroken` : `${s.weeks}`)

/**
 * The 10 longest Attendance Streaks (GLOSSARY.md) this year, for the Charts
 * tab (#563). Always 1 January to today: it ignores the tab's date range.
 */
const AttendanceStreaksChart = ({ statuses }: { statuses: MembershipStatus[] }) => {
  const { data: streaks, error } = useReport(
    useCallback(() => fetchAttendanceStreaks(statuses), [statuses]),
    "Failed to load Attendance Streaks",
  )

  return (
    <Section heading="Attendance Streaks">
      <p className="text-sm text-muted-foreground">
        Longest Attendance Streaks of consecutive weeks attended, 1 January to today.
      </p>
      {error !== null ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : streaks === null ? (
        <Skeleton className="h-64 w-full rounded-lg" />
      ) : streaks.length === 0 ? (
        <EmptyState message="No Attendance Streaks this year." />
      ) : (
        <>
          <ChartContainer
            config={config}
            className="aspect-auto w-full"
            style={{ height: streaks.length * ROW_HEIGHT + 40 }}
            aria-hidden="true"
          >
            <BarChart
              data={streaks.map((s) => ({ ...s, label: label(s) }))}
              layout="vertical"
              margin={{ left: 0, right: 80 }}
            >
              <CartesianGrid horizontal={false} />
              <XAxis type="number" allowDecimals={false} tickLine={false} axisLine={false} />
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
                dataKey="weeks"
                fill="var(--color-weeks)"
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
          <table className="sr-only" aria-label="Attendance Streaks">
            <thead>
              <tr>
                <th scope="col">Member</th>
                <th scope="col">Weeks</th>
                <th scope="col">Unbroken</th>
              </tr>
            </thead>
            <tbody>
              {streaks.map((s) => (
                <tr key={s.member_id}>
                  <th scope="row">{s.display_name}</th>
                  <td>{s.weeks}</td>
                  <td>{s.running ? "Yes" : "No"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </Section>
  )
}

export default AttendanceStreaksChart
