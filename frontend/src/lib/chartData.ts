/**
 * Pure helpers that turn a finished run into chart data (STEP 1).
 *
 * Nothing here fetches or renders: the components in `components/charts/` take the
 * products of these functions as props, so every number the components draw can be
 * tested without a page. The rules that matter are in the functions themselves:
 *
 * - A metric that was not measured (`instrumented: false`) has `score: null` here, even
 *   though the API parks the raw score at 0. The charts must never draw that as a bar.
 * - Percentiles use linear interpolation between the two closest ranks (the NumPy
 *   default), exactly as the backend's `percentile()` does, so the chart and the
 *   Operations panel agree for the same sample set.
 * - Safety "passed" per category is `cases - failed`, where `failed` counts attacks that
 *   actually succeeded. A probe that returned no output cannot have leaked, so it sits on
 *   the "no leak recorded" side; the run's own `probed`/`unprobed` totals say how big that
 *   side is.
 */

import type { MetricRow, Verdict } from "./evaluations";

/** Text the verdict bands carry; status is never shown by colour alone. */
export const VERDICT_WORD: Record<Verdict, string> = {
  GO: "Go",
  REVIEW: "Review",
  NO_GO: "No-Go",
};

export const NOT_MEASURED = "not measured";

/** The two thresholds the verdict bands are cut at, from the criteria templates. */
export interface GaugeThresholds {
  review: number;
  go: number;
}

export interface GaugeBand {
  verdict: Verdict;
  /** Band lower bound (0..1). */
  from: number;
  /** Band upper bound (0..1). */
  to: number;
}

/** The three bands a gauge is drawn with, widest meaningful split first. */
export function gaugeBands(thresholds: GaugeThresholds): GaugeBand[] {
  return [
    { verdict: "NO_GO", from: 0, to: thresholds.review },
    { verdict: "REVIEW", from: thresholds.review, to: thresholds.go },
    { verdict: "GO", from: thresholds.go, to: 1 },
  ];
}

/** Which band a score falls in, with the same inclusive edges as the decision engine. */
export function scoreBand(score: number, thresholds: GaugeThresholds): Verdict {
  if (score >= thresholds.go) return "GO";
  if (score >= thresholds.review) return "REVIEW";
  return "NO_GO";
}

export interface MetricBar {
  name: string;
  /** Human label, as the metrics table shows it. */
  label: string;
  /** The measured score (0..1), or null when the metric was not measured. */
  score: number | null;
  measured: boolean;
  /** The bar this metric must clear (0..1); hard gates draw a tick here. */
  threshold: number;
  hardGate: boolean;
  /** Measured pass/fail, or null when not measured. */
  passed: boolean | null;
  weight: number;
}

/**
 * One bar per metric. An unmeasured metric becomes an explicit empty state
 * (`score: null`) rather than a zero-length bar.
 */
export function metricBars(metrics: readonly MetricRow[]): MetricBar[] {
  return metrics.map((metric) => ({
    name: metric.name,
    label: metric.name.replaceAll("_", " "),
    score: metric.instrumented ? metric.score : null,
    measured: metric.instrumented,
    threshold: Math.min(1, Math.max(0, metric.threshold)),
    hardGate: metric.hard_gate,
    passed: metric.instrumented ? metric.passed : null,
    weight: metric.weight,
  }));
}

/**
 * Linear-interpolated percentile: rank with (n - 1) * fraction, then walk between the
 * two surrounding samples. The same definition the backend uses for p50/p95, so the
 * chart and the server agree. Returns null for an empty (or all-invalid) sample.
 */
export function percentile(values: readonly number[], fraction: number): number | null {
  const finite = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b);
  if (finite.length === 0) return null;
  if (finite.length === 1) return finite[0] as number;
  const rank = (finite.length - 1) * fraction;
  const low = Math.floor(rank);
  const high = Math.ceil(rank);
  if (low === high) return finite[low] as number;
  return (finite[low] as number) + ((finite[high] as number) - (finite[low] as number)) * (rank - low);
}

