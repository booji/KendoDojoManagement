import { useCallback } from "react"
import { Bar, BarChart, CartesianGrid, LabelList, XAxis, YAxis } from "recharts"

import type { MembershipStatus } from "@/api/members"
import { fetchGradeDistribution } from "@/api/reports"
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
  count: { label: "Members", color: "var(--chart-4)" },
} satisfies ChartConfig

const ROW_HEIGHT = 32

/**
 * Members by current Grade, as of today, for the Charts tab (#560).
 * Horizontal bars, one per Grade from Mukyū down, so the long Grade names
 * read on the axis. The visually hidden table carries every value without
 * hover, for screen readers.
 */
const GradeDistributionChart = ({ statuses }: { statuses: MembershipStatus[] }) => {
  const { data: grades, error } = useReport(
    useCallback(() => fetchGradeDistribution(statuses), [statuses]),
    "Failed to load grade distribution",
  )

  return (
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
        <>
          <ChartContainer
            config={config}
            className="aspect-auto w-full"
            style={{ height: grades.length * ROW_HEIGHT + 40 }}
            aria-hidden="true"
          >
            <BarChart
              data={grades}
              layout="vertical"
              margin={{ left: 0, right: 32 }}
            >
              <CartesianGrid horizontal={false} />
              <XAxis type="number" allowDecimals={false} tickLine={false} axisLine={false} />
              <YAxis
                type="category"
                dataKey="display_name"
                width={112}
                tickLine={false}
                axisLine={false}
              />
              <ChartTooltip
                cursor={false}
                content={<ChartTooltipContent indicator="line" />}
              />
              <Bar
                dataKey="count"
                fill="var(--color-count)"
                radius={[0, 4, 4, 0]}
                maxBarSize={24}
              >
                <LabelList
                  dataKey="count"
                  position="right"
                  className="fill-muted-foreground"
                  fontSize={12}
                />
              </Bar>
            </BarChart>
          </ChartContainer>
          <table className="sr-only" aria-label="Grade distribution">
            <thead>
              <tr>
                <th scope="col">Grade</th>
                <th scope="col">Members</th>
              </tr>
            </thead>
            <tbody>
              {grades.map((g) => (
                <tr key={g.grade}>
                  <th scope="row">{g.display_name}</th>
                  <td>{g.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </Section>
  )
}

export default GradeDistributionChart
