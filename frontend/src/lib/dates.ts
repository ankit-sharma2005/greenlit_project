/**
 * Dates, rendered in the account's chosen time zone.
 *
 * The zone is an IANA name stored on the account; `Intl` does the conversion, so
 * there is no time-zone database in this bundle and no new dependency. With no
 * zone chosen the browser's own is used, which is what every screen showed before
 * the choice existed.
 */

const FALLBACK_ZONES = [
  "UTC",
  "Europe/London",
  "Europe/Berlin",
  "Europe/Madrid",
  "America/New_York",
  "America/Chicago",
  "America/Los_Angeles",
  "America/Sao_Paulo",
  "Asia/Kolkata",
  "Asia/Shanghai",
  "Asia/Tokyo",
  "Australia/Sydney",
];

/** Every IANA zone this browser knows, or a short fixed list when it will not say. */
export function timeZoneChoices(): string[] {
  const supported = (
    Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
  ).supportedValuesOf;
  let zones: string[] | null = null;
  if (typeof supported === "function") {
    try {
      const listed = supported("timeZone");
      if (Array.isArray(listed) && listed.length > 0) zones = listed;
    } catch {
      /* older browsers throw; the fixed list below is the answer */
    }
  }
  const all = zones ?? FALLBACK_ZONES;
  // `supportedValuesOf` leaves UTC out in some engines, and a user who wants
  // UTC has no other way to ask for it.
  return all.includes("UTC") ? all : ["UTC", ...all];
}

function formatter(timeZone: string | null | undefined, withTime: boolean): Intl.DateTimeFormat {
  let zone: string | undefined;
  if (timeZone) {
    try {
      // An unknown zone makes Intl throw; falling back is better than a crash
      // in a screen whose only job is to show a date.
      new Intl.DateTimeFormat("en-US", { timeZone });
      zone = timeZone;
    } catch {
      zone = undefined;
    }
  }
  // The browser's own locale, as every screen already used: the only thing this
  // module changes is the zone.
  return new Intl.DateTimeFormat(undefined, {
    timeZone: zone,
    year: "numeric",
    month: "short",
    day: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}),
    timeZoneName: withTime ? "short" : undefined,
  });
}

/** "12 Nov 2026, 14:05 GMT+1" (the exact short name depends on the zone). */
export function formatDateTime(value: string | null | undefined, timeZone?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return formatter(timeZone, true).format(date);
}

/** "12 Nov 2026". */
export function formatDate(value: string | null | undefined, timeZone?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return formatter(timeZone, false).format(date);
}