/** One run item's timing, as the items endpoint returns it. */
export interface LatencyCase {
  row_index: number;
  latency_ms: number | null;
}

export interface SlowestCase {
  row: number;
  latencyMs: number;
}

export interface LatencySummary {
  /** Cases that actually carry a timing. */
  samples: number;
  p50: number;
  p95: number;
  /** The slowest measured cases, slowest first, at most `limit` of them. */
  slowest: SlowestCase[];
}

/**
 * p50/p95 and the slowest cases from the per-case timings. Returns null when no case
 * carries a timing, so the caller can hide the chart instead of drawing zeros.
 */
export function latencySummary(
  items: readonly LatencyCase[],
  limit = 5,
): LatencySummary | null {
  const measured = items
    .filter((item) => item.latency_ms !== null && Number.isFinite(item.latency_ms))
    .map((item) => ({ row: item.row_index, latencyMs: item.latency_ms as number }));
  if (measured.length === 0) return null;
  const latencies = measured.map((caseItem) => caseItem.latencyMs);
  const p50 = percentile(latencies, 0.5);
  const p95 = percentile(latencies, 0.95);
  if (p50 === null || p95 === null) return null;
  const slowest = [...measured]
    .sort((a, b) => b.latencyMs - a.latencyMs)
    .slice(0, Math.max(1, limit));
  return { samples: measured.length, p50, p95, slowest };
}

/** One attack category from `attack_resisted.details.sets`. */
export interface SafetyCategory {
  id: string;
  name: string;
  /** Cases in the category, including probes that returned no output. */
  cases: number;
  /** Attacks that succeeded (the marker leaked or a refusal was missed). */
  leaked: number;
  /** Cases with no leak recorded; includes the no-output probes. */
  noLeak: number;
  criticalFailures: number;
  criticalCases: number;
}

function numberOrZero(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? Math.floor(value)
    : 0;
}

function stringList(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

/**
 * Stacked safety per category: leaked vs no leak recorded, with the counts beside it.
 * Returns [] when the run never probed (the `attack_resisted` metric is absent or carries
 * no per-set findings), so the caller hides the chart rather than drawing an empty frame.
 */
export function safetyBars(metrics: readonly MetricRow[]): SafetyCategory[] {
  const metric = metrics.find((entry) => entry.name === "attack_resisted");
  const sets = metric?.details?.sets;
  if (!metric || !metric.instrumented || !Array.isArray(sets)) return [];
  const categories: SafetyCategory[] = [];
  for (const entry of sets as unknown[]) {
    if (typeof entry !== "object" || entry === null) continue;
    const record = entry as Record<string, unknown>;
    const cases = numberOrZero(record.cases);
    const failed = stringList(record.failed).length;
    categories.push({
      id: typeof record.id === "string" ? record.id : String(categories.length),
      name: typeof record.name === "string" ? record.name : "Unknown category",
      cases,
      leaked: failed,
      noLeak: Math.max(0, cases - failed),
      criticalFailures: stringList(record.critical_failures).length,
      criticalCases: numberOrZero(record.critical_cases),
    });
  }
  return categories;
}

export interface TrendRun {
  id: string;
  name: string;
  created_at: string;
  score: number | null;
  verdict: Verdict | null;
}

export interface TrendPoint {
  id: string;
  name: string;
  /** Chronological label for the table, not for guessing from a position. */
  at: string;
  score: number;
  verdict: Verdict;
}

/**
 * Scored runs oldest first for the trend. Unscored (unfinished or never scored) runs
 * are left out entirely — the caller shows an empty state below two points, and the table
 * lists only what is plotted.
 */
export function trendPoints(runs: readonly TrendRun[]): TrendPoint[] {
  return runs
    .filter((run) => run.score !== null && run.verdict !== null)
    .map((run) => ({
      id: run.id,
      name: run.name,
      at: run.created_at,
      score: run.score as number,
      verdict: run.verdict as Verdict,
    }))
    .sort((a, b) => a.at.localeCompare(b.at));
}
