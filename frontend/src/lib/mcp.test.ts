import { describe, expect, it } from "vitest";

import { buildMcpRunPayload, parseExtraArgs, type McpConfig } from "./mcp";

const config: McpConfig = {
  url: " https://mcp.example.com/mcp ",
  tool: "search",
  questionArg: "query",
  extraArgs: '{"locale": "en"}',
  headersSecret: "encrypted-blob",
  headerNames: ["Authorization"],
};

describe("parseExtraArgs", () => {
  it("treats an empty box as no extra arguments", () => {
    expect(parseExtraArgs("   ")).toEqual({ value: {} });
  });

  it("rejects a broken document and a non-object", () => {
    expect(parseExtraArgs("{").error).toMatch(/valid JSON/);
    expect(parseExtraArgs("[1, 2]").error).toMatch(/JSON object/);
  });

  it("accepts an object", () => {
    expect(parseExtraArgs('{"locale": "en"}')).toEqual({ value: { locale: "en" } });
  });
});

describe("buildMcpRunPayload", () => {
  it("carries the entry point, the tool, the argument and the extras", () => {
    const payload = buildMcpRunPayload({
      config,
      allowPrivate: true,
      permissionConfirmed: false,
      maxRetries: 2,
    });

    expect(payload).toMatchObject({
      entry_point: "mcp_server",
      target: "https://mcp.example.com/mcp",
      mcp_tool: "search",
      mcp_question_arg: "query",
      mcp_extra_args: { locale: "en" },
      headers_secret: "encrypted-blob",
      header_names: ["Authorization"],
      timeout_seconds: 60,
      allow_private_targets: true,
      max_retries: 2,
    });
    // A target on this computer invents no permission record.
    expect(payload?.permission_confirmed).toBe(false);
    expect(payload?.permission_reference).toBeUndefined();
  });

  it("records the permission for a remote server", () => {
    const payload = buildMcpRunPayload({
      config,
      allowPrivate: false,
      permissionConfirmed: true,
      permissionReference: " TICKET-42 ",
    });

    expect(payload?.permission_confirmed).toBe(true);
    expect(payload?.permission_reference).toBe("TICKET-42");
  });

  it("returns nothing until the tool, the argument and the JSON are valid", () => {
    expect(
      buildMcpRunPayload({
        config: { ...config, tool: "" },
        allowPrivate: true,
        permissionConfirmed: false,
      }),
    ).toBeNull();
    expect(
      buildMcpRunPayload({
        config: { ...config, questionArg: "" },
        allowPrivate: true,
        permissionConfirmed: false,
      }),
    ).toBeNull();
    expect(
      buildMcpRunPayload({
        config: { ...config, extraArgs: "{" },
        allowPrivate: true,
        permissionConfirmed: false,
      }),
    ).toBeNull();
    expect(
      buildMcpRunPayload({
        config: { ...config, url: " " },
        allowPrivate: true,
        permissionConfirmed: false,
      }),
    ).toBeNull();
  });
});
