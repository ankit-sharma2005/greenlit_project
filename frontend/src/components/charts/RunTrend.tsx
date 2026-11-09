import { ChartFrame } from "./ChartFrame";
import { VERDICT_WORD, trendPoints, type TrendRun } from "../../lib/chartData";

export interface RunTrendProps {
  runs: TrendRun[];
  /** The same thresholds the run pages use, for the two guide lines. */
  thresholds: { review: number; go: number };
}

const WIDTH = 340;
const HEIGHT = 150;
const LEFT = 30;
const RIGHT = WIDTH - 8;
const TOP = 10;
const BOTTOM = HEIGHT - 24;

function y(score: number): number {
  return Math.round((BOTTOM - (BOTTOM - TOP) * Math.min(1, Math.max(0, score))) * 100) / 100;
}

function x(index: number, count: number): number {
  if (count <= 1) return (LEFT + RIGHT) / 2;
  return Math.round((LEFT + ((RIGHT - LEFT) * index) / (count - 1)) * 100) / 100;
}

/**
 * Scores of finished runs, oldest first, as a plain line with each point marked by the
 * verdict's own shape (circle, diamond, triangle) and named in the table — a reader who
 * cannot tell the colours apart can still tell the verdicts apart.
 */
export function RunTrend({ runs, thresholds }: RunTrendProps) {
  const points = trendPoints(runs);

  if (points.length < 2) {
    return (
      <section className="chart" data-testid="run-trend" aria-labelledby="run-trend-empty">
        {/* The heading is the empty state's label; keep the testid on the message only. */}
        <div className="chart__head">
          <h3 className="chart__title" id="run-trend-empty">
            Score over time
          </h3>
          <p className="chart__empty" data-testid="run-trend-empty">
            Two finished runs are needed to draw a trend. Finish another run and come back.
          </p>
        </div>
      </section>
    );
  }

  const path = points.map((point, index) => `${x(index, points.length)},${y(point.score)}`).join(" ");

  const ariaLabel =
    `Scores of ${points.length} finished runs, oldest first: ` +
    points.map((point) => `${point.score.toFixed(2)} ${VERDICT_WORD[point.verdict]}`).join(", ") +
    `.`;

  const rows: string[][] = points.map((point) => [
    point.name,
    new Date(point.at).toLocaleString(),
    point.score.toFixed(2),
    VERDICT_WORD[point.verdict],
  ]);

  return (
    <ChartFrame
      title="Score over time"
      description="Every finished run's weighted score, oldest first. The dashed lines are the REVIEW and GO thresholds this run family uses."
      ariaLabel={ariaLabel}
      testId="run-trend"
      columns={["Run", "Finished", "Score", "Verdict"]}
      rows={rows}
    >
      <svg
        className="chart-svg"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={ariaLabel}
        data-testid="run-trend-svg"
      >
        <title>{ariaLabel}</title>
        <line className="grid-line" x1={LEFT} y1={y(0)} x2={RIGHT} y2={y(0)} />
        <line className="grid-line" x1={LEFT} y1={y(1)} x2={RIGHT} y2={y(1)} />
        <text className="chart-svg__muted" x={2} y={y(0) + 3}>
          0
        </text>
        <text className="chart-svg__muted" x={2} y={y(1) + 3}>
          1
        </text>
        <line className="marker-line" x1={LEFT} y1={y(thresholds.review)} x2={RIGHT} y2={y(thresholds.review)} />
        <line className="marker-line" x1={LEFT} y1={y(thresholds.go)} x2={RIGHT} y2={y(thresholds.go)} />
        <text className="chart-svg__muted" x={RIGHT - 2} y={y(thresholds.go) - 3} textAnchor="end">
          GO {thresholds.go.toFixed(2)}
        </text>
        <text className="chart-svg__muted" x={RIGHT - 2} y={y(thresholds.review) - 3} textAnchor="end">
          REVIEW {thresholds.review.toFixed(2)}
        </text>
        <polyline className="trend-line" points={path} />
        {points.map((point, index) => {
          const cx = x(index, points.length);
          const cy = y(point.score);
          const shapeClass = `shape--${point.verdict.toLowerCase().replace("_", "-")}`;
          return (
            <g key={point.id} data-testid={`run-trend-point-${index}`}>
              {point.verdict === "GO" ? (
                <circle className={shapeClass} cx={cx} cy={cy} r={4} />
              ) : point.verdict === "REVIEW" ? (
                <polygon className={shapeClass} points={`${cx},${cy - 5} ${cx + 5},${cy} ${cx},${cy + 5} ${cx - 5},${cy}`} />
              ) : (
                <polygon className={shapeClass} points={`${cx},${cy - 5} ${cx + 5},${cy + 4} ${cx - 5},${cy + 4}`} />
              )}
            </g>
          );
        })}
      </svg>
    </ChartFrame>
  );
}
