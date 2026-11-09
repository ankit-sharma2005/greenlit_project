import { ChartFrame } from "./ChartFrame";
import type { LatencySummary } from "../../lib/chartData";

export interface LatencyChartProps {
  summary: LatencySummary;
  /** Optional cap the criteria use, so the reader can compare against it. */
  limitMs?: number | null;
}

const WIDTH = 340;
const LABEL_WIDTH = 46;
const PLOT_LEFT = LABEL_WIDTH;
const PLOT_RIGHT = WIDTH - 40;
const ROW = 24;
const TOP = 8;

function barWidth(latency: number, max: number): number {
  if (max <= 0) return 0;
  return Math.round(((PLOT_RIGHT - PLOT_LEFT) * (latency / max)) * 100) / 100;
}

/**
 * The slowest measured cases, with p50 and p95 written above them. Only cases that
 * reported a timing are drawn; the description states the percentile method and the
 * sample count, because a percentile of three cases is not a percentile of three hundred.
 */
export function LatencyChart({ summary, limitMs = null }: LatencyChartProps) {
  const max = Math.max(summary.p95, ...summary.slowest.map((item) => item.latencyMs));

  const ariaLabel =
    `Latency of ${summary.samples} measured case${summary.samples === 1 ? "" : "s"}: ` +
    `p50 ${Math.round(summary.p50)} ms, p95 ${Math.round(summary.p95)} ms. ` +
    `Slowest: ${summary.slowest
      .map((item) => `case ${item.row + 1} ${Math.round(item.latencyMs)} ms`)
      .join(", ")}.`;

  const rows: string[][] = [
    ["p50", `${Math.round(summary.p50)} ms`],
    ["p95", `${Math.round(summary.p95)} ms`],
    ...summary.slowest.map((item) => [`Case ${item.row + 1}`, `${Math.round(item.latencyMs)} ms`]),
  ];

  return (
    <ChartFrame
      title="Latency"
      description={`The slowest of the ${summary.samples} case${summary.samples === 1 ? "" : "s"} that reported a latency. p50 and p95 use linear interpolation between the two closest ranks, the method GreenLit's server reports. A case that never answered is not drawn.`}
      ariaLabel={ariaLabel}
      testId="latency-chart"
      columns={["Measure", "Latency"]}
      rows={rows}
    >
      <svg
        className="chart-svg"
        viewBox={`0 0 ${WIDTH} ${TOP + 30 + summary.slowest.length * ROW}`}
        role="img"
        aria-label={ariaLabel}
        data-testid="latency-chart-svg"
      >
        <title>{ariaLabel}</title>
        <text className="chart-svg__text" x={4} y={14}>
          p50 {Math.round(summary.p50)} ms · p95 {Math.round(summary.p95)} ms
        </text>
        {limitMs !== null && limitMs > 0 ? (
          <text className="chart-svg__muted" x={4} y={TOP + 24}>
            limit {Math.round(limitMs)} ms
          </text>
        ) : null}
        {summary.slowest.map((item, index) => {
          const top = TOP + 30 + index * ROW;
          return (
            <g key={item.row}>
              <text className="chart-svg__muted" x={4} y={top + 11}>
                #{item.row + 1}
              </text>
              <rect
                className="fill-measure"
                x={PLOT_LEFT}
                y={top + 2}
                width={Math.max(barWidth(item.latencyMs, max), 0.5)}
                height={12}
                data-testid={`latency-bar-${item.row}`}
              />
              <text className="chart-svg__muted" x={PLOT_LEFT + barWidth(item.latencyMs, max) + 4} y={top + 11}>
                {Math.round(item.latencyMs)} ms
              </text>
            </g>
          );
        })}
      </svg>
    </ChartFrame>
  );
}
