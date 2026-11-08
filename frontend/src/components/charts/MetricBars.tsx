import { ChartFrame } from "./ChartFrame";
import { type MetricBar } from "../../lib/chartData";

export interface MetricBarsProps {
  bars: MetricBar[];
}

const WIDTH = 340;
const LABEL_WIDTH = 118;
const BAR_LEFT = LABEL_WIDTH;
const BAR_WIDTH = 150;
const VALUE_LEFT = BAR_LEFT + BAR_WIDTH + 8;
const ROW = 30;
const TOP = 6;

function x(value: number): number {
  return Math.round((BAR_LEFT + Math.min(1, Math.max(0, value)) * BAR_WIDTH) * 100) / 100;
}

/**
 * One horizontal bar per metric on a shared 0..1 scale. Measured metrics get a solid
 * bar with the score written beside it and, for hard gates, a tick at the bar the metric
 * must clear. A metric the run never measured gets a dashed empty slot labelled
 * "not measured" — never a zero-length bar — and is skipped by nothing else.
 */
export function MetricBars({ bars }: MetricBarsProps) {
  const ariaParts = bars.map((bar) =>
    bar.measured
      ? `${bar.label} ${bar.score?.toFixed(2)}${bar.hardGate ? ", hard gate" : ""}`
      : `${bar.label} not measured`,
  );
  const ariaLabel = `Metric scores.${ariaParts.length > 0 ? ` ${ariaParts.join(", ")}.` : ""}`;

  const rows: string[][] = bars.map((bar) => [
    bar.label,
    bar.measured ? (bar.score as number).toFixed(2) : "not measured",
    bar.weight.toFixed(2),
    bar.hardGate ? `gate at ${bar.threshold.toFixed(2)}` : "-",
    bar.measured ? (bar.passed ? "pass" : "fail") : "-",
  ]);

  return (
    <ChartFrame
      title="Metrics"
      description="Each metric's score on a 0 to 1 scale with its weight; a dashed slot means the run never measured that metric, not that it scored zero."
      ariaLabel={ariaLabel}
      testId="metric-bars"
      columns={["Metric", "Score", "Weight", "Gate", "State"]}
      rows={rows}
    >
      <svg
        className="chart-svg"
        viewBox={`0 0 ${WIDTH} ${TOP + bars.length * ROW}`}
        role="img"
        aria-label={ariaLabel}
        data-testid="metric-bars-svg"
      >
        <title>{ariaLabel}</title>
        {bars.map((bar, index) => {
          const top = TOP + index * ROW;
          return (
            <g key={bar.name}>
              <text className="chart-svg__text" x={4} y={top + ROW / 2 + 4}>
                {bar.label}
              </text>
              {bar.measured ? (
                <>
                  <rect
                    className="track"
                    x={BAR_LEFT}
                    y={top + 4}
                    width={BAR_WIDTH}
                    height={12}
                    data-testid={`metric-track-${bar.name}`}
                  />
                  <rect
                    className="fill-measure"
                    x={BAR_LEFT}
                    y={top + 4}
                    width={Math.max((bar.score as number) * BAR_WIDTH, 0.5)}
                    height={12}
                    data-testid={`metric-bar-${bar.name}`}
                  />
                  <text className="chart-svg__text" x={VALUE_LEFT} y={top + ROW / 2 + 4}>
                    {(bar.score as number).toFixed(2)} {bar.passed ? "pass" : "fail"}
                  </text>
                  {bar.hardGate ? (
                    <line
                      className="gate-tick"
                      x1={x(bar.threshold)}
                      x2={x(bar.threshold)}
                      y1={top + 2}
                      y2={top + ROW - 2}
                      data-testid={`metric-gate-${bar.name}`}
                    />
                  ) : null}
                </>
              ) : (
                <>
                  <rect
                    className="slot-draft"
                    x={BAR_LEFT}
                    y={top + 4}
                    width={BAR_WIDTH}
                    height={12}
                    data-testid={`metric-unmeasured-${bar.name}`}
                  />
                  <text className="chart-svg__muted" x={VALUE_LEFT} y={top + ROW / 2 + 4}>
                    not measured
                  </text>
                </>
              )}
            </g>
          );
        })}
      </svg>
    </ChartFrame>
  );
}
