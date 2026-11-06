/**
 * The MCP server entry point: discover one tool, choose where the question goes.
 *
 * GreenLit calls a single tool of a Streamable-HTTP MCP server once per test
 * case. Only servers reachable by URL are supported, so this panel has no
 * command, no stdio option and no local runner: nothing typed here can start a
 * process. The Authorization value never leaves this component in the clear —
 * it is encrypted by the server and only the blob is passed up.
 */

import { useState } from "react";

import { Button } from "./Button";
import { ApiError } from "../lib/api";
import {
  encryptHeaders,
  listMcpTools,
  parseExtraArgs,
  type McpConfig,
  type McpTool,
} from "../lib/mcp";

export interface McpPanelProps {
  config: McpConfig;
  onConfigChange: (patch: Partial<McpConfig>) => void;
  /** True when the server runs on this computer (no permission record needed). */
  allowPrivate: boolean;
  permissionConfirmed: boolean;
  permissionReference: string;
  disabled?: boolean;
}

export function McpPanel({
  config,
  onConfigChange,
  allowPrivate,
  permissionConfirmed,
  permissionReference,
  disabled = false,
}: McpPanelProps) {
  // Held here, never in the page's state or localStorage: it is a password.
  const [authorization, setAuthorization] = useState("");
  const [tools, setTools] = useState<McpTool[]>([]);
  const [server, setServer] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const extra = parseExtraArgs(config.extraArgs);
  const selected = tools.find((tool) => tool.name === config.tool) ?? null;

  async function discover() {
    setError(null);
    setNotice(null);
    if (!config.url.trim()) {
      setError("Enter the MCP server's URL first.");
      return;
    }
    if (!allowPrivate && (!permissionConfirmed || !permissionReference.trim())) {
      setError(
        "This server is not on your computer. Confirm that you own it or have permission to test it, and give a reference, before GreenLit sends anything.",
      );
      return;
    }
    setLoading(true);
    try {
      const encrypted = authorization.trim()
        ? await encryptHeaders({ Authorization: authorization.trim() })
        : null;
      const found = await listMcpTools({
        target: config.url.trim(),
        headers_secret: encrypted?.headers_secret,
        header_names: encrypted?.header_names,
        allow_private_targets: allowPrivate,
        permission_confirmed: !allowPrivate && permissionConfirmed,
        permission_reference:
          !allowPrivate && permissionReference.trim() ? permissionReference.trim() : undefined,
      });
      setTools(found.tools);
      setServer(found.server);
      const only = found.tools.length === 1 ? found.tools[0] : null;
      const tool = only ? only.name : config.tool;
      const suggested =
        found.tools.find((candidate) => candidate.name === tool)?.suggested_question_arg ??
        found.tools.find((candidate) => candidate.suggested_question_arg)?.suggested_question_arg ??
        "";
      onConfigChange({
        tool,
        questionArg: suggested,
        headersSecret: encrypted?.headers_secret ?? null,
        headerNames: encrypted?.header_names ?? [],
      });
      setNotice(
        found.tools.length === 0
          ? "That server listed no tools."
          : `Found ${found.tools.length} tool${found.tools.length === 1 ? "" : "s"}${
              found.server ? ` on ${found.server}` : ""
            }.`,
      );
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Could not reach that MCP server. Check the URL and try again.",
      );
      setTools([]);
      setServer(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="card" aria-labelledby="mcp-heading" data-testid="mcp-panel">
      <div className="card__header">
        <h2 id="mcp-heading">MCP server</h2>
        <span className="badge badge--neutral">{tools.length} tools</span>
      </div>
      <p className="card__hint">
        GreenLit calls one tool of this server once per test case. Only servers reachable by URL are
        supported; stdio servers are not.
      </p>

      <div className="form__row">
        <label className="form__label" htmlFor="mcp-url">
          Server URL
        </label>
        <input
          id="mcp-url"
          data-testid="mcp-url"
          type="text"
          value={config.url}
          onChange={(event) => onConfigChange({ url: event.target.value })}
          placeholder="https://my-mcp.example.com/mcp"
          disabled={disabled}
        />
      </div>

      <div className="form__row">
        <label className="form__label" htmlFor="mcp-auth">
          Authorization header (optional)
        </label>
        <input
          id="mcp-auth"
          data-testid="mcp-auth"
          type="password"
          autoComplete="off"
          value={authorization}
          onChange={(event) => setAuthorization(event.target.value)}
          placeholder="Bearer …"
          disabled={disabled}
        />
        <p className="form__hint">
          Encrypted by the server before it is stored. It never goes into this browser&apos;s
          storage.
        </p>
      </div>

      <div className="datasets__actions">
        <Button
          variant="secondary"
          loading={loading}
          onClick={() => void discover()}
          disabled={disabled}
          data-testid="mcp-discover"
        >
          Discover tools
        </Button>
      </div>

      {error ? (
        <p className="form-error" role="alert" data-testid="mcp-error">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="notice" role="status" data-testid="mcp-notice">
          {notice}
        </p>
      ) : null}

      {tools.length > 0 ? (
        <>
          <div className="form__row">
            <label className="form__label" htmlFor="mcp-tool">
              Tool to call
            </label>
            <select
              id="mcp-tool"
              data-testid="mcp-tool"
              value={config.tool}
              onChange={(event) => {
                const tool = tools.find((candidate) => candidate.name === event.target.value);
                onConfigChange({
                  tool: event.target.value,
                  questionArg: tool?.suggested_question_arg ?? "",
                });
              }}
              disabled={disabled}
            >
              <option value="">Choose a tool</option>
              {tools.map((tool) => (
                <option key={tool.name} value={tool.name}>
                  {tool.description ? `${tool.name} — ${tool.description}` : tool.name}
                </option>
              ))}
            </select>
          </div>

          <div className="form__row">
            <label className="form__label" htmlFor="mcp-question-arg">
              Argument that carries the question
            </label>
            <select
              id="mcp-question-arg"
              data-testid="mcp-question-arg"
              value={config.questionArg}
              onChange={(event) => onConfigChange({ questionArg: event.target.value })}
              disabled={disabled || !selected}
            >
              <option value="">Choose an argument</option>
              {(selected?.argument_names ?? []).map((name) => (
                <option key={name} value={name}>
                  {selected?.required_arguments.includes(name) ? `${name} (required)` : name}
                </option>
              ))}
            </select>
            {selected && selected.suggested_question_arg ? (
              <p className="form__hint">
                Preselected: {selected.suggested_question_arg} is the only required string argument.
              </p>
            ) : null}
          </div>

          <div className="form__row">
            <label className="form__label" htmlFor="mcp-extra-args">
              Extra arguments (optional JSON)
            </label>
            <textarea
              id="mcp-extra-args"
              data-testid="mcp-extra-args"
              rows={3}
              value={config.extraArgs}
              onChange={(event) => onConfigChange({ extraArgs: event.target.value })}
              placeholder={'{"locale": "en"}'}
              disabled={disabled}
            />
            {extra.error ? (
              <p className="form-error" role="alert" data-testid="mcp-extra-error">
                {extra.error}
              </p>
            ) : null}
          </div>
        </>
      ) : null}

      {server ? (
        <p className="form__hint" data-testid="mcp-server-name">
          Server: {server}
        </p>
      ) : null}
    </section>
  );
}
