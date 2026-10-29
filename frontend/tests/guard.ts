/**
 * The guardrail the e2e fixtures give a "healthy" app.
 *
 * Safety is a real test now (spec 8.3): the worker sends the built-in attack set
 * through the app's own connector, and a missing refusal for disallowed content
 * is a hard NO-GO. A fixture that answers every prompt therefore cannot reach GO,
 * exactly like the demo app, which needed the same guard (DECISIONS.md D8.6).
 *
 * The hints and the refusal wording mirror `backend/app/services/demo.py` and
 * `backend/app/safety/metrics.py` (`REFUSAL_PHRASES`), so a guarded fixture passes
 * the probes for the same reason a real guarded app does.
 */

const DISALLOWED_HINTS: readonly string[] = [
  "explosive",
  "weapon",
  "illegal drug",
  "malware",
  "break into",
  "hateful",
  "fraud",
  "hurt someone",
];

/** Matches `REFUSAL_PHRASES` ("i can't help") so the probe sees a refusal. */
export const GUARDED_REFUSAL =
  "I can't help with that. I answer questions about the product and its documentation.";

/** True for a request the built-in attack set expects an app to decline. */
export function isDisallowed(prompt: string): boolean {
  const lowered = prompt.toLowerCase();
  return DISALLOWED_HINTS.some((hint) => lowered.includes(hint));
}
