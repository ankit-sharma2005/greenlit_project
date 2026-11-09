import { useId } from "react";

import { ChartFrame } from "./ChartFrame";
import type { SafetyCategory } from "../../lib/chartData";

export interface SafetyByCategoryProps {
  categories: SafetyCategory[];
}

const WIDTH = 340;
const LABEL_WIDTH = 132;
const BAR_LEFT = LABEL_WIDTH;
const BAR_WIDTH = 150;
const VALUE_LEFT = BAR_LEFT + BAR_WIDTH + 8;
const ROW = 30;
const TOP = 6;

/**
 * Stacked safety per attack category: attacks that leaked the marker (hatched) beside
 * attacks with no leak recorded. A probe that returned no output cannot have leaked, so
 * it counts with the no-leak side; the description says so rather than calling it
 * "passed". Returns null when the run was never probed, like the rest of the safety UI.
 */
export function SafetyByCategory({ categories }: SafetyByCategoryProps) {
  const patternId = useId().replace(/:/g, "");
  if (categories.length === 0) return null;

  const ariaLabel =
    "Safety per category. " +
    categories
      .map(
        (category) =>
          `${category.name}: ${category.cases} attacks, ${category.leaked} leaked, ` +
          `${category.criticalFailures} critical failure${
            category.criticalFailures === 1 ? "" : "s"
          }`,
      )
      .join(". ") +
    ".";

  const rows: string[][] = categories.map((category) => [
    category.name,
    String(category.cases),
    String(category.noLeak),
    String(category.leaked),
    category.criticalFailures > 0
      ? `${category.criticalFailures} critical failure${category.criticalFailures === 1 ? "" : "s"}`
      : "none",
  ]);

  return (
    <ChartFrame
      title="Safety by category"
      description="Attacks per category, split into leaks and attacks with no leak recorded. A probe that returned no output cannot have leaked, so it counts with the no-leak side; the run's probed and unprobed totals are in the safety section above."
      ariaLabel={ariaLabel}
      testId="safety-by-category"
      columns={["Category", "Attacks", "No leak recorded", "Leaked", "Critical failures"]}
      rows={rows}
    >
      <svg
        className="chart-svg"
        viewBox={`0 0 ${WIDTH} ${TOP + categories.length * ROW}`}
        role="img"
        aria-label={ariaLabel}
        data-testid="safety-by-category-svg"
      >
        <title>{ariaLabel}</title>
        <defs>
          <pattern id={patternId} width="6" height="6" patternUnits="userSpaceOnUse">
            <rect width="6" height="6" fill="var(--color-no-go)" />
            <line x1="0" y1="6" x2="6" y2="0" stroke="var(--color-on-danger)" strokeWidth="1.5" />
          </pattern>
        </defs>
        {categories.map((category, index) => {
          const top = TOP + index * ROW;
          const safeWidth =
            category.cases > 0 ? (category.noLeak / category.cases) * BAR_WIDTH : 0;
          const leakedWidth =
            category.cases > 0 ? (category.leaked / category.cases) * BAR_WIDTH : 0;
          return (
            <g key={category.id}>
              <text className="chart-svg__text" x={4} y={top + ROW / 2 + 4}>
                {category.name}
              </text>
              <rect
                className="fill-measure"
                x={BAR_LEFT}
                y={top + 4}
                width={safeWidth}
                height={12}
                data-testid={`safety-safebar-${category.id}`}
              />
              <rect
                x={BAR_LEFT + safeWidth}
                y={top + 4}
                width={leakedWidth}
                height={12}
                fill={`url(#${patternId})`}
                data-testid={`safety-leakedbar-${category.id}`}
              />
              <text className="chart-svg__text" x={VALUE_LEFT} y={top + ROW / 2 + 4}>
                {category.noLeak} no leak · {category.leaked} leaked
              </text>
            </g>
          );
        })}
        <g>
          <rect x={4} y={TOP + categories.length * ROW + 2} width="10" height="10" className="fill-measure" />
          <text className="chart-svg__muted" x={20} y={TOP + categories.length * ROW + 11}>
            no leak recorded
          </text>
          <rect
            x={150}
            y={TOP + categories.length * ROW + 2}
            width="10"
            height="10"
            fill={`url(#${patternId})`}
          />
          <text className="chart-svg__muted" x={166} y={TOP + categories.length * ROW + 11}>
            leaked
          </text>
        </g>
      </svg>
    </ChartFrame>
  );
}
