import { ChartFrame } from "./ChartFrame";
import {
  VERDICT_WORD,
  gaugeBands,
  type GaugeThresholds,
} from "../../lib/chartData";
import type { Verdict } from "../../lib/evaluations";

export interface VerdictGaugeProps {
  /** Weighted score, 0..1. */
  score: number;
  verdict: Verdict;
  thresholds: GaugeThresholds;
}

const WIDTH = 340;
const BAR_LEFT = 8;
const BAR_WIDTH = WIDTH - 2 * BAR_LEFT;
const BAR_TOP = 34;
const BAR_HEIGHT = 18;

function x(value: number): number {
  return Math.round((BAR_LEFT + value * BAR_WIDTH) * 100) / 100;
}

/**
 * The score on a bar with the NO-GO / REVIEW / GO bands and the two threshold marks.
 * Bands are tinted with the verdict tokens, so they never ask colour to do the work alone:
 * the verdict word stands beside the bar and the band words sit under it.
 */
export function VerdictGauge({ score, verdict, thresholds }: VerdictGaugeProps) {
  const bands = gaugeBands(thresholds);
  const word = VERDICT_WORD[verdict];

  const ariaLabel =
    `Weighted score ${score.toFixed(2)}, verdict ${word}. ` +
    `NO-GO below ${thresholds.review.toFixed(2)}, REVIEW from ${thresholds.review.toFixed(2)} ` +
    `to ${thresholds.go.toFixed(2)}, GO at or above ${thresholds.go.toFixed(2)}.`;

  const rows: string[][] = bands.map((band) => [
    band.verdict === "NO_GO" ? "No-Go" : band.verdict === "REVIEW" ? "Review" : "Go",
    `${band.from.toFixed(2)} to ${band.to.toFixed(2)}`,
  ]);
  rows.push(["This run", score.toFixed(2), word]);

  return (
    <ChartFrame
      title="Score"
      description="The run's weighted score on the same 0 to 1 scale the verdict was decided on, with the REVIEW and GO thresholds marked."
      ariaLabel={ariaLabel}
      testId="verdict-gauge"
      columns={["Band", "Score range"]}
      rows={rows}
    >
      <svg
        className="chart-svg"
        viewBox={`0 0 ${WIDTH} 76`}
        role="img"
        aria-label={ariaLabel}
        data-testid="verdict-gauge-svg"
      >
        <title>{ariaLabel}</title>
        <text className="chart-svg__word" x={BAR_LEFT} y={20}>
          {word} · {score.toFixed(2)}
        </text>
        {bands.map((band) => (
          <rect
            key={band.verdict}
            className={`band--${band.verdict.toLowerCase().replace("_", "-")}`}
            x={x(band.from)}
            y={BAR_TOP}
            width={Math.max(band.to - band.from, 0.001) * BAR_WIDTH}
            height={BAR_HEIGHT}
            data-testid={`verdict-gauge-band-${band.verdict}`}
          />
        ))}
        <polygon
          className="stroke-line"
          fill="var(--color-text)"
          points={`${x(score) - 5},${BAR_TOP - 8} ${x(score) + 5},${BAR_TOP - 8} ${x(score)},${BAR_TOP}`}
          data-testid="verdict-gauge-marker"
        />
        {[thresholds.review, thresholds.go].map((threshold) => (
          <g key={threshold}>
            <line
              className="gate-tick"
              x1={x(threshold)}
              x2={x(threshold)}
              y1={BAR_TOP - 4}
              y2={BAR_TOP + BAR_HEIGHT + 14}
            />
            <text className="chart-svg__muted" x={x(threshold)} y={BAR_TOP + BAR_HEIGHT + 26} textAnchor="middle">
              {threshold.toFixed(2)}
            </text>
          </g>
        ))}
        {bands.map((band) => (
          <text
            key={`label-${band.verdict}`}
            className="chart-svg__muted"
            x={x((band.from + band.to) / 2)}
            y={BAR_TOP + BAR_HEIGHT / 2 + 3}
            textAnchor="middle"
          >
            {band.verdict === "NO_GO" ? "NO-GO" : band.verdict}
          </text>
        ))}
      </svg>
    </ChartFrame>
  );
}
