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

  it("rejects non-curl input and commands without a URL", () => {
    expect(parseCurl("wget https://x.test")).toBeNull();
    expect(parseCurl("")).toBeNull();
    expect(parseCurl("curl --help")).toBeNull();
  });
});
