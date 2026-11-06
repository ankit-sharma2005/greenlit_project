import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { McpPanel, type McpPanelProps } from "./McpPanel";
import type { McpConfig, McpTool } from "../lib/mcp";

const api = vi.hoisted(() => ({
  listMcpTools: vi.fn(),
  encryptHeaders: vi.fn(),
}));

vi.mock("../lib/mcp", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/mcp")>();
  return { ...actual, listMcpTools: api.listMcpTools, encryptHeaders: api.encryptHeaders };
});

const search: McpTool = {
  name: "search",
  description: "Search the helpdesk knowledge base",
  required_arguments: ["query"],
  string_arguments: ["query"],
  argument_names: ["query", "limit"],
  suggested_question_arg: "query",
};

const compare: McpTool = {
  name: "compare",
  description: "Compare two documents",
  required_arguments: ["left", "right"],
  string_arguments: ["left", "right"],
  argument_names: ["left", "right"],
  suggested_question_arg: null,
};

const emptyConfig: McpConfig = {
  url: "https://mcp.example.com/mcp",
  tool: "",
  questionArg: "",
  extraArgs: "",
  headersSecret: null,
  headerNames: [],
};

/** A controlled host, so a typed value behaves like it does on the page. */
function StatefulPanel({
  initial,
  onConfigChange,
  ...rest
}: Omit<McpPanelProps, "config" | "onConfigChange"> & {
  initial: McpConfig;
  onConfigChange: (patch: Partial<McpConfig>) => void;
}) {
  const [config, setConfig] = useState(initial);
  return (
    <McpPanel
      config={config}
      onConfigChange={(patch) => {
        setConfig((previous) => ({ ...previous, ...patch }));
        onConfigChange(patch);
      }}
      {...rest}
    />
  );
}

function renderPanel(overrides: Partial<Omit<McpPanelProps, "config">> = {}, config = emptyConfig) {
  const onConfigChange = vi.fn();
  const view = render(
    <StatefulPanel
      initial={config}
      onConfigChange={onConfigChange}
      allowPrivate={overrides.allowPrivate ?? true}
      permissionConfirmed={overrides.permissionConfirmed ?? false}
      permissionReference={overrides.permissionReference ?? ""}
      disabled={overrides.disabled}
    />,
  );
  return { ...view, onConfigChange };
}

beforeEach(() => {
  vi.clearAllMocks();
  api.listMcpTools.mockResolvedValue({
    server: "mock-mcp",
    target: "mcp.example.com/mcp",
    tools: [search, compare],
  });
  api.encryptHeaders.mockResolvedValue({
    headers_secret: "encrypted-blob",
    header_names: ["Authorization"],
  });
});

describe("McpPanel", () => {
  it("fills the tool list on discover and preselects the only required string argument", async () => {
    const { onConfigChange } = renderPanel();

    await userEvent.click(screen.getByTestId("mcp-discover"));

    await waitFor(() => expect(screen.getByTestId("mcp-tool")).toBeInTheDocument());
    expect(screen.getByTestId("mcp-tool")).toHaveValue("");
    expect(screen.getByTestId("mcp-server-name")).toHaveTextContent("mock-mcp");
    // Two tools and two suggestions, so the argument is the first suggested slot.
    expect(onConfigChange).toHaveBeenCalledWith(
      expect.objectContaining({ questionArg: "query", headersSecret: null, headerNames: [] }),
    );
  });

  it("preselects the tool when the server lists exactly one", async () => {
    api.listMcpTools.mockResolvedValue({
      server: "one-tool",
      target: "mcp.example.com/mcp",
      tools: [search],
    });
    const { onConfigChange } = renderPanel();

    await userEvent.click(screen.getByTestId("mcp-discover"));

    await waitFor(() =>
      expect(onConfigChange).toHaveBeenCalledWith(
        expect.objectContaining({ tool: "search", questionArg: "query" }),
      ),
    );
  });

  it("encrypts a typed Authorization header and never passes the value up", async () => {
    const { onConfigChange } = renderPanel();

    await userEvent.type(screen.getByTestId("mcp-auth"), "Bearer secret-token");
    await userEvent.click(screen.getByTestId("mcp-discover"));

    await waitFor(() => expect(api.encryptHeaders).toHaveBeenCalled());
    expect(api.encryptHeaders).toHaveBeenCalledWith({ Authorization: "Bearer secret-token" });
    const reported = onConfigChange.mock.calls.flatMap(([patch]) => Object.values(patch));
    expect(reported).not.toContain("Bearer secret-token");
    expect(onConfigChange).toHaveBeenCalledWith(
      expect.objectContaining({ headersSecret: "encrypted-blob", headerNames: ["Authorization"] }),
    );
  });

  it("does not contact a remote server without the permission record", async () => {
    renderPanel({ allowPrivate: false, permissionConfirmed: false, permissionReference: "" });

    await userEvent.click(screen.getByTestId("mcp-discover"));

    expect(screen.getByTestId("mcp-error")).toHaveTextContent("permission");
    expect(api.listMcpTools).not.toHaveBeenCalled();
  });

  it("shows an error for extra arguments that are not a JSON object", async () => {
    renderPanel();
    await userEvent.click(screen.getByTestId("mcp-discover"));
    await waitFor(() => expect(screen.getByTestId("mcp-extra-args")).toBeInTheDocument());

    await userEvent.type(screen.getByTestId("mcp-extra-args"), "{{");

    expect(screen.getByTestId("mcp-extra-error")).toHaveTextContent("valid JSON");
  });

  it("renders a tool description as text, never as markup", async () => {
    api.listMcpTools.mockResolvedValue({
      server: "noisy",
      target: "mcp.example.com/mcp",
      tools: [{ ...search, description: "<script>alert(1)</script> search" }],
    });
    const { container } = renderPanel();

    await userEvent.click(screen.getByTestId("mcp-discover"));

    await waitFor(() => expect(screen.getByTestId("mcp-tool")).toBeInTheDocument());
    const option = screen.getByRole("option", { name: /search/ });
    expect(option).toHaveTextContent("<script>alert(1)</script>");
    expect(container.querySelectorAll("script")).toHaveLength(0);
  });

  it("reports the chosen tool and its argument upward", async () => {
    const { onConfigChange } = renderPanel();
    await userEvent.click(screen.getByTestId("mcp-discover"));
    await waitFor(() => expect(screen.getByTestId("mcp-tool")).toBeInTheDocument());

    await userEvent.selectOptions(screen.getByTestId("mcp-tool"), "compare");

    // "compare" has two required strings, so no argument is guessed.
    expect(onConfigChange).toHaveBeenCalledWith({ tool: "compare", questionArg: "" });

    await userEvent.selectOptions(screen.getByTestId("mcp-question-arg"), "right");
    expect(onConfigChange).toHaveBeenCalledWith({ questionArg: "right" });
    expect(screen.getByTestId("mcp-question-arg")).toHaveValue("right");
  });
});
