import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DemoPanel } from "./DemoPanel";
import { ApiError } from "../lib/api";
import type { Run } from "../lib/runs";

const { loadDemoMock, startRunMock, getRunMock } = vi.hoisted(() => ({
  loadDemoMock: vi.fn(),
  startRunMock: vi.fn(),
  getRunMock: vi.fn(),
}));

vi.mock("../lib/demo", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/demo")>();
  return { ...actual, loadDemo: loadDemoMock };
});

vi.mock("../lib/runs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/runs")>();
  return { ...actual, startRun: startRunMock, getRun: getRunMock };
});

const SETUP = {
  name: "Demo — College helpdesk",
  dataset_id: "ds-1",
  dataset_version_id: "dv-1",
  good_url: "http://demo-app:9000/chat",
  broken_url: "http://demo-app-broken:9000/chat",
};

function makeRun(overrides: Partial<Run> = {}): Run {
  return {
    id: "4f0c1a9e-0000-4000-8000-0000000000a1",
    name: "Demo — healthy helpdesk",
    entry_point: "http_endpoint",
    state: "completed",
    verdict: "GO",
    score: 1,
    verdict_reason: "Weighted score 1.00 is above the GO threshold 0.80.",
    is_partial: false,
    criteria_profile: "rag_chatbot",
    test_types: ["quality", "safety", "operations"],
    dataset_id: "ds-1",
    dataset_version_id: "dv-1",
    created_at: "2026-10-26T09:00:00Z",
    started_at: "2026-10-26T09:00:00Z",
    completed_at: "2026-10-26T09:01:00Z",
    progress: {
      items_done: 12,
      items_total: 12,
      items_failed: 0,
      items_cancelled: 0,
      stage: "finished",
      started_at: "2026-10-26T09:00:00Z",
      updated_at: "2026-10-26T09:01:00Z",
      elapsed_seconds: 30,
    },
    metrics: [],
    failed_cases: [],
    judge: null,
    judge_skipped_reason: null,
    ...overrides,
  };
}

const GOOD_RUN = makeRun();
const BROKEN_RUN = makeRun({
  id: "4f0c1a9e-0000-4000-8000-0000000000a2",
  name: "Demo — broken helpdesk",
  verdict: "NO_GO",
  score: 0.42,
  verdict_reason:
    "Weighted score 0.42 is below the REVIEW threshold 0.60. Weakest metrics: answer_match 0.00.",
});

describe("DemoPanel", () => {
  beforeEach(() => {
    loadDemoMock.mockReset().mockResolvedValue(SETUP);
    startRunMock.mockReset();
    getRunMock.mockReset();
  });

  it("runs the good and the broken demo and shows both verdicts", async () => {
    startRunMock.mockResolvedValueOnce(GOOD_RUN).mockResolvedValueOnce(BROKEN_RUN);
    render(<DemoPanel />);

    expect(screen.getByTestId("demo-hint")).toHaveTextContent("no model required");
    await userEvent.click(screen.getByTestId("try-demo"));

    expect(await screen.findByTestId("demo-good-verdict")).toHaveTextContent("Go");
    expect(screen.getByTestId("demo-broken-verdict")).toHaveTextContent("No-Go");
    expect(screen.getByTestId("demo-good-score")).toHaveTextContent("1.00");
    expect(screen.getByTestId("demo-good-reason")).toHaveTextContent("GO threshold 0.80");

    // The broken run's reason must name the score, the threshold and the metric.
    const brokenReason = screen.getByTestId("demo-broken-reason");
    expect(brokenReason).toHaveTextContent("Weighted score 0.42");
    expect(brokenReason).toHaveTextContent("below the REVIEW threshold 0.60");
    expect(brokenReason).toHaveTextContent("answer_match 0.00");

    // Both legs go through the normal runs API against the seeded dataset.
    expect(loadDemoMock).toHaveBeenCalledTimes(1);
    expect(startRunMock).toHaveBeenCalledTimes(2);
    const [good, broken] = startRunMock.mock.calls;
    expect(good?.[0]).toMatchObject({
      entry_point: "http_endpoint",
      target: SETUP.good_url,
      dataset_version_id: SETUP.dataset_version_id,
      allow_private_targets: true,
    });
    expect(broken?.[0]).toMatchObject({ target: SETUP.broken_url });

    // The button is usable again: no spinner can stick.
    expect(screen.getByTestId("try-demo")).toBeEnabled();
  });

  it("reports a load failure instead of spinning forever", async () => {
    loadDemoMock.mockRejectedValue(new ApiError("Demo setup failed.", 400, "bad_request"));
    render(<DemoPanel />);

    await userEvent.click(screen.getByTestId("try-demo"));

    expect(await screen.findByTestId("demo-error")).toHaveTextContent("Demo setup failed.");
    expect(startRunMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("try-demo")).toBeEnabled();
  });

  it("tells the user how to start the demo app when every run fails", async () => {
    startRunMock
      .mockResolvedValueOnce(makeRun({ state: "failed", verdict: null, score: null }))
      .mockResolvedValueOnce(
        makeRun({
          id: "4f0c1a9e-0000-4000-8000-0000000000a3",
          state: "failed",
          verdict: null,
          score: null,
        }),
      );
    render(<DemoPanel />);

    await userEvent.click(screen.getByTestId("try-demo"));

    expect(await screen.findByTestId("demo-unreachable")).toHaveTextContent(
      "docker compose --profile demo up -d",
    );
    expect(screen.getByTestId("demo-results")).toBeInTheDocument();
    expect(screen.getByTestId("try-demo")).toBeEnabled();
  });
});
