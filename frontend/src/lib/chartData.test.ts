import { describe, expect, it } from "vitest";

import {
  gaugeBands,
  latencySummary,
  metricBars,
  percentile,
  safetyBars,
  scoreBand,
  trendPoints,
  type TrendRun,
} from "./chartData";
import type { MetricRow } from "./evaluations";

function metric(overrides: Partial<MetricRow> = {}): MetricRow {
  return {
    name: "answer_match",
    score: 0.75,
    passed: true,
    explanation: "measured",
    instrumented: true,
    weight: 0.3,
    threshold: 0.6,
    hard_gate: false,
    details: {},
    ...overrides,
  };
}

// The thresholds every template ships with (backend DEFAULT_REVIEW_THRESHOLD 0.60 and
// DEFAULT_GO_THRESHOLD 0.80): the gauge draws its bands from them, never from its own
// copy of the numbers.
const THRESHOLDS = { review: 0.6, go: 0.8 };

describe("gauge bands", () => {
  it("cuts the scale at the thresholds the criteria templates return", () => {
    expect(gaugeBands(THRESHOLDS)).toEqual([
      { verdict: "NO_GO", from: 0, to: 0.6 },
      { verdict: "REVIEW", from: 0.6, to: 0.8 },
      { verdict: "GO", from: 0.8, to: 1 },
    ]);
  });

  it("puts each score in the band the decision engine would", () => {
    expect(scoreBand(0, THRESHOLDS)).toBe("NO_GO");
    expect(scoreBand(0.59, THRESHOLDS)).toBe("NO_GO");
    expect(scoreBand(0.6, THRESHOLDS)).toBe("REVIEW");
    expect(scoreBand(0.79, THRESHOLDS)).toBe("REVIEW");
    expect(scoreBand(0.8, THRESHOLDS)).toBe("GO");
    expect(scoreBand(1, THRESHOLDS)).toBe("GO");
  });
});

describe("metricBars", () => {
  it("keeps an unmeasured metric as an explicit empty state, never a zero", () => {
    const [bar] = metricBars([
      metric({
        name: "retrieval_context_recall",
        score: 0,
        instrumented: false,
        passed: false,
        threshold: 0.6,
      }),
    ]);
    expect(bar?.measured).toBe(false);
    expect(bar?.score).toBeNull();
    expect(bar?.passed).toBeNull();
    expect(bar?.label).toBe("retrieval context recall");
  });

  it("passes measured scores through with their gate data", () => {
    const [bar] = metricBars([
      metric({ name: "output_nonempty", score: 0.9, weight: 0.1, hard_gate: true, threshold: 1 }),
    ]);
    expect(bar).toMatchObject({
      name: "output_nonempty",
      score: 0.9,
      measured: true,
      weight: 0.1,
      hardGate: true,
      passed: true,
      threshold: 1,
    });
  });

  it("returns an empty list for an empty run instead of inventing bars", () => {
    expect(metricBars([])).toEqual([]);
  });
});

describe("percentile", () => {
  it("interpolates linearly between the closest ranks", () => {
    expect(percentile([0, 10, 20, 30, 40], 0.5)).toBe(20);
    expect(percentile([0, 10, 20, 30, 40], 0.25)).toBe(10);
    expect(percentile([0, 10, 20, 30, 40], 0.95)).toBeCloseTo(38);
    expect(percentile([1, 2], 0.5)).toBe(1.5);
    expect(percentile([1, 2], 0.95)).toBeCloseTo(1.95);
  });

  it("returns the only sample for one value and ignores non-finite input", () => {
    expect(percentile([7], 0.95)).toBe(7);
    expect(percentile([NaN, 5, Infinity], 0.5)).toBe(5);
    expect(percentile([], 0.5)).toBeNull();
  });
});

describe("latencySummary", () => {
  it("computes p50, p95 and the slowest cases from the measured timings", () => {
    const summary = latencySummary([
      { row_index: 0, latency_ms: 100 },
      { row_index: 1, latency_ms: 200 },
      { row_index: 2, latency_ms: null },
      { row_index: 3, latency_ms: 300 },
      { row_index: 4, latency_ms: 400 },
    ]);
    expect(summary?.samples).toBe(4);
    expect(summary?.p50).toBe(250);
    expect(summary?.p95).toBeCloseTo(385);
    expect(summary?.slowest).toEqual([
      { row: 4, latencyMs: 400 },
      { row: 3, latencyMs: 300 },
      { row: 1, latencyMs: 200 },
      { row: 0, latencyMs: 100 },
    ]);
  });

  it("caps the slowest list at the requested limit", () => {
    const items = Array.from({ length: 8 }, (_item, index) => ({
      row_index: index,
      latency_ms: (index + 1) * 100,
    }));
    expect(latencySummary(items, 3)?.slowest).toHaveLength(3);
  });

  it("returns null when no case carries a timing, so the chart stays hidden", () => {
    expect(latencySummary([])).toBeNull();
    expect(latencySummary([{ row_index: 0, latency_ms: null }])).toBeNull();
  });
});

describe("safetyBars", () => {
  const safetyMetric = metric({
    name: "attack_resisted",
    details: {
      sets: [
        {
          id: "system_prompt_leak",
          name: "System prompt leaks",
          cases: 8,
          failed: ["a1", "a2"],
          critical_failures: ["a1"],
          critical_cases: 3,
        },
        {
          id: "direct_injection",
          name: "Direct injection",
          cases: 10,
          failed: [],
          critical_failures: [],
          critical_cases: 0,
        },
      ],
    },
  });

  it("splits each category into leaked and no-leak-recorded counts", () => {
    const [first, second] = safetyBars([safetyMetric]);
    expect(first).toMatchObject({
      id: "system_prompt_leak",
      name: "System prompt leaks",
      cases: 8,
      leaked: 2,
      noLeak: 6,
      criticalFailures: 1,
      criticalCases: 3,
    });
    expect(second).toMatchObject({
      id: "direct_injection",
      cases: 10,
      leaked: 0,
      noLeak: 10,
      criticalFailures: 0,
    });
  });

  it("returns no categories when safety never ran or the details are absent", () => {
    expect(safetyBars([])).toEqual([]);
    expect(safetyBars([metric({ name: "attack_resisted", instrumented: false, details: {} })])).toEqual(
      [],
    );
    expect(
      safetyBars([metric({ name: "answer_match", details: { attacks: 44 } })]),
    ).toEqual([]);
  });
});

describe("trendPoints", () => {
  const run = (overrides: Partial<TrendRun> = {}): TrendRun => ({
    id: "r1",
    name: "Run one",
    created_at: "2026-11-01T10:00:00Z",
    score: 0.9,
    verdict: "GO",
    ...overrides,
  });

  it("plots scored runs oldest first and leaves unscored ones out", () => {
    const points = trendPoints([
      run({ id: "b", created_at: "2026-11-03T10:00:00Z", score: 0.5, verdict: "NO_GO", name: "Run three" }),
      run({ id: "a", created_at: "2026-11-01T10:00:00Z", score: null, verdict: null, name: "Unscored" }),
      run({ id: "c", created_at: "2026-11-02T10:00:00Z", score: 0.7, verdict: "REVIEW", name: "Run two" }),
    ]);
    expect(points.map((point) => point.id)).toEqual(["c", "b"]);
    expect(points[0]).toMatchObject({ name: "Run two", score: 0.7, verdict: "REVIEW" });
  });

  it("returns an empty list until two runs make the trend drawable", () => {
    expect(trendPoints([])).toEqual([]);
    expect(trendPoints([run({ score: null, verdict: "GO" })])).toEqual([]);
  });
});
