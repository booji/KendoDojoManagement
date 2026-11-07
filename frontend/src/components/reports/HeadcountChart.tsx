import { useCallback } from "react"
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts"

import { fetchHeadcount } from "@/api/reports"
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { EmptyState } from "@/components/ui/empty-state"
import { Section } from "@/components/ui/section"
import { Skeleton } from "@/components/ui/skeleton"
import { useReport } from "@/hooks/useReport"
import { formatSessionDate, formatShortDate } from "@/lib/date"

// Members keep the hue the grade distribution gives them; Visitors take the
// first categorical slot, which stays apart from it under colour blindness.
const config = {
  members: { label: "Members", color: "var(--chart-4)" },
  visitors: { label: "Visitors", color: "var(--chart-1)" },
} satisfies ChartConfig

/**
 * Headcount per held Session over the tab's From/To range: one stacked bar per
 * Session, oldest on the left. The visually hidden table carries every value
 * without hover, for screen readers.
 */
const HeadcountChart = ({ dateFrom, dateTo }: { dateFrom: string; dateTo: string }) => {
  const { data: sessions, error } = useReport(
    useCallback(
      // An emptied date input: wait for a whole date rather than ask for none.
      () => (dateFrom === "" || dateTo === "" ? null : fetchHeadcount(dateFrom, dateTo)),
      [dateFrom, dateTo],
    ),
    "Failed to load headcount",
  )

  return (
    <Section heading="Headcount per Session">
      <p className="text-sm text-muted-foreground">
        Members and Visitors at each held Session in the range. Every Member
        counts, whatever their Membership Status today.
      </p>
      {error !== null ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : sessions === null ? (
        <Skeleton className="h-72 w-full rounded-lg" />
      ) : sessions.length === 0 ? (
        <EmptyState message="No held Sessions in this range." />
      ) : (
        <>
          <ChartContainer config={config} className="aspect-auto h-72 w-full" aria-hidden="true">
            <BarChart data={sessions} margin={{ left: 0, right: 8 }}>
              <CartesianGrid vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={formatShortDate}
                tickLine={false}
                axisLine={false}
                minTickGap={16}
              />
              <YAxis allowDecimals={false} width={32} tickLine={false} axisLine={false} />
              <ChartTooltip
                cursor={false}
                content={
                  <ChartTooltipContent
                    labelFormatter={(date) => formatSessionDate(String(date))}
                  />
                }
              />
              <ChartLegend content={<ChartLegendContent />} />
              <Bar
                dataKey="members"
                stackId="headcount"
                fill="var(--color-members)"
                stroke="var(--background)"
                strokeWidth={2}
                maxBarSize={24}
              />
              <Bar
                dataKey="visitors"
                stackId="headcount"
                fill="var(--color-visitors)"
                stroke="var(--background)"
                strokeWidth={2}
                radius={[4, 4, 0, 0]}
                maxBarSize={24}
              />
            </BarChart>
          </ChartContainer>
          <table className="sr-only" aria-label="Headcount per Session">
            <thead>
              <tr>
                <th scope="col">Session</th>
                <th scope="col">Members</th>
                <th scope="col">Visitors</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr key={s.session_id}>
                  <th scope="row">{formatSessionDate(s.date)}</th>
                  <td>{s.members}</td>
                  <td>{s.visitors}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </Section>
  )
}

export default HeadcountChart
