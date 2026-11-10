import { describe, expect, it } from "vitest";

import { formatDate, formatDateTime, timeZoneChoices } from "./dates";

// One instant, two zones: 23:30 UTC is already midnight in Berlin and still
// late afternoon in New York. The exact wording depends on the machine's locale,
// so each assertion looks for the clock time the zone must produce.
const INSTANT = "2026-11-10T23:30:00Z";

describe("dates in the account's time zone", () => {
  it("renders the same instant differently in two zones", () => {
    const berlin = formatDateTime(INSTANT, "Europe/Berlin");
    const newYork = formatDateTime(INSTANT, "America/New_York");

    expect(berlin).not.toBe(newYork);
    expect(berlin).toContain("00:30");
    expect(newYork).toContain("18:30");
  });

  it("moves the date itself when the zone crosses midnight", () => {
    // 00:30 UTC is 11 November in Berlin and still 10 November in New York.
    const midnightish = "2026-11-11T00:30:00Z";

    expect(formatDate(midnightish, "Europe/Berlin")).toContain("11");
    expect(formatDate(midnightish, "America/New_York")).toContain("10");
  });

  it("falls back to the browser's zone for an unusable name, never throwing", () => {
    expect(formatDateTime(INSTANT, "Mars/Olympus")).not.toBe("—");
    expect(formatDateTime(INSTANT, null)).not.toBe("—");
  });

  it("says so rather than inventing a date", () => {
    expect(formatDateTime(null)).toBe("—");
    expect(formatDate("not a date")).toBe("—");
  });

  it("offers zones to choose from", () => {
    const zones = timeZoneChoices();
    expect(zones.length).toBeGreaterThan(0);
    expect(zones).toContain("UTC");
  });
});
