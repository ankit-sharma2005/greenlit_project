/** Minimal cURL parsing for the New Test page: method, URL and header count. */

const METHODS = new Set(["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]);

const DATA_FLAGS = new Set([
  "-d",
  "--data",
  "--data-raw",
  "--data-binary",
  "--data-ascii",
  "-F",
  "--form",
]);

export interface ParsedCurl {
  method: string;
  url: string;
  headerCount: number;
}

/** Parse a pasted curl command; null when no URL can be found. */
export function parseCurl(command: string): ParsedCurl | null {
  const trimmed = command.trim();
  if (!/^curl\b/.test(trimmed)) {
    return null;
  }

  const tokens = trimmed.split(/\s+/).filter(Boolean);
  let method = "";
  let url = "";
  let headerCount = 0;

  for (let i = 1; i < tokens.length; i += 1) {
    const token = tokens[i] ?? "";

    if (token === "-X" || token === "--request") {
      const candidate = (tokens[i + 1] ?? "").toUpperCase();
      if (METHODS.has(candidate)) {
        method = candidate;
        i += 1;
      }
      continue;
    }

    if (token === "-H" || token === "--header") {
      headerCount += 1;
      i += 1;
      continue;
    }

    if (DATA_FLAGS.has(token)) {
      i += 1;
      continue;
    }

    if (token.startsWith("-")) {
      continue;
    }

    const cleaned = token.replace(/^['"]+|['"]+$/g, "");
    if (/^https?:\/\//.test(cleaned) && !url) {
      url = cleaned;
    }
  }

  if (!url) {
    return null;
  }
  return { method: method || "POST", url, headerCount };
}
