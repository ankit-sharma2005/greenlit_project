import { describe, expect, it } from "vitest";

import { parseCurl } from "./curl";

describe("parseCurl", () => {
  it("extracts a bare URL and defaults to POST", () => {
    expect(parseCurl("curl https://myapp.local/ask")).toEqual({
      method: "POST",
      url: "https://myapp.local/ask",
      headerCount: 0,
    });
  });

  it("honours -X and quoted URLs", () => {
    expect(parseCurl("curl -X GET 'https://myapp.local/ask'")).toEqual({
      method: "GET",
      url: "https://myapp.local/ask",
      headerCount: 0,
    });
  });

  it("counts headers and skips data flags", () => {
    const parsed = parseCurl(
      `curl https://x.test/ask -H "Content-Type: application/json" ` +
        `-H "Authorization: Bearer token" -d '{"question": "hi"}'`,
    );
    expect(parsed).toEqual({ method: "POST", url: "https://x.test/ask", headerCount: 2 });
  });

  it.each([
    [
      `curl -X POST https://example.test/ask -H "A: b" -d '{"q":"x"}'`,
      { method: "POST", url: "https://example.test/ask", headerCount: 1 },
    ],
    [
      "curl --request POST --url https://example.test/ask",
      { method: "POST", url: "https://example.test/ask", headerCount: 0 },
    ],
    [
      `curl -H "A: b" -X POST 'https://example.test/ask' --data-raw '{"q":"x"}'`,
      { method: "POST", url: "https://example.test/ask", headerCount: 1 },
    ],
    [
      `curl 'https://example.test/ask' -H 'A: b' --data-raw '{"q":"x"}'`,
      { method: "POST", url: "https://example.test/ask", headerCount: 1 },
    ],
    [
      `curl -L -s --compressed https://example.test/ask -d '{"q":"x"}'`,
      { method: "POST", url: "https://example.test/ask", headerCount: 0 },
    ],
  ])("finds the URL regardless of option order: %s", (curl, expected) => {
    expect(parseCurl(curl as string)).toEqual(expected);
  });

  it("rejects non-curl input and commands without a URL", () => {
    expect(parseCurl("wget https://x.test")).toBeNull();
    expect(parseCurl("")).toBeNull();
    expect(parseCurl("curl --help")).toBeNull();
  });
});
