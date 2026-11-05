import { Bar, BarChart, CartesianGrid, LabelList, XAxis, YAxis } from "recharts"

import type { GradeCount } from "@/api/reports"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"

// One series, so one hue and no legend: the heading names what is plotted.
const config = {
  count: { label: "Members", color: "var(--chart-4)" },
} satisfies ChartConfig

const ROW_HEIGHT = 32

/**
 * Horizontal bars, one per Grade from Mukyū down, so the long Grade names
 * read on the axis. The visually hidden table carries every value without
 * hover, for screen readers.
 */
const GradeDistributionChart = ({ grades }: { grades: GradeCount[] }) => (
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
)

export default GradeDistributionChart
