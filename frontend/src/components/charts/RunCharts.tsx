import { useEffect, useState } from "react";

import { getRunItems, type Run } from "../../lib/runs";
import { latencySummary, metricBars, safetyBars, type LatencySummary } from "../../lib/chartData";
import { LatencyChart } from "./LatencyChart";
import { MetricBars } from "./MetricBars";
import { SafetyByCategory } from "./SafetyByCategory";
import { VerdictGauge } from "./VerdictGauge";
import { useCriteriaThresholds } from "./useCriteriaThresholds";

/**
 * The Charts block of a finished run. Each chart is drawn only when its data exists:
 * the gauge needs a score and a verdict, the bars need metrics, the safety chart needs
 * per-category findings, and the latency chart needs at least one case that reported a
 * timing (its items are fetched here, because they are not part of the run payload).
 */
export function RunCharts({ run }: { run: Run }) {
  const thresholds = useCriteriaThresholds(run.criteria_profile);
  const [latency, setLatency] = useState<LatencySummary | null>(null);

  useEffect(() => {
    let active = true;
    getRunItems(run.id)
      .then((response) => {
        if (active) setLatency(latencySummary(response.items));
      })
      .catch(() => {
        /* No timings were readable, so the latency chart stays hidden. */
        if (active) setLatency(null);
      });
    return () => {
      active = false;
    };
  }, [run.id]);

  const bars = metricBars(run.metrics);
  const safety = safetyBars(run.metrics);
  const latencyMetric = run.metrics.find((metric) => metric.name === "latency_under_limit");
  const limitMs = latencyMetric?.details?.limit_ms;
  const hasCharts =
    (run.score !== null && run.verdict !== null) || bars.length > 0 || safety.length > 0 || latency;
  if (!hasCharts) return null;

  return (
    <section
      className="card"
      aria-labelledby="run-charts-heading"
      data-testid="run-charts"
      style={{ marginTop: "var(--space-5)" }}
    >
      <div className="card__header">
        <h2 id="run-charts-heading">Charts</h2>
        <p className="card__hint">
          Drawn from this run&apos;s stored results only. A metric the run did not measure is
          shown as an empty slot labelled “not measured”, never as zero.
        </p>
      </div>

      {run.score !== null && run.verdict !== null ? (
        <VerdictGauge score={run.score} verdict={run.verdict} thresholds={thresholds} />
      ) : null}
      {bars.length > 0 ? <MetricBars bars={bars} /> : null}
      {safety.length > 0 ? <SafetyByCategory categories={safety} /> : null}
      {latency ? (
        <LatencyChart summary={latency} limitMs={typeof limitMs === "number" ? limitMs : null} />
      ) : null}
    </section>
  );
}
