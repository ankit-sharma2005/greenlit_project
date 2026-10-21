import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Link } from 'react-router-dom';
import { apiRequest, Workspace } from './api';
import DatasetStudio from './DatasetStudio';
import { buildConnectorPayload } from './connectorPayload';
import { parseUploadRows, UploadedRow } from './phase2Uploads';
import { ProjectTestChat } from './WorkspaceChat';

interface WorkspaceProjectsProps {
  accessToken: string;
  userRole: string;
  userId?: string;
  workspace: Workspace;
  page?: string;
  activeProjectId?: string;
  onProjectOptionsChange?: (
    projects: Array<{ id: string; name: string }>,
  ) => void;
  onActiveProjectChange?: (projectId: string) => void;
}

interface Project {
  id: string;
  name: string;
  description?: string | null;
  original_name?: string | null;
  duplicate_of?: string | null;
  is_duplicate?: boolean;
}

interface Provider {
  id: string;
  name: string;
  provider_type: string;
  base_url?: string | null;
  test_model?: string | null;
  default_model?: string | null;
  original_name?: string | null;
  duplicate_of?: string | null;
  is_duplicate?: boolean;
  rpm?: number | null;
  rpd?: number | null;
  max_input_tokens?: number | null;
  max_output_tokens?: number | null;
  has_api_key: boolean;
}

interface SettingsField {
  type?: string;
  title?: string;
  description?: string;
  enum?: Array<string | number>;
  default?: unknown;
  format?: string;
}

interface EntryPointType {
  type: string;
  label: string;
  description: string;
  access_level?: string;
  implemented?: boolean;
  coming_in?: string | number | null;
  settings_schema?: {
    type?: string;
    properties?: Record<string, SettingsField>;
    required?: string[];
  };
}

interface TestCallResult {
  test_call_id: string;
  trace: unknown;
  raw_response: unknown;
  latency_ms: number;
  detected_fields: string[];
  missing_fields: string[];
  preview?: UploadedRow[];
}

interface TestFailure {
  reason: string;
  nextStep: string;
  rawResponse?: unknown;
}

interface Connector {
  id?: string;
  name?: string;
  entry_point_type?: string;
  settings?: Record<string, unknown>;
  created_at?: string;
}

interface WorkspacePreferences {
  default_provider_id: string | null;
  active_project_id: string | null;
  last_page: string;
  last_entry_point: string | null;
  last_column_mapping: Record<string, unknown> | null;
  chat_retention_days: number;
}

const fallbackTypes: EntryPointType[] = [
  {
    type: 'HTTP_ENDPOINT',
    label: 'HTTP endpoint',
    description: 'App running at a URL (staging or localhost)',
  },
  {
    type: 'PYTHON_FUNCTION',
    label: 'Python function',
    description: 'A Python function (module:function)',
  },
  {
    type: 'PYTHON_SDK_TRACED',
    label: 'Python SDK traced',
    description: 'Python app instrumented with greenlit-trace',
  },
  {
    type: 'PROMPT_APP',
    label: 'Prompt App',
    description: 'No-code: system prompt + model',
  },
  {
    type: 'BUILTIN_RAG_APP',
    label: 'Built-in RAG App',
    description: 'Built-in RAG app (upload documents)',
  },
  {
    type: 'BUILTIN_AGENT_APP',
    label: 'Built-in agent app',
    description: 'Built-in tool-using agent',
  },
  {
    type: 'DOCKER_IMAGE',
    label: 'Docker image',
    description: 'Docker image or compose file',
    implemented: false,
  },
  {
    type: 'GIT_REPO',
    label: 'Git repository',
    description: 'Git repository + entrypoint',
    implemented: false,
  },
  {
    type: 'CLI_COMMAND',
    label: 'CLI command',
    description: 'Command-line program with an input template',
    implemented: false,
  },
  {
    type: 'PROXY_MODE',
    label: 'Proxy mode',
    description: 'Point your app LLM base URL at GreenLit',
    implemented: false,
  },
  {
    type: 'UPLOAD_OUTPUTS',
    label: 'Upload outputs',
    description: 'Upload inputs and outputs you already generated',
  },
  {
    type: 'WEBSITE_URL',
    label: 'Website URL',
    description: 'Website URL: discover the embedded chatbot',
    coming_in: 'Phase 4',
  },
  {
    type: 'MCP_SERVER',
    label: 'MCP server',
    description: 'App or agent exposed over MCP',
    coming_in: 'Phase 4',
  },
];

const phaseTwoTypes = new Set([
  'HTTP_ENDPOINT',
  'PROMPT_APP',
  'BUILTIN_RAG_APP',
  'BUILTIN_AGENT_APP',
  'UPLOAD_OUTPUTS',
]);
const providerEntryTypes = new Set([
  'PROMPT_APP',
  'BUILTIN_RAG_APP',
  'BUILTIN_AGENT_APP',
]);

const promptAppSchema: EntryPointType['settings_schema'] = {
  type: 'object',
  required: ['system_prompt'],
  properties: {
    system_prompt: {
      type: 'string',
      title: 'System prompt',
      description: 'Instructions sent to the model for every request.',
    },
    temperature: {
      type: 'number',
      title: 'Temperature',
      default: 0,
    },
    output_json_schema: {
      type: 'object',
      title: 'Output JSON schema (optional)',
      description: 'Optional JSON Schema used to describe structured output.',
    },
    context_messages: {
      type: 'integer',
      title: 'Context messages',
      default: 10,
    },
  },
};

const ragAppSchema: EntryPointType['settings_schema'] = {
  type: 'object',
  required: ['documents', 'prompt'],
  properties: {
    documents: {
      type: 'array',
      title: 'Documents (JSON)',
      description: 'Enter a JSON array of documents with title and text.',
    },
    chunk_size: {
      type: 'integer',
      title: 'Chunk size',
      default: 800,
    },
    chunk_overlap: {
      type: 'integer',
      title: 'Chunk overlap',
      default: 100,
    },
    top_k: {
      type: 'integer',
      title: 'Retrieved chunks (top-k)',
      default: 4,
    },
    prompt: {
      type: 'string',
      title: 'Answer prompt',
      description: 'Prompt used to answer using retrieved document context.',
    },
    temperature: {
      type: 'number',
      title: 'Temperature',
      default: 0,
    },
    context_messages: {
      type: 'integer',
      title: 'Context messages',
      default: 10,
    },
  },
};

const genericSchemas: Record<string, EntryPointType['settings_schema']> = {
  HTTP_ENDPOINT: {
    type: 'object',
    required: ['url'],
    properties: {
      url: { type: 'string', title: 'Endpoint URL', format: 'uri' },
      method: {
        type: 'string',
        title: 'HTTP method',
        enum: ['POST', 'GET'],
        default: 'POST',
      },
      request_body_template: {
        type: 'string',
        title: 'Request body template',
      },
      input_field: {
        type: 'string',
        title: 'Input field',
        default: 'input',
      },
      output_field: {
        type: 'string',
        title: 'Output field',
        default: 'output',
      },
      timeout_seconds: {
        type: 'integer',
        title: 'Timeout seconds',
        default: 15,
      },
      context_messages: {
        type: 'integer',
        title: 'Context messages',
        default: 10,
      },
      allow_private_targets: {
        type: 'boolean',
        title: 'Allow private targets',
        default: false,
        description:
          'Explicitly permits this connector to call localhost or private network addresses. Only workspace owners or admins may authorize it.',
      },
    },
  },
  PYTHON_FUNCTION: {
    type: 'object',
    required: ['callable'],
    properties: {
      callable: {
        type: 'string',
        title: 'Function (module:function)',
        description: 'Python callable exposed to the evaluation runner.',
      },
      working_directory: {
        type: 'string',
        title: 'Working directory (optional)',
      },
    },
  },
  PYTHON_SDK_TRACED: {
    type: 'object',
    required: ['callable'],
    properties: {
      callable: { type: 'string', title: 'Function (module:function)' },
      working_directory: {
        type: 'string',
        title: 'Working directory (optional)',
      },
    },
  },
  BUILTIN_AGENT_APP: {
    type: 'object',
    required: [],
    properties: {
      tools: {
        type: 'array',
        title: 'Tools (JSON)',
        default: [],
      },
      max_steps: { type: 'integer', title: 'Maximum steps', default: 5 },
      system_prompt: {
        type: 'string',
        title: 'System prompt',
        default: 'You are a helpful assistant.',
      },
      temperature: {
        type: 'number',
        title: 'Temperature',
        default: 0,
      },
      context_messages: {
        type: 'integer',
        title: 'Context messages',
        default: 10,
      },
    },
  },
  UPLOAD_OUTPUTS: {
    type: 'object',
    required: [],
    properties: {
      sample_output: { type: 'string', title: 'Sample output' },
      input_field: { type: 'string', title: 'Input field (optional)' },
    },
  },
};

function makeWorkspacePath(workspaceId: string, suffix: string) {
  return `/workspaces/${encodeURIComponent(workspaceId)}${suffix}`;
}

function safeProvider(provider: Provider): Provider {
  return {
    id: provider.id,
    name: provider.name,
    provider_type: provider.provider_type,
    base_url: provider.base_url,
    test_model: provider.default_model ?? provider.test_model,
    default_model: provider.default_model ?? provider.test_model,
    original_name: provider.original_name,
    duplicate_of: provider.duplicate_of,
    is_duplicate: provider.is_duplicate,
    rpm: provider.rpm,
    rpd: provider.rpd,
    max_input_tokens: provider.max_input_tokens,
    max_output_tokens: provider.max_output_tokens,
    has_api_key: provider.has_api_key,
  };
}

function safeConnector(connector: Connector): Connector {
  return {
    id: connector.id,
    name: connector.name,
    entry_point_type: connector.entry_point_type,
    created_at: connector.created_at,
  };
}

function initialSettings(
  type: EntryPointType | undefined,
): Record<string, unknown> {
  const schema = getSettingsSchema(type);
  const settings: Record<string, unknown> = {};
  for (const [key, field] of Object.entries(schema?.properties ?? {})) {
    if (field.default !== undefined) settings[key] = field.default;
  }
  return settings;
}

function getSettingsSchema(type: EntryPointType | undefined) {
  if (!type) return undefined;
  const schema: EntryPointType['settings_schema'] = type.settings_schema
    ?.properties
    ? type.settings_schema
    : type.type === 'PROMPT_APP'
      ? promptAppSchema
      : type.type === 'BUILTIN_RAG_APP'
        ? ragAppSchema
        : genericSchemas[type.type];
  const reservedFields = new Set(['entry_point_type', 'provider_id']);
  if (
    !schema ||
    !Object.keys(schema.properties ?? {}).some((field) =>
      reservedFields.has(field),
    )
  ) {
    return schema;
  }

  const properties: Record<string, SettingsField> = { ...schema.properties };
  for (const field of reservedFields) delete properties[field];
  return {
    ...schema,
    properties,
    required: schema.required?.filter((field) => field !== 'entry_point_type'),
  };
}

function scrubSecrets(value: unknown, secrets: string[]): unknown {
  if (typeof value === 'string') {
    return secrets.reduce(
      (safeValue, secret) =>
        secret ? safeValue.split(secret).join('[redacted]') : safeValue,
      value,
    );
  }
  if (Array.isArray(value)) {
    return value.map((item) => scrubSecrets(item, secrets));
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [
        key,
        scrubSecrets(item, secrets),
      ]),
    );
  }
  return value;
}

function secretSettings(settings: Record<string, unknown>) {
  return Object.entries(settings)
    .filter(([key]) =>
      /api[_-]?key|secret|token|password|credential/i.test(key),
    )
    .map(([, value]) => String(value))
    .filter(Boolean);
}

function connectorFailure(error: unknown, entryPointType: string) {
  const detail =
    error instanceof Error
      ? error.message
      : 'The test could not be completed. Review the settings and try again.';
  const message = detail.toLowerCase();
  if (message.includes('timeout') || message.includes('timed out')) {
    return {
      reason: 'The request timed out after 15 seconds.',
      nextStep:
        'Check that the app is running and increase the timeout in Advanced if needed.',
    };
  }
  if (
    message.includes('private endpoint') ||
    message.includes('private targets') ||
    message.includes('ssrf')
  ) {
    return {
      reason: 'GreenLit blocked this private URL to protect your workspace.',
      nextStep:
        'For a local app in Docker, use host.docker.internal and enable Allow private targets in Advanced. Only workspace owners or admins can do this.',
    };
  }
  if (message.includes('http 401') || message.includes('http 403')) {
    return {
      reason: 'Your app returned an authorization error (401/403).',
      nextStep: 'Check the app credentials and API key, then test again.',
    };
  }
  if (message.includes('response field') && message.includes('not found')) {
    return {
      reason: 'The JSON path for the answer was not found in the response.',
      nextStep:
        'Check the raw response and update the JSON path for the answer.',
    };
  }
  if (message.includes('json') && message.includes('response')) {
    return {
      reason: 'The app returned a non-JSON response.',
      nextStep:
        'Make the endpoint return JSON and check that the answer path exists.',
    };
  }
  if (
    message.includes('could not connect') ||
    message.includes('could not be resolved') ||
    message.includes('did not resolve') ||
    message.includes('fetch failed') ||
    message.includes('networkerror') ||
    message.includes('failed to fetch')
  ) {
    return {
      reason: 'The URL is unreachable.',
      nextStep:
        'Check the URL, port, and that the app is running and reachable from GreenLit.',
    };
  }
  if (
    message.includes('mapped columns are missing') ||
    message.includes('missing column') ||
    message.includes('choose valid input and output columns')
  ) {
    return {
      reason: 'A required column is missing from the uploaded file.',
      nextStep:
        'Choose the correct input and output columns, or upload a file that contains both.',
    };
  }
  if (message.includes('connector with this name already exists')) {
    return {
      reason: 'That connector name is already in use in this project.',
      nextStep: 'Choose a different connector name and save again.',
    };
  }
  return {
    reason: detail,
    nextStep:
      entryPointType === 'HTTP_ENDPOINT'
        ? 'Check the URL, request body, API key, and answer JSON path.'
        : 'Review the settings and sample input, then run the test again.',
  };
}

function formatJson(value: unknown) {
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}

function traceOutput(trace: unknown): unknown {
  if (
    trace &&
    typeof trace === 'object' &&
    !Array.isArray(trace) &&
    'output' in trace
  ) {
    return trace.output;
  }
  return trace;
}

interface WorkspaceDraft {
  project?: { name: string; description: string };
  provider?: {
    name: string;
    type: string;
    baseUrl: string;
    model: string;
    rpm: string;
    rpd: string;
    inputTokens: string;
    outputTokens: string;
  };
  connector?: {
    selectedType: string;
    providerId: string;
    settings: Record<string, unknown>;
    name: string;
    testInput: string;
  };
}

function workspaceDraftKey(
  userId: string,
  workspaceId: string,
  section: keyof WorkspaceDraft,
) {
  return `greenlit:draft:${userId}:${workspaceId}:${section}`;
}

function readWorkspaceDraft<T>(
  userId: string | undefined,
  workspaceId: string,
  section: keyof WorkspaceDraft,
): T | null {
  if (!userId || typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(
      workspaceDraftKey(userId, workspaceId, section),
    );
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function writeWorkspaceDraft(
  userId: string | undefined,
  workspaceId: string,
  section: keyof WorkspaceDraft,
  value: unknown,
) {
  if (!userId || typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(
      workspaceDraftKey(userId, workspaceId, section),
      JSON.stringify(redactDraftValue(value)),
    );
  } catch {
    // Storage can be unavailable or full; the in-memory form remains usable.
  }
}

function redactDraftValue(value: unknown): unknown {
  if (typeof value === 'string') {
    return value
      .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, 'Bearer [REDACTED]')
      .replace(
        /(\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|secret)\s*[:=]\s*['"]?)[^,\s'";&]+/gi,
        '$1[REDACTED]',
      )
      .replace(
        /\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})\b/gi,
        '[REDACTED]',
      );
  }
  if (Array.isArray(value)) return value.map(redactDraftValue);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).flatMap(([key, item]) =>
        /api[_-]?key|secret|token|password|credential/i.test(key)
          ? []
          : [[key, redactDraftValue(item)]],
      ),
    );
  }
  return value;
}

function clearWorkspaceDraft(
  userId: string | undefined,
  workspaceId: string,
  section: keyof WorkspaceDraft,
) {
  if (!userId || typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(
      workspaceDraftKey(userId, workspaceId, section),
    );
  } catch {
    // Keep the successful server save intact if browser cleanup is unavailable.
  }
}

function safeDraftSettings(settings: Record<string, unknown>) {
  return Object.fromEntries(
    Object.entries(settings).filter(
      ([key]) =>
        key !== 'rows' &&
        !/api[_-]?key|secret|token|password|credential/i.test(key),
    ),
  );
}

function SettingsEditor({
  entryType,
  settings,
  onChange,
  onError,
}: {
  entryType: EntryPointType;
  settings: Record<string, unknown>;
  onChange: (nextSettings: Record<string, unknown>) => void;
  onError: (message: string) => void;
}) {
  if (entryType.type === 'UPLOAD_OUTPUTS') {
    const rows = Array.isArray(settings.rows)
      ? (settings.rows as UploadedRow[])
      : [];
    const columns = rows.length > 0 ? Object.keys(rows[0]) : [];
    const mappings = [
      ['input_field', 'Input', true],
      ['output_field', 'Output', true],
      ['retrieved_contexts_field', 'Retrieved context', false],
      ['latency_ms_field', 'Latency (ms)', false],
      ['tokens_in_field', 'Tokens in', false],
      ['tokens_out_field', 'Tokens out', false],
    ] as const;
    const detected = [
      ['id', /^(id|record_id|example_id)$/i],
      ['input', /^(input|question|prompt|query)$/i],
      ['output', /^(output|answer|response|completion)$/i],
      ['retrieved_context', /^(retrieved_contexts?|contexts?)$/i],
      ['latency_ms', /^latency(_ms)?$/i],
      ['tokens_in', /^(tokens_in|input_tokens)$/i],
      ['tokens_out', /^(tokens_out|output_tokens)$/i],
    ].flatMap(([name, pattern]) => {
      if (!(pattern instanceof RegExp)) return [];
      const match = columns.find((column) => pattern.test(column));
      return match ? [`${String(name)}: ${match}`] : [];
    });
    const mappingFailed =
      rows.length > 0 &&
      (!String(settings.input_field ?? '') ||
        !String(settings.output_field ?? ''));
    return (
      <div className="phase2-form-stack">
        <label className="phase2-field">
          <span>Outputs file *</span>
          <input
            type="file"
            accept=".csv,.json,.jsonl,.xlsx,text/csv,application/json,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(event) => {
              const file = event.target.files?.[0];
              onError('');
              onChange({ ...settings, rows: [] });
              if (!file) return;
              void parseUploadRows(file)
                .then((nextRows) => {
                  const nextColumns = Object.keys(nextRows[0]);
                  const findColumn = (pattern: RegExp) =>
                    nextColumns.find((column) => pattern.test(column)) ?? '';
                  onChange({
                    ...settings,
                    rows: nextRows,
                    input_field: findColumn(/^(input|question|prompt|query)$/i),
                    output_field: findColumn(
                      /^(output|answer|response|completion)$/i,
                    ),
                    retrieved_contexts_field:
                      findColumn(/^(retrieved_contexts?|contexts?)$/i) || null,
                    latency_ms_field: findColumn(/^latency(_ms)?$/i) || null,
                    tokens_in_field:
                      findColumn(/^(tokens_in|input_tokens)$/i) || null,
                    tokens_out_field:
                      findColumn(/^(tokens_out|output_tokens)$/i) || null,
                  });
                  onError('');
                })
                .catch((error: unknown) => {
                  onError(
                    error instanceof Error
                      ? error.message
                      : 'The uploaded file could not be read.',
                  );
                });
            }}
          />
          <small>CSV, JSON, JSONL, or XLSX; up to 10,000 rows.</small>
        </label>
        {rows.length > 0 ? (
          <>
            <p className="phase2-inline-note">
              {detected.length > 0
                ? `Detected columns: ${detected.join(', ')}`
                : 'No standard columns were detected.'}
            </p>
            {mappingFailed && (
              <div className="phase2-form-grid">
                {mappings.map(([key, label, required]) => (
                  <label className="phase2-field" key={key}>
                    <span>
                      {label}
                      {required ? ' column *' : ' column (optional)'}
                    </span>
                    <select
                      required={required}
                      value={String(settings[key] ?? '')}
                      onChange={(event) =>
                        onChange({
                          ...settings,
                          [key]: event.target.value || null,
                        })
                      }
                    >
                      <option value="">Choose a column</option>
                      {columns.map((column) => (
                        <option key={column} value={column}>
                          {column}
                        </option>
                      ))}
                    </select>
                  </label>
                ))}
              </div>
            )}
            <div
              className="phase2-test-result"
              aria-label="Uploaded output preview"
            >
              <strong>Preview · first {Math.min(5, rows.length)} rows</strong>
              <pre>{formatJson(rows.slice(0, 5))}</pre>
            </div>
          </>
        ) : (
          <p className="field-hint-error" role="status">
            Choose a file to preview and detect its columns.
          </p>
        )}
      </div>
    );
  }
  if (entryType.type === 'HTTP_ENDPOINT') {
    return (
      <div className="phase2-form-stack">
        <label className="phase2-field">
          <span>App URL *</span>
          <input
            required
            type="url"
            value={String(settings.url ?? '')}
            onChange={(event) =>
              onChange({ ...settings, url: event.target.value })
            }
            placeholder="https://your-app.example.com/answer"
          />
        </label>
        <label className="phase2-field">
          <span>Method</span>
          <select
            value={String(settings.method ?? 'POST')}
            onChange={(event) =>
              onChange({ ...settings, method: event.target.value })
            }
          >
            <option value="POST">POST</option>
            <option value="GET">GET</option>
          </select>
        </label>
        {settings.method !== 'GET' && (
          <label className="phase2-field">
            <span>Request body template</span>
            <textarea
              rows={3}
              value={String(
                settings.request_body_template ?? '{"input": {{input}}}',
              )}
              onChange={(event) =>
                onChange({
                  ...settings,
                  request_body_template: event.target.value,
                })
              }
            />
            <small>Use {'{{input}}'} wherever the sample input belongs.</small>
          </label>
        )}
        <label className="phase2-field">
          <span>JSON path for the answer</span>
          <input
            value={String(settings.output_field ?? 'output')}
            onChange={(event) =>
              onChange({ ...settings, output_field: event.target.value })
            }
            placeholder="output or data.answer"
          />
          <small>Use dots for nested JSON, for example data.answer.</small>
        </label>
        <details className="phase2-advanced">
          <summary>Advanced</summary>
          <label className="phase2-field">
            <span>Timeout (seconds)</span>
            <input
              type="number"
              min="1"
              max="60"
              value={String(settings.timeout_seconds ?? 15)}
              onChange={(event) =>
                onChange({
                  ...settings,
                  timeout_seconds: Number(event.target.value),
                })
              }
            />
          </label>
          <label className="phase2-field">
            <span>GET input parameter name</span>
            <input
              value={String(settings.input_field ?? 'input')}
              onChange={(event) =>
                onChange({ ...settings, input_field: event.target.value })
              }
            />
          </label>
          <label className="phase2-field phase2-checkbox-field">
            <input
              className="phase2-checkbox"
              type="checkbox"
              checked={Boolean(settings.allow_private_targets)}
              onChange={(event) =>
                onChange({
                  ...settings,
                  allow_private_targets: event.target.checked,
                })
              }
            />
            <span>Allow private targets (workspace owner/admin only)</span>
          </label>
        </details>
      </div>
    );
  }
  if (entryType.type === 'PROMPT_APP') {
    return (
      <div className="phase2-form-stack">
        <label className="phase2-field">
          <span>System prompt *</span>
          <textarea
            required
            rows={6}
            value={String(settings.system_prompt ?? '')}
            onChange={(event) =>
              onChange({ ...settings, system_prompt: event.target.value })
            }
            placeholder="Describe how your app should respond."
          />
        </label>
        <label className="phase2-field">
          <span>Temperature</span>
          <input
            type="number"
            min="0"
            max="2"
            step="0.1"
            value={String(settings.temperature ?? 0)}
            onChange={(event) =>
              onChange({
                ...settings,
                temperature: Number(event.target.value),
              })
            }
          />
        </label>
        <details className="phase2-advanced">
          <summary>Advanced</summary>
          <label className="phase2-field">
            <span>Context messages</span>
            <input
              type="number"
              min="0"
              max="50"
              value={String(settings.context_messages ?? 10)}
              onChange={(event) =>
                onChange({
                  ...settings,
                  context_messages: Number(event.target.value),
                })
              }
            />
          </label>
          <label className="phase2-field">
            <span>Output JSON schema (optional)</span>
            <textarea
              rows={4}
              value={formatJson(settings.output_json_schema ?? {})}
              onChange={(event) => {
                try {
                  const output_json_schema: unknown = JSON.parse(
                    event.target.value,
                  );
                  if (
                    output_json_schema &&
                    typeof output_json_schema === 'object' &&
                    !Array.isArray(output_json_schema)
                  ) {
                    onChange({ ...settings, output_json_schema });
                  }
                } catch {
                  onError('Output JSON schema must be a valid JSON object.');
                }
              }}
            />
          </label>
        </details>
      </div>
    );
  }
  const schema = getSettingsSchema(entryType);
  const fields = Object.entries(schema?.properties ?? {});
  if (fields.length === 0) {
    return (
      <label className="phase2-field">
        <span>Settings (JSON)</span>
        <textarea
          rows={5}
          value={formatJson(settings)}
          onChange={(event) => {
            try {
              const nextSettings: unknown = JSON.parse(event.target.value);
              if (nextSettings && typeof nextSettings === 'object') {
                onChange(nextSettings as Record<string, unknown>);
              }
            } catch {
              // Leave the last valid settings object in place while editing.
            }
          }}
        />
        <small>Enter a JSON object matching this entry point's settings.</small>
      </label>
    );
  }

  return (
    <div className="phase2-form-grid">
      {fields.map(([key, field]) => {
        const required = schema?.required?.includes(key) ?? false;
        const value = settings[key] ?? '';
        const isSecretField =
          /api[_-]?key|secret|token|password|credential/i.test(key);
        const inputType = isSecretField
          ? 'password'
          : field.type === 'integer' || field.type === 'number'
            ? 'number'
            : field.format === 'uri'
              ? 'url'
              : field.format === 'email'
                ? 'email'
                : 'text';
        const isLongText =
          !isSecretField &&
          (field.type === 'object' ||
            key.toLowerCase().includes('prompt') ||
            key.toLowerCase().includes('documents') ||
            key.toLowerCase().includes('schema') ||
            key.toLowerCase().includes('definitions'));
        const label = field.title ?? key.replace(/_/g, ' ');
        const isJsonField = field.type === 'object' || field.type === 'array';
        const jsonText =
          typeof value === 'string' ? value : JSON.stringify(value, null, 2);

        return (
          <label className="phase2-field" key={key}>
            <span>
              {label}
              {required ? <em aria-hidden="true"> *</em> : null}
            </span>
            {field.type === 'boolean' ? (
              <input
                className="phase2-checkbox"
                type="checkbox"
                checked={value === true}
                onChange={(event) =>
                  onChange({ ...settings, [key]: event.target.checked })
                }
              />
            ) : field.enum ? (
              <select
                required={required}
                value={String(value)}
                onChange={(event) =>
                  onChange({ ...settings, [key]: event.target.value })
                }
              >
                <option value="">Choose {label.toLowerCase()}</option>
                {field.enum.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            ) : isJsonField ? (
              <textarea
                required={required}
                rows={key === 'documents' || key === 'tools' ? 6 : 4}
                value={jsonText}
                onChange={(event) => {
                  const text = event.target.value;
                  try {
                    onChange({ ...settings, [key]: JSON.parse(text) });
                  } catch {
                    onChange({ ...settings, [key]: text });
                  }
                }}
              />
            ) : isLongText ? (
              <textarea
                required={required}
                rows={key === 'documents' ? 5 : 4}
                value={String(value)}
                onChange={(event) =>
                  onChange({ ...settings, [key]: event.target.value })
                }
              />
            ) : (
              <input
                required={required}
                type={inputType}
                min={inputType === 'number' ? 0 : undefined}
                step={field.type === 'integer' ? 1 : undefined}
                value={String(value)}
                placeholder={
                  field.format === 'uri' ? 'https://example.com/api' : ''
                }
                onChange={(event) => {
                  const nextValue =
                    inputType === 'number' && event.target.value !== ''
                      ? Number(event.target.value)
                      : event.target.value;
                  onChange({ ...settings, [key]: nextValue });
                }}
              />
            )}
            {field.description && <small>{field.description}</small>}
            {required && (value === '' || value === undefined) && (
              <small className="field-hint-error">
                This field is required.
              </small>
            )}
          </label>
        );
      })}
    </div>
  );
}

export default function WorkspaceProjects({
  accessToken,
  userRole,
  userId,
  workspace,
  page,
  activeProjectId,
  onProjectOptionsChange,
  onActiveProjectChange,
}: WorkspaceProjectsProps) {
  const activePage = page ?? 'all';
  const projectDraft = readWorkspaceDraft<WorkspaceDraft['project']>(
    userId,
    workspace.id,
    'project',
  );
  const providerDraft = readWorkspaceDraft<WorkspaceDraft['provider']>(
    userId,
    workspace.id,
    'provider',
  );
  const connectorDraft = readWorkspaceDraft<WorkspaceDraft['connector']>(
    userId,
    workspace.id,
    'connector',
  );
  const [projects, setProjects] = useState<Project[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [entryTypes, setEntryTypes] = useState<EntryPointType[]>(fallbackTypes);
  const [localSelectedProjectId, setLocalSelectedProjectId] = useState('');
  const selectedProjectId = activeProjectId ?? localSelectedProjectId;
  const setSelectedProjectId = useCallback(
    (projectId: string) => {
      setLocalSelectedProjectId(projectId);
      onActiveProjectChange?.(projectId);
    },
    [onActiveProjectChange],
  );
  const [defaultProviderId, setDefaultProviderId] = useState('');
  const [chatRetentionDays, setChatRetentionDays] = useState(30);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [projectName, setProjectName] = useState(projectDraft?.name ?? '');
  const [projectDescription, setProjectDescription] = useState(
    projectDraft?.description ?? '',
  );
  const [providerName, setProviderName] = useState(providerDraft?.name ?? '');
  const [providerType, setProviderType] = useState(
    providerDraft?.type ?? 'github_models',
  );
  const [providerBaseUrl, setProviderBaseUrl] = useState(
    providerDraft?.baseUrl ?? '',
  );
  const [providerTestModel, setProviderTestModel] = useState(
    providerDraft?.model ?? '',
  );
  const [providerApiKey, setProviderApiKey] = useState('');
  const [providerRpm, setProviderRpm] = useState(providerDraft?.rpm ?? '60');
  const [providerRpd, setProviderRpd] = useState(providerDraft?.rpd ?? '1000');
  const [providerInputTokens, setProviderInputTokens] = useState(
    providerDraft?.inputTokens ?? '8192',
  );
  const [providerOutputTokens, setProviderOutputTokens] = useState(
    providerDraft?.outputTokens ?? '2048',
  );
  const [providerTestToken, setProviderTestToken] = useState('');
  const [providerTesting, setProviderTesting] = useState(false);
  const [providerTestId, setProviderTestId] = useState('');
  const [settingDefaultProviderId, setSettingDefaultProviderId] = useState('');
  const [selectedType, setSelectedType] = useState(
    connectorDraft?.selectedType ?? '',
  );
  const [selectedProviderId, setSelectedProviderId] = useState(
    connectorDraft?.providerId ?? '',
  );
  const [connectorSettings, setConnectorSettings] = useState<
    Record<string, unknown>
  >(connectorDraft?.settings ?? {});
  const [connectorApiKey, setConnectorApiKey] = useState('');
  const [connectorName, setConnectorName] = useState(
    connectorDraft?.name ?? '',
  );
  const [testInput, setTestInput] = useState(connectorDraft?.testInput ?? '');
  const [testResult, setTestResult] = useState<TestCallResult | null>(null);
  const [testFailure, setTestFailure] = useState<TestFailure | null>(null);
  const [testResultSaved, setTestResultSaved] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [overviewDatasetApproved, setOverviewDatasetApproved] = useState(false);
  const [overviewRunCompleted, setOverviewRunCompleted] = useState(false);
  const [savingProject, setSavingProject] = useState(false);
  const [savingProvider, setSavingProvider] = useState(false);
  const [testingConnector, setTestingConnector] = useState(false);
  const [savingConnector, setSavingConnector] = useState(false);
  const projectRequestLock = useRef(false);
  const providerTestLock = useRef(false);
  const providerSaveLock = useRef(false);
  const connectorTestLock = useRef(false);
  const connectorSaveLock = useRef(false);

  const enabledTypes = useMemo(
    () =>
      entryTypes.map((entryType) => ({
        ...entryType,
        implemented: entryType.implemented ?? phaseTwoTypes.has(entryType.type),
      })),
    [entryTypes],
  );
  const activeType = enabledTypes.find((item) => item.type === selectedType);
  const activeProvider = providers.find(
    (provider) => provider.id === selectedProviderId,
  );
  const currentSchema = getSettingsSchema(activeType);
  const requiredSettings = (currentSchema?.required ?? []).filter(
    (key) => key !== 'provider_id',
  );
  const requiresProvider = Boolean(
    activeType && providerEntryTypes.has(activeType.type),
  );
  const uploadRows = Array.isArray(connectorSettings.rows)
    ? connectorSettings.rows
    : [];
  const uploadReady =
    activeType?.type !== 'UPLOAD_OUTPUTS' ||
    (uploadRows.length > 0 &&
      Boolean(connectorSettings.input_field) &&
      Boolean(connectorSettings.output_field));
  const selectedModel =
    activeProvider?.default_model ?? activeProvider?.test_model ?? undefined;
  const canTest =
    Boolean(activeType) &&
    Boolean(connectorName.trim()) &&
    Boolean(testInput.trim()) &&
    uploadReady &&
    (!requiresProvider || Boolean(selectedProviderId)) &&
    requiredSettings.every((key) => {
      const value = connectorSettings[key];
      return (
        value !== undefined && value !== null && String(value).trim() !== ''
      );
    }) &&
    !testingConnector &&
    !savingConnector;
  const canTestProvider =
    Boolean(providerName.trim()) &&
    (providerType === 'ollama' ||
      (providerType === 'github_models' && Boolean(providerApiKey.trim())) ||
      (providerType === 'custom' &&
        Boolean(providerBaseUrl.trim()) &&
        Boolean(providerApiKey.trim())));

  useEffect(() => {
    if (projectName.trim() || projectDescription.trim()) {
      writeWorkspaceDraft(userId, workspace.id, 'project', {
        name: projectName,
        description: projectDescription,
      });
    } else {
      clearWorkspaceDraft(userId, workspace.id, 'project');
    }
  }, [projectDescription, projectName, userId, workspace.id]);

  useEffect(() => {
    if (
      providerName.trim() ||
      providerBaseUrl.trim() ||
      providerTestModel.trim()
    ) {
      writeWorkspaceDraft(userId, workspace.id, 'provider', {
        name: providerName,
        type: providerType,
        baseUrl: providerBaseUrl,
        model: providerTestModel,
        rpm: providerRpm,
        rpd: providerRpd,
        inputTokens: providerInputTokens,
        outputTokens: providerOutputTokens,
      });
    } else {
      clearWorkspaceDraft(userId, workspace.id, 'provider');
    }
  }, [
    providerBaseUrl,
    providerInputTokens,
    providerName,
    providerOutputTokens,
    providerRpd,
    providerRpm,
    providerTestModel,
    providerType,
    userId,
    workspace.id,
  ]);

  useEffect(() => {
    if (testResultSaved) {
      clearWorkspaceDraft(userId, workspace.id, 'connector');
      return;
    }
    writeWorkspaceDraft(userId, workspace.id, 'connector', {
      selectedType,
      providerId: selectedProviderId,
      settings: safeDraftSettings(connectorSettings),
      name: connectorName,
      testInput,
    });
  }, [
    connectorName,
    connectorSettings,
    selectedProviderId,
    selectedType,
    testInput,
    testResultSaved,
    userId,
    workspace.id,
  ]);

  const saveWorkspacePreferences = useCallback(
    async (preferences: Record<string, unknown>) => {
      await apiRequest<WorkspacePreferences>(
        makeWorkspacePath(workspace.id, '/preferences'),
        {
          method: 'PUT',
          body: JSON.stringify(preferences),
          signal: AbortSignal.timeout(15_000),
        },
        accessToken,
      );
    },
    [accessToken, workspace.id],
  );

  useEffect(() => {
    if (activePage === 'all') return;
    void saveWorkspacePreferences({ last_page: activePage }).catch(() =>
      setError('Could not save the last-page preference.'),
    );
  }, [activePage, saveWorkspacePreferences]);

  useEffect(() => {
    let isCurrent = true;
    const projectPath = makeWorkspacePath(workspace.id, '/projects');
    const providerPath = makeWorkspacePath(workspace.id, '/providers');
    const preferencesPath = makeWorkspacePath(workspace.id, '/preferences');

    async function loadWorkspaceData() {
      const [
        projectResponse,
        providerResponse,
        typeResponse,
        preferenceResponse,
      ] = await Promise.allSettled([
        apiRequest<Project[]>(projectPath, {}, accessToken),
        apiRequest<Provider[]>(providerPath, {}, accessToken),
        apiRequest<EntryPointType[]>('/entry-point-types', {}, accessToken),
        apiRequest<WorkspacePreferences>(preferencesPath, {}, accessToken),
      ]);
      if (!isCurrent) return;

      if (projectResponse.status === 'fulfilled') {
        setProjects(projectResponse.value);
        onProjectOptionsChange?.(projectResponse.value);
        const storedProjectId =
          preferenceResponse.status === 'fulfilled'
            ? preferenceResponse.value.active_project_id
            : null;
        const initialProjectId =
          projectResponse.value.find(
            (project) => project.id === storedProjectId,
          )?.id ??
          projectResponse.value[0]?.id ??
          '';
        setSelectedProjectId(initialProjectId);
        onActiveProjectChange?.(initialProjectId);
        if (initialProjectId && !storedProjectId) {
          void saveWorkspacePreferences({
            active_project_id: initialProjectId,
          }).catch(() =>
            setError('Could not save the active project preference.'),
          );
        }
      } else {
        setError(
          'Projects could not be loaded. Refresh the page to try again.',
        );
      }
      if (providerResponse.status === 'fulfilled') {
        const loadedProviders = providerResponse.value.map(safeProvider);
        setProviders(loadedProviders);
        const storedProviderId =
          preferenceResponse.status === 'fulfilled'
            ? preferenceResponse.value.default_provider_id
            : null;
        const initialProviderId =
          loadedProviders.find((provider) => provider.id === storedProviderId)
            ?.id ??
          loadedProviders[0]?.id ??
          '';
        setDefaultProviderId(initialProviderId);
        setSelectedProviderId(initialProviderId);
        if (initialProviderId && !storedProviderId) {
          void saveWorkspacePreferences({
            default_provider_id: initialProviderId,
          }).catch(() =>
            setError('Could not save the workspace default provider.'),
          );
        }
      }
      if (
        typeResponse.status === 'fulfilled' &&
        typeResponse.value.length > 0
      ) {
        const suppliedTypes = new Map(
          typeResponse.value.map((entryType) => [entryType.type, entryType]),
        );
        setEntryTypes(
          fallbackTypes.map((fallbackType) => ({
            ...fallbackType,
            ...suppliedTypes.get(fallbackType.type),
          })),
        );
        if (preferenceResponse.status === 'fulfilled') {
          const rememberedType = preferenceResponse.value.last_entry_point;
          const selectedEntryType = fallbackTypes
            .map((fallbackType) => ({
              ...fallbackType,
              ...suppliedTypes.get(fallbackType.type),
            }))
            .find(
              (entryType) =>
                entryType.type === rememberedType && entryType.implemented,
            );
          if (selectedEntryType) {
            setSelectedType(selectedEntryType.type);
            setConnectorSettings({
              ...initialSettings(selectedEntryType),
              ...(preferenceResponse.value.last_column_mapping ?? {}),
            });
          }
        }
      }
      if (preferenceResponse.status === 'fulfilled') {
        setChatRetentionDays(
          preferenceResponse.value.chat_retention_days ?? 30,
        );
      }
      setLoading(false);
    }

    void loadWorkspaceData();
    return () => {
      isCurrent = false;
    };
  }, [
    accessToken,
    onActiveProjectChange,
    onProjectOptionsChange,
    saveWorkspacePreferences,
    setSelectedProjectId,
    workspace.id,
  ]);

  async function makeDefaultProvider(providerId: string) {
    if (settingDefaultProviderId) return;
    setSettingDefaultProviderId(providerId);
    setError('');
    try {
      await saveWorkspacePreferences({ default_provider_id: providerId });
      setDefaultProviderId(providerId);
      setSelectedProviderId(providerId);
      setMessage('Workspace default provider saved.');
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'Could not save the workspace default provider.',
      );
    } finally {
      setSettingDefaultProviderId('');
    }
  }

  useEffect(() => {
    if (!selectedProjectId) return;
    let isCurrent = true;
    const path = makeWorkspacePath(
      workspace.id,
      `/projects/${encodeURIComponent(selectedProjectId)}/connectors`,
    );
    void apiRequest<Connector[]>(path, {}, accessToken)
      .then((result) => {
        if (isCurrent) setConnectors(result.map(safeConnector));
      })
      .catch(() => {
        if (isCurrent) setConnectors([]);
      });
    return () => {
      isCurrent = false;
    };
  }, [accessToken, selectedProjectId, workspace.id]);

  useEffect(() => {
    if (activePage !== 'overview' || !selectedProjectId) return;
    let isCurrent = true;
    const projectBase = makeWorkspacePath(
      workspace.id,
      `/projects/${encodeURIComponent(selectedProjectId)}`,
    );
    void Promise.all([
      apiRequest<Array<{ approved_items?: number }>>(
        `${projectBase}/datasets`,
        {},
        accessToken,
      ),
      apiRequest<Array<{ status?: string }>>(
        `${projectBase}/runs`,
        {},
        accessToken,
      ),
    ])
      .then(([datasets, runs]) => {
        if (!isCurrent) return;
        setOverviewDatasetApproved(
          datasets.some((dataset) => (dataset.approved_items ?? 0) > 0),
        );
        setOverviewRunCompleted(
          runs.some((run) => run.status?.toLowerCase() === 'completed'),
        );
      })
      .catch((reason: unknown) => {
        if (!isCurrent) return;
        setOverviewDatasetApproved(false);
        setOverviewRunCompleted(false);
        setError(
          reason instanceof Error
            ? `Overview setup status could not be loaded: ${reason.message}`
            : 'Overview setup status could not be loaded.',
        );
      });
    return () => {
      isCurrent = false;
    };
  }, [accessToken, activePage, selectedProjectId, workspace.id]);

  function updateConnectorSettings(nextSettings: Record<string, unknown>) {
    setConnectorSettings(nextSettings);
    setTestResult(null);
    setTestFailure(null);
    setTestResultSaved(false);
    setMessage('');
    setError('');
    if (selectedType === 'UPLOAD_OUTPUTS') {
      const mapping = Object.fromEntries(
        [
          'input_field',
          'output_field',
          'retrieved_contexts_field',
          'tool_calls_field',
          'latency_ms_field',
          'tokens_in_field',
          'tokens_out_field',
        ]
          .filter((key) => key in nextSettings)
          .map((key) => [key, nextSettings[key]]),
      );
      void saveWorkspacePreferences({ last_column_mapping: mapping }).catch(
        () => setError('Could not save the last column mapping.'),
      );
    }
  }

  function selectEntryPoint(nextType: string) {
    const nextEntryType = enabledTypes.find((item) => item.type === nextType);
    if (!nextEntryType?.implemented) return;
    setSelectedType(nextType);
    void saveWorkspacePreferences({ last_entry_point: nextType }).catch(() =>
      setError('Could not save the last entry-point preference.'),
    );
    setSelectedProviderId(defaultProviderId);
    setConnectorSettings(initialSettings(nextEntryType));
    setConnectorName(nextEntryType.label);
    setTestResult(null);
    setTestFailure(null);
    setTestResultSaved(false);
    setConnectorApiKey('');
    setMessage('');
    setError('');
  }

  async function handleCreateProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (projectRequestLock.current) return;
    projectRequestLock.current = true;
    setError('');
    setMessage('');
    setSavingProject(true);
    try {
      const createdProject = await apiRequest<Project>(
        makeWorkspacePath(workspace.id, '/projects'),
        {
          method: 'POST',
          body: JSON.stringify({
            name: projectName.trim(),
            description: projectDescription.trim(),
          }),
          signal: AbortSignal.timeout(20_000),
        },
        accessToken,
      );
      setProjects((current) =>
        current.some((project) => project.id === createdProject.id)
          ? current.map((project) =>
              project.id === createdProject.id ? createdProject : project,
            )
          : [...current, createdProject],
      );
      setSelectedProjectId(createdProject.id);
      onProjectOptionsChange?.([
        ...projects,
        { id: createdProject.id, name: createdProject.name },
      ]);
      onActiveProjectChange?.(createdProject.id);
      void saveWorkspacePreferences({
        active_project_id: createdProject.id,
      }).catch(() =>
        setError(
          'Project created, but the active-project preference could not be saved.',
        ),
      );
      setConnectors([]);
      setTestResult(null);
      setTestFailure(null);
      setTestResultSaved(false);
      setProjectName('');
      setProjectDescription('');
      clearWorkspaceDraft(userId, workspace.id, 'project');
      setMessage('Project created.');
    } catch (error: unknown) {
      setError(
        error instanceof Error
          ? error.message
          : 'Project could not be created. Check the details and try again.',
      );
    } finally {
      projectRequestLock.current = false;
      setSavingProject(false);
    }
  }

  async function handleCreateProvider(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (providerSaveLock.current) return;
    if (!providerTestToken) {
      setError('Test this provider successfully before saving it.');
      return;
    }
    providerSaveLock.current = true;
    setError('');
    setMessage('');
    setSavingProvider(true);
    const secret = providerApiKey;
    const providerPayload: Record<string, unknown> = {
      name: providerName.trim(),
      provider_type: providerType,
      base_url:
        providerType === 'github_models'
          ? null
          : providerBaseUrl.trim() || null,
      default_model: providerTestModel.trim() || null,
      rpm: Number(providerRpm),
      rpd: Number(providerRpd),
      max_input_tokens: Number(providerInputTokens),
      max_output_tokens: Number(providerOutputTokens),
      test_token: providerTestToken,
    };
    if (secret) providerPayload.api_key = secret;

    try {
      const createdProvider = await apiRequest<Provider>(
        makeWorkspacePath(workspace.id, '/providers'),
        {
          method: 'POST',
          body: JSON.stringify(providerPayload),
          signal: AbortSignal.timeout(20_000),
        },
        accessToken,
      );
      setProviders((current) =>
        current.some((provider) => provider.id === createdProvider.id)
          ? current.map((provider) =>
              provider.id === createdProvider.id
                ? safeProvider(createdProvider)
                : provider,
            )
          : [...current, safeProvider(createdProvider)],
      );
      setSelectedProviderId(createdProvider.id);
      if (!defaultProviderId) {
        setDefaultProviderId(createdProvider.id);
        void saveWorkspacePreferences({
          default_provider_id: createdProvider.id,
        }).catch(() =>
          setError(
            'Provider saved, but the default preference could not be saved.',
          ),
        );
      }
      setTestResult(null);
      setTestFailure(null);
      setTestResultSaved(false);
      setProviderName('');
      setProviderBaseUrl('');
      setProviderTestModel('');
      setProviderTestToken('');
      setProviderApiKey('');
      clearWorkspaceDraft(userId, workspace.id, 'provider');
      setMessage('Provider saved. Test its connection before using it.');
    } catch (error: unknown) {
      setError(
        error instanceof Error
          ? error.message
          : 'Provider could not be saved. Check the configuration and retry.',
      );
    } finally {
      providerSaveLock.current = false;
      setSavingProvider(false);
    }
  }

  async function handleTestProviderForm() {
    if (providerTestLock.current || providerTesting || !canTestProvider) return;
    providerTestLock.current = true;
    setError('');
    setMessage('');
    setProviderTestToken('');
    setProviderTesting(true);
    const payload: Record<string, unknown> = {
      name: providerName.trim(),
      provider_type: providerType,
      base_url:
        providerType === 'github_models'
          ? null
          : providerBaseUrl.trim() || null,
      default_model: providerTestModel.trim() || null,
      rpm: Number(providerRpm),
      rpd: Number(providerRpd),
      max_input_tokens: Number(providerInputTokens),
      max_output_tokens: Number(providerOutputTokens),
    };
    if (providerApiKey) payload.api_key = providerApiKey;
    try {
      const result = await apiRequest<{
        test_token: string;
        test_model?: string;
      }>(
        makeWorkspacePath(workspace.id, '/providers/test-connection'),
        {
          method: 'POST',
          body: JSON.stringify(payload),
          signal: AbortSignal.timeout(130_000),
        },
        accessToken,
      );
      setProviderTestToken(result.test_token);
      setMessage(
        result.test_model
          ? `Provider test succeeded with ${result.test_model}. Save to add it.`
          : 'Provider test succeeded. Save to add it.',
      );
    } catch (error: unknown) {
      setError(
        error instanceof Error ? error.message : 'Provider connection failed.',
      );
    } finally {
      providerTestLock.current = false;
      setProviderTesting(false);
    }
  }

  async function handleTestProvider(providerId: string) {
    setError('');
    setMessage('');
    setProviderTestId(providerId);
    try {
      const result = await apiRequest<{
        test_model?: string;
        output?: string;
      }>(
        makeWorkspacePath(
          workspace.id,
          `/providers/${encodeURIComponent(providerId)}/test-connection`,
        ),
        {
          method: 'POST',
          body: JSON.stringify({}),
          signal: AbortSignal.timeout(130_000),
        },
        accessToken,
      );
      setMessage(
        result.test_model
          ? `Provider connection successful with ${result.test_model}.`
          : 'Provider connection successful.',
      );
    } catch (error: unknown) {
      setError(
        error instanceof Error ? error.message : 'Provider connection failed.',
      );
    } finally {
      setProviderTestId('');
    }
  }

  async function handleTestConnector(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (connectorTestLock.current || !activeType || !canTest) return;
    if (!selectedProjectId) {
      setError('Select a project before testing a connector.');
      return;
    }
    if (activeType.type === 'UPLOAD_OUTPUTS') {
      const rows = connectorSettings.rows;
      if (!Array.isArray(rows) || rows.length === 0) {
        setTestFailure({
          reason: 'No file has been uploaded.',
          nextStep: 'Choose a CSV, JSON, JSONL, or XLSX file first.',
        });
        return;
      }
      if (
        !connectorSettings.input_field ||
        !connectorSettings.output_field ||
        !Object.keys(rows[0] as UploadedRow).includes(
          String(connectorSettings.input_field),
        ) ||
        !Object.keys(rows[0] as UploadedRow).includes(
          String(connectorSettings.output_field),
        )
      ) {
        setTestFailure(
          connectorFailure('Missing column mapping', activeType.type),
        );
        return;
      }
    }
    if (!testInput.trim()) {
      setTestFailure({
        reason: 'A sample input is required.',
        nextStep:
          activeType.type === 'UPLOAD_OUTPUTS'
            ? 'Enter an input that exactly matches a row in the uploaded file.'
            : 'Enter a sample input and run the test again.',
      });
      return;
    }
    connectorTestLock.current = true;
    setError('');
    setMessage('');
    setTestingConnector(true);
    setTestResult(null);
    setTestFailure(null);
    setTestResultSaved(false);
    const secretValues = [
      connectorApiKey,
      ...secretSettings(connectorSettings),
    ].filter(Boolean);
    const credentials: Record<string, string> = {};
    if (connectorApiKey) credentials.api_key = connectorApiKey;
    try {
      const payload = buildConnectorPayload(
        activeType.type,
        {
          settings: connectorSettings,
          credentials,
          provider_id: selectedProviderId || undefined,
          model: selectedModel,
          input: testInput,
        },
        currentSchema,
      );
      const result = await apiRequest<TestCallResult>(
        makeWorkspacePath(workspace.id, '/connectors/test-call'),
        {
          method: 'POST',
          body: JSON.stringify(payload),
          signal: AbortSignal.timeout(15_000),
        },
        accessToken,
      );
      if (
        activeType.type === 'HTTP_ENDPOINT' &&
        typeof result.raw_response === 'string'
      ) {
        setTestFailure({
          reason: 'The app returned a non-JSON response.',
          nextStep:
            'Make the endpoint return JSON and check that the configured answer path exists.',
          rawResponse: result.raw_response,
        });
        return;
      }
      setTestResult(scrubSecrets(result, secretValues) as TestCallResult);
      setTestResultSaved(false);
      setMessage('Test call succeeded. You can now save this connector.');
    } catch (error: unknown) {
      setTestResult(null);
      setTestFailure(connectorFailure(error, activeType.type));
    } finally {
      connectorTestLock.current = false;
      setTestingConnector(false);
    }
  }

  async function handleSaveConnector() {
    if (
      connectorSaveLock.current ||
      !activeType ||
      !selectedProjectId ||
      !testResult ||
      !connectorName.trim()
    )
      return;
    connectorSaveLock.current = true;
    setError('');
    setMessage('');
    setSavingConnector(true);
    const secret = connectorApiKey;
    const credentials: Record<string, string> = {};
    if (secret) credentials.api_key = secret;
    try {
      const payload = buildConnectorPayload(
        activeType.type,
        {
          settings: connectorSettings,
          credentials,
          provider_id: selectedProviderId || undefined,
          model: selectedModel,
          test_call_id: testResult.test_call_id,
          name: connectorName.trim(),
        },
        currentSchema,
      );
      const createdConnector = await apiRequest<Connector>(
        makeWorkspacePath(
          workspace.id,
          `/projects/${encodeURIComponent(selectedProjectId)}/connectors`,
        ),
        {
          method: 'POST',
          body: JSON.stringify(payload),
          signal: AbortSignal.timeout(15_000),
        },
        accessToken,
      );
      setConnectors((current) =>
        current.some((connector) => connector.id === createdConnector.id)
          ? current.map((connector) =>
              connector.id === createdConnector.id
                ? safeConnector(createdConnector)
                : connector,
            )
          : [...current, safeConnector(createdConnector)],
      );
      setTestResultSaved(true);
      setConnectorApiKey('');
      clearWorkspaceDraft(userId, workspace.id, 'connector');
      setConnectorSettings((current) =>
        Object.fromEntries(
          Object.entries(current).filter(
            ([key]) =>
              !/api[_-]?key|secret|token|password|credential/i.test(key),
          ),
        ),
      );
      setMessage('Connector saved.');
    } catch (error: unknown) {
      const failure = connectorFailure(error, activeType.type);
      setError(`${failure.reason} ${failure.nextStep}`);
    } finally {
      connectorSaveLock.current = false;
      setSavingConnector(false);
    }
  }

  async function handleRenameProject(project: Project) {
    const name = window.prompt('Rename project', project.name)?.trim();
    if (!name || name === project.name) return;
    setError('');
    try {
      const updated = await apiRequest<Project>(
        makeWorkspacePath(
          workspace.id,
          `/projects/${encodeURIComponent(project.id)}`,
        ),
        {
          method: 'PATCH',
          body: JSON.stringify({
            name,
            description: project.description ?? '',
          }),
        },
        accessToken,
      );
      setProjects((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      onProjectOptionsChange?.(
        projects.map((item) =>
          item.id === updated.id
            ? { id: updated.id, name: updated.name }
            : { id: item.id, name: item.name },
        ),
      );
      setMessage('Project renamed.');
    } catch (error: unknown) {
      setError(
        error instanceof Error ? error.message : 'Project rename failed.',
      );
    }
  }

  async function handleDeleteProject(project: Project) {
    if (
      !window.confirm(
        `Permanently delete "${project.name}" and its app versions, connectors, datasets, and evaluation runs? This cannot be undone.`,
      )
    )
      return;
    setError('');
    try {
      await apiRequest(
        makeWorkspacePath(
          workspace.id,
          `/projects/${encodeURIComponent(project.id)}`,
        ),
        { method: 'DELETE' },
        accessToken,
      );
      const remaining = projects.filter((item) => item.id !== project.id);
      setProjects(remaining);
      onProjectOptionsChange?.(remaining);
      if (selectedProjectId === project.id) {
        const nextProjectId = remaining[0]?.id ?? '';
        setSelectedProjectId(nextProjectId);
        onActiveProjectChange?.(nextProjectId);
        setConnectors([]);
        setTestResult(null);
        setTestFailure(null);
        setTestResultSaved(false);
      }
      setMessage('Project deleted.');
    } catch (error: unknown) {
      setError(
        error instanceof Error ? error.message : 'Project deletion failed.',
      );
    }
  }

  async function handleRenameProvider(provider: Provider) {
    const name = window.prompt('Rename provider', provider.name)?.trim();
    if (!name || name === provider.name) return;
    setError('');
    try {
      const updated = await apiRequest<Provider>(
        makeWorkspacePath(
          workspace.id,
          `/providers/${encodeURIComponent(provider.id)}`,
        ),
        { method: 'PATCH', body: JSON.stringify({ name }) },
        accessToken,
      );
      setProviders((current) =>
        current.map((item) =>
          item.id === updated.id ? safeProvider(updated) : item,
        ),
      );
      setMessage('Provider renamed.');
    } catch (error: unknown) {
      setError(
        error instanceof Error ? error.message : 'Provider rename failed.',
      );
    }
  }

  async function handleDeleteProvider(provider: Provider) {
    if (!window.confirm(`Delete provider "${provider.name}"?`)) return;
    setError('');
    try {
      await apiRequest(
        makeWorkspacePath(
          workspace.id,
          `/providers/${encodeURIComponent(provider.id)}`,
        ),
        { method: 'DELETE' },
        accessToken,
      );
      setProviders((current) =>
        current.filter((item) => item.id !== provider.id),
      );
      if (selectedProviderId === provider.id) {
        setSelectedProviderId('');
        setConnectorSettings((current) => {
          const next = { ...current };
          delete next.provider_id;
          return next;
        });
        setTestResult(null);
        setTestFailure(null);
        setTestResultSaved(false);
      }
      setMessage('Provider deleted.');
    } catch (error: unknown) {
      setError(
        error instanceof Error ? error.message : 'Provider deletion failed.',
      );
    }
  }

  async function handleRenameConnector(connector: Connector) {
    if (!connector.id || !selectedProjectId) return;
    const name = window
      .prompt(
        'Rename connector',
        connector.name ?? connector.entry_point_type ?? '',
      )
      ?.trim();
    if (!name || name === connector.name) return;
    setError('');
    try {
      const updated = await apiRequest<Connector>(
        makeWorkspacePath(
          workspace.id,
          `/projects/${encodeURIComponent(selectedProjectId)}/connectors/${encodeURIComponent(connector.id)}`,
        ),
        { method: 'PATCH', body: JSON.stringify({ name }) },
        accessToken,
      );
      setConnectors((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setMessage('Connector renamed.');
    } catch (error: unknown) {
      setError(
        error instanceof Error ? error.message : 'Connector rename failed.',
      );
    }
  }

  async function handleDeleteConnector(connector: Connector) {
    if (
      !connector.id ||
      !selectedProjectId ||
      !window.confirm(
        `Delete saved connector "${connector.name ?? connector.entry_point_type}"?`,
      )
    )
      return;
    setError('');
    try {
      await apiRequest(
        makeWorkspacePath(
          workspace.id,
          `/projects/${encodeURIComponent(selectedProjectId)}/connectors/${encodeURIComponent(connector.id)}`,
        ),
        { method: 'DELETE' },
        accessToken,
      );
      setConnectors((current) =>
        current.filter((item) => item.id !== connector.id),
      );
      setMessage('Connector deleted.');
    } catch (error: unknown) {
      setError(
        error instanceof Error ? error.message : 'Connector deletion failed.',
      );
    }
  }

  const secretInputId = 'connector-api-key';
  const providerRequiresKey = providerType !== 'ollama';
  const canManage = ['owner', 'admin'].includes(userRole.toLowerCase());

  return (
    <section
      className="phase2-workspace"
      aria-label={`${workspace.name} projects`}
    >
      <div className="phase2-heading">
        <div>
          <p className="eyebrow">
            {activePage === 'overview' && 'WORKSPACE OVERVIEW'}
            {activePage === 'providers' && 'LLM PROVIDERS'}
            {activePage === 'projects' && 'PROJECTS'}
            {activePage === 'connector' && 'PROJECT CONNECTOR'}
            {activePage === 'dataset' && 'DATASET STUDIO'}
            {activePage === 'evaluation' && 'EVALUATION RUNS'}
            {activePage === 'results' && 'RESULTS / REPORTS'}
            {activePage === 'test-chat' && 'TEST CHAT'}
            {activePage === 'settings' && 'SETTINGS'}
          </p>
          <h2>
            {activePage === 'overview' && 'Workspace overview'}
            {activePage === 'providers' && 'LLM provider setup'}
            {activePage === 'projects' && `${workspace.name} projects`}
            {activePage === 'connector' && 'Connect and test your app'}
            {activePage === 'dataset' && 'Build and review your dataset'}
            {activePage === 'evaluation' && 'Run and monitor evaluations'}
            {activePage === 'results' && 'Results and reports'}
            {activePage === 'test-chat' && 'Test your app'}
            {activePage === 'settings' && 'Workspace settings'}
          </h2>
          <p className="muted-text">
            {activePage === 'overview' &&
              'See the current setup status and next tasks.'}
            {activePage === 'providers' &&
              'Manage the models that power your evaluations.'}
            {activePage === 'projects' &&
              'Create and manage the projects in this workspace.'}
            {activePage === 'connector' &&
              'Choose a connector and validate the request format.'}
            {activePage === 'dataset' &&
              'Upload or generate curated examples before running a judge.'}
            {activePage === 'evaluation' &&
              'Launch runs and track quality across the golden dataset.'}
            {activePage === 'results' &&
              'Review verdicts, metrics, and exportable reports.'}
            {activePage === 'test-chat' &&
              'Send sample prompts to confirm the app behaves as expected.'}
            {activePage === 'settings' &&
              'Adjust workspace preferences and retention settings.'}
          </p>
        </div>
      </div>

      {(error || message) && (
        <div
          className={error ? 'phase2-alert phase2-alert-error' : 'phase2-alert'}
          role={error ? 'alert' : 'status'}
        >
          {error || message}
        </div>
      )}

      {activePage === 'overview' && (
        <section
          className="dashboard-card phase2-card setup-checklist"
          aria-label="Workspace setup checklist"
        >
          <div className="phase2-section-heading">
            <div>
              <p className="eyebrow">GETTING STARTED</p>
              <h3>Setup checklist</h3>
            </div>
            {!selectedProjectId && (
              <span className="muted-text">Choose or create a project</span>
            )}
          </div>
          <ul>
            {[
              {
                label: 'Provider saved',
                done: providers.length > 0,
                to: '/workspace/providers',
              },
              {
                label: 'Project created',
                done: projects.length > 0,
                to: '/workspace/projects',
              },
              {
                label: 'Connector tested and saved',
                done: connectors.length > 0,
                to: '/workspace/connector',
              },
              {
                label: 'Dataset approved',
                done: overviewDatasetApproved,
                to: '/workspace/dataset',
              },
              {
                label: 'Evaluation run completed',
                done: overviewRunCompleted,
                to: '/workspace/evaluation',
              },
            ].map((item) => (
              <li key={item.label}>
                <span aria-label={item.done ? 'Complete' : 'Incomplete'}>
                  {item.done ? '✓' : '○'}
                </span>
                <Link to={item.to}>{item.label}</Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {activePage === 'settings' && (
        <section
          className="dashboard-card phase2-card workspace-settings"
          aria-label="Workspace settings"
        >
          <div className="phase2-section-heading">
            <div>
              <p className="eyebrow">PRIVACY</p>
              <h3>Chat history retention</h3>
            </div>
          </div>
          <label className="phase2-field">
            <span>Delete chat history older than</span>
            <select
              value={chatRetentionDays}
              onChange={(event) => {
                const days = Number(event.target.value);
                setChatRetentionDays(days);
                void saveWorkspacePreferences({
                  chat_retention_days: days,
                }).catch(() => setError('Chat retention could not be saved.'));
              }}
            >
              {[7, 30, 90, 365].map((days) => (
                <option value={days} key={days}>
                  {days} days
                </option>
              ))}
            </select>
            <small>
              Expired conversations are removed from your account when chat
              history is opened. Each conversation is private to its owner.
            </small>
          </label>
        </section>
      )}

      <div className="phase2-top-grid">
        <section
          className="dashboard-card phase2-card"
          hidden={activePage !== 'all' && activePage !== 'projects'}
        >
          <div className="phase2-section-heading">
            <div>
              <p className="eyebrow">PROJECTS</p>
              <h3>Create a project</h3>
            </div>
            <span className="phase2-count">{projects.length}</span>
          </div>
          <form className="phase2-form-stack" onSubmit={handleCreateProject}>
            <label className="phase2-field">
              <span>Project name *</span>
              <input
                required
                value={projectName}
                onChange={(event) => {
                  setProjectName(event.target.value);
                  setError('');
                }}
                placeholder="Customer support assistant"
              />
            </label>
            <label className="phase2-field">
              <span>
                Description <small>(optional)</small>
              </span>
              <textarea
                rows={2}
                value={projectDescription}
                onChange={(event) => {
                  setProjectDescription(event.target.value);
                  setError('');
                }}
                placeholder="What are you evaluating?"
              />
            </label>
            <button
              className="primary-button"
              type="submit"
              disabled={savingProject || !projectName.trim()}
            >
              {savingProject ? 'Creating…' : 'Create project'}
            </button>
          </form>
          <div className="phase2-project-list" aria-label="Project list">
            {loading ? (
              <p className="muted-text">Loading projects…</p>
            ) : projects.length === 0 ? (
              <p className="muted-text">Your projects will appear here.</p>
            ) : (
              projects.map((project) => (
                <div className="phase2-project-entry" key={project.id}>
                  <button
                    className={`phase2-project-option ${
                      selectedProjectId === project.id ? 'selected' : ''
                    }`}
                    onClick={() => {
                      setSelectedProjectId(project.id);
                      void saveWorkspacePreferences({
                        active_project_id: project.id,
                      }).catch(() =>
                        setError(
                          'Could not save the active project preference.',
                        ),
                      );
                      setConnectors([]);
                      setTestResult(null);
                      setTestFailure(null);
                      setTestResultSaved(false);
                      setError('');
                    }}
                    type="button"
                  >
                    <span>
                      <strong>{project.name}</strong>
                      <small>
                        {project.is_duplicate
                          ? `Duplicate flagged; original name: ${project.original_name}`
                          : project.description || 'No description'}
                      </small>
                    </span>
                    <span aria-hidden="true">›</span>
                  </button>
                  {canManage && (
                    <div className="phase2-row-actions">
                      <button
                        className="secondary-button phase2-small-button"
                        type="button"
                        onClick={() => void handleRenameProject(project)}
                      >
                        Rename
                      </button>
                      <button
                        className="secondary-button phase2-small-button"
                        type="button"
                        onClick={() => void handleDeleteProject(project)}
                      >
                        Delete
                      </button>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </section>

        <section
          className="dashboard-card phase2-card"
          hidden={activePage !== 'all' && activePage !== 'providers'}
        >
          <div className="phase2-section-heading">
            <div>
              <p className="eyebrow">LLM PROVIDERS</p>
              <h3>Provider configuration</h3>
            </div>
            <span className="phase2-count">{providers.length}</span>
          </div>
          <form className="phase2-form-stack" onSubmit={handleCreateProvider}>
            <label className="phase2-field">
              <span>Provider name *</span>
              <input
                required
                value={providerName}
                onChange={(event) => {
                  setProviderName(event.target.value);
                  setProviderTestToken('');
                  setError('');
                }}
                placeholder="Team GitHub Models"
              />
            </label>
            <label className="phase2-field">
              <span>Provider *</span>
              <select
                value={providerType}
                onChange={(event) => {
                  const type = event.target.value;
                  setProviderType(type);
                  setProviderTestModel(type === 'ollama' ? 'hermes3:8b' : '');
                  setProviderTestToken('');
                  setError('');
                  if (type === 'github_models') setProviderBaseUrl('');
                  if (type === 'ollama') {
                    setProviderBaseUrl(
                      (current) =>
                        current || 'http://host.docker.internal:11434/v1',
                    );
                  }
                }}
              >
                <option value="github_models">GitHub Models</option>
                <option value="ollama">Ollama</option>
                <option value="custom">Custom OpenAI-compatible</option>
              </select>
            </label>
            {providerType !== 'github_models' && (
              <label className="phase2-field">
                <span>Base URL {providerType === 'ollama' ? '*' : ''}</span>
                <input
                  required
                  type="url"
                  value={providerBaseUrl}
                  onChange={(event) => {
                    setProviderBaseUrl(event.target.value);
                    setProviderTestToken('');
                    setError('');
                  }}
                  placeholder={
                    providerType === 'ollama'
                      ? 'http://host.docker.internal:11434/v1'
                      : 'https://api.example.com/v1'
                  }
                />
              </label>
            )}
            <label className="phase2-field">
              <span>Default model</span>
              <input
                value={providerTestModel}
                onChange={(event) => {
                  setProviderTestModel(event.target.value);
                  setProviderTestToken('');
                  setError('');
                }}
                placeholder={
                  providerType === 'ollama'
                    ? 'hermes3:8b'
                    : 'Optional; otherwise select a model per project'
                }
              />
              <small>
                Used for connection tests, generation, and default judging.
              </small>
            </label>
            {providerRequiresKey && (
              <label className="phase2-field">
                <span>API key {providerRequiresKey ? '*' : '(optional)'}</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  required={providerRequiresKey}
                  value={providerApiKey}
                  onChange={(event) => {
                    setProviderApiKey(event.target.value);
                    setProviderTestToken('');
                    setError('');
                  }}
                  placeholder="Stored securely; never shown again"
                />
              </label>
            )}
            <div className="phase2-form-grid phase2-provider-limits">
              <label className="phase2-field">
                <span>RPM</span>
                <input
                  type="number"
                  min="1"
                  required
                  value={providerRpm}
                  onChange={(event) => {
                    setProviderRpm(event.target.value);
                    setProviderTestToken('');
                    setError('');
                  }}
                />
              </label>
              <label className="phase2-field">
                <span>RPD</span>
                <input
                  type="number"
                  min="1"
                  required
                  value={providerRpd}
                  onChange={(event) => {
                    setProviderRpd(event.target.value);
                    setProviderTestToken('');
                    setError('');
                  }}
                />
              </label>
              <label className="phase2-field">
                <span>Max input tokens</span>
                <input
                  type="number"
                  min="1"
                  required
                  value={providerInputTokens}
                  onChange={(event) => {
                    setProviderInputTokens(event.target.value);
                    setProviderTestToken('');
                    setError('');
                  }}
                />
              </label>
              <label className="phase2-field">
                <span>Max output tokens</span>
                <input
                  type="number"
                  min="1"
                  required
                  value={providerOutputTokens}
                  onChange={(event) => {
                    setProviderOutputTokens(event.target.value);
                    setProviderTestToken('');
                    setError('');
                  }}
                />
              </label>
            </div>
            <div className="phase2-save-row">
              <button
                className="secondary-button"
                type="button"
                disabled={providerTesting || savingProvider || !canTestProvider}
                onClick={() => void handleTestProviderForm()}
              >
                {providerTesting ? 'Testing provider…' : 'Test connection'}
              </button>
              <button
                className="primary-button"
                type="submit"
                disabled={
                  savingProvider ||
                  providerTesting ||
                  !providerName.trim() ||
                  !providerTestToken
                }
              >
                {savingProvider ? 'Saving provider…' : 'Save provider'}
              </button>
            </div>
          </form>
          <div className="phase2-provider-list" aria-label="Saved providers">
            {providers.map((provider) => (
              <article className="phase2-provider-row" key={provider.id}>
                <div>
                  <strong>{provider.name}</strong>
                  <small>
                    {provider.is_duplicate
                      ? `Duplicate flagged; original name: ${provider.original_name}`
                      : provider.provider_type}{' '}
                    ·{' '}
                    {provider.has_api_key
                      ? 'Credentials stored securely'
                      : 'No API key'}
                  </small>
                </div>
                <div className="phase2-row-actions">
                  {defaultProviderId === provider.id ? (
                    <span className="phase2-step-tag">Workspace default</span>
                  ) : (
                    <button
                      className="secondary-button phase2-small-button"
                      type="button"
                      disabled={settingDefaultProviderId === provider.id}
                      onClick={() => void makeDefaultProvider(provider.id)}
                    >
                      {settingDefaultProviderId === provider.id
                        ? 'Saving…'
                        : 'Set as default'}
                    </button>
                  )}
                  <button
                    className="secondary-button phase2-small-button"
                    type="button"
                    disabled={providerTestId === provider.id}
                    onClick={() => void handleTestProvider(provider.id)}
                  >
                    {providerTestId === provider.id
                      ? 'Testing…'
                      : 'Test connection'}
                  </button>
                  {canManage && (
                    <>
                      <button
                        className="secondary-button phase2-small-button"
                        type="button"
                        onClick={() => void handleRenameProvider(provider)}
                      >
                        Rename
                      </button>
                      <button
                        className="secondary-button phase2-small-button"
                        type="button"
                        onClick={() => void handleDeleteProvider(provider)}
                      >
                        Delete
                      </button>
                    </>
                  )}
                </div>
              </article>
            ))}
          </div>
        </section>
      </div>

      <section
        className="dashboard-card phase2-card connector-wizard"
        hidden={activePage !== 'all' && activePage !== 'connector'}
      >
        <div className="phase2-section-heading">
          <div>
            <p className="eyebrow">PROJECT CONNECTOR</p>
            <h3>Connect and test your app</h3>
          </div>
          <span className="phase2-step-tag">TEST REQUIRED TO SAVE</span>
        </div>
        {!selectedProjectId ? (
          <p className="field-hint-error" role="alert">
            No project selected. Create a project or select one above before
            configuring a connector.
          </p>
        ) : (
          <>
            <h3 className="connector-question">
              How can GreenLit reach your application?
            </h3>
            <div className="connector-choices" aria-label="Connector options">
              {[
                {
                  type: 'UPLOAD_OUTPUTS',
                  title: "I have my app's answers in a file",
                  description:
                    'Upload the inputs and outputs you already have.',
                },
                {
                  type: 'HTTP_ENDPOINT',
                  title: 'My app runs at a URL',
                  description: 'Send a sample request to your running app.',
                },
                {
                  type: 'PROMPT_APP',
                  title: 'I only have a prompt and a model',
                  description: 'Use your saved default provider and model.',
                },
              ].map((choice) => (
                <button
                  className={`connector-choice${selectedType === choice.type ? ' selected' : ''}`}
                  type="button"
                  key={choice.type}
                  aria-pressed={selectedType === choice.type}
                  onClick={() => selectEntryPoint(choice.type)}
                >
                  <strong>{choice.title}</strong>
                  <span>{choice.description}</span>
                </button>
              ))}
            </div>
            <details className="connector-more-ways">
              <summary>More ways (coming soon)</summary>
              <div className="connector-more-grid">
                {enabledTypes
                  .filter(
                    (entryType) =>
                      ![
                        'UPLOAD_OUTPUTS',
                        'HTTP_ENDPOINT',
                        'PROMPT_APP',
                      ].includes(entryType.type),
                  )
                  .map((entryType) => (
                    <button
                      className={`connector-more-card${entryType.implemented ? ' available' : ''}`}
                      type="button"
                      key={entryType.type}
                      disabled={!entryType.implemented}
                      aria-pressed={selectedType === entryType.type}
                      onClick={() => selectEntryPoint(entryType.type)}
                    >
                      <strong>{entryType.label}</strong>
                      <span>
                        {entryType.implemented
                          ? entryType.description
                          : `${entryType.description} · Coming soon`}
                      </span>
                    </button>
                  ))}
              </div>
            </details>
            {activeType && (
              <div className="connector-config">
                <label className="phase2-field">
                  <span>Connector name *</span>
                  <input
                    required
                    value={connectorName}
                    onChange={(event) => {
                      setConnectorName(event.target.value);
                      setError('');
                    }}
                    placeholder="Name this connector"
                  />
                </label>
                <SettingsEditor
                  entryType={activeType}
                  settings={connectorSettings}
                  onChange={updateConnectorSettings}
                  onError={setError}
                />
                {activeType.type === 'HTTP_ENDPOINT' && (
                  <label className="phase2-field" htmlFor={secretInputId}>
                    <span>API key (optional)</span>
                    <input
                      id={secretInputId}
                      type="password"
                      autoComplete="new-password"
                      value={connectorApiKey}
                      onChange={(event) => {
                        setConnectorApiKey(event.target.value);
                        setTestResult(null);
                        setTestFailure(null);
                        setTestResultSaved(false);
                        setError('');
                      }}
                      placeholder="Sent only to your app; never shown again"
                    />
                  </label>
                )}
                {activeType.type === 'PROMPT_APP' && (
                  <p className="phase2-inline-note">
                    {activeProvider
                      ? `Using your saved provider: ${activeProvider.name}.`
                      : 'Set a default provider in Provider setup before testing this path.'}
                  </p>
                )}
                <form
                  className="connector-test-form"
                  onSubmit={handleTestConnector}
                >
                  <label className="phase2-field">
                    <span>
                      {activeType.type === 'UPLOAD_OUTPUTS'
                        ? 'Sample input (must match a file row)'
                        : 'Sample input'}
                    </span>
                    <textarea
                      rows={3}
                      value={testInput}
                      onChange={(event) => {
                        setTestInput(event.target.value);
                        setTestResult(null);
                        setTestFailure(null);
                        setTestResultSaved(false);
                        setError('');
                      }}
                      placeholder={
                        activeType.type === 'UPLOAD_OUTPUTS'
                          ? 'Enter the input from one uploaded row'
                          : 'Enter an example input'
                      }
                    />
                  </label>
                  <button
                    className="primary-button"
                    type="submit"
                    disabled={!canTest}
                  >
                    {testingConnector
                      ? 'Sending…'
                      : activeType.type === 'HTTP_ENDPOINT'
                        ? 'Send sample input'
                        : 'Test with sample input'}
                  </button>
                  {!connectorName.trim() && (
                    <p className="muted-text">
                      Enter a connector name to test.
                    </p>
                  )}
                  {requiresProvider && !selectedProviderId && (
                    <p className="field-hint-error" role="status">
                      A saved default provider is required for this option.
                    </p>
                  )}
                </form>
                {testFailure && (
                  <div
                    className="connector-result connector-result-failure"
                    role="alert"
                  >
                    <strong>{testFailure.reason}</strong>
                    <p>Next step: {testFailure.nextStep}</p>
                    {testFailure.rawResponse !== undefined && (
                      <details>
                        <summary>Raw response</summary>
                        <pre>{formatJson(testFailure.rawResponse)}</pre>
                      </details>
                    )}
                  </div>
                )}
                {testResult && (
                  <div
                    className="phase2-test-result"
                    role="region"
                    aria-label="Test result"
                  >
                    <div className="phase2-result-summary">
                      <span className="phase2-result-success">
                        Test succeeded
                      </span>
                      <strong>{testResult.latency_ms} ms</strong>
                    </div>
                    <div className="phase2-result-fields">
                      <div>
                        <strong>Sample input</strong>
                        <p>{testInput}</p>
                      </div>
                      <div>
                        <strong>Output</strong>
                        <p>{formatJson(traceOutput(testResult.trace))}</p>
                      </div>
                    </div>
                    {activeType.type === 'HTTP_ENDPOINT' && (
                      <details>
                        <summary>Raw response</summary>
                        <pre>{formatJson(testResult.raw_response)}</pre>
                      </details>
                    )}
                  </div>
                )}
              </div>
            )}
            <div className="phase2-save-row">
              <p className="muted-text">
                {testResult
                  ? 'The latest test passed. Save to add this connector to the project.'
                  : 'Save is disabled until a test succeeds. Run the test above to unlock it.'}
              </p>
              <button
                className="primary-button"
                type="button"
                disabled={
                  !testResult ||
                  testResultSaved ||
                  savingConnector ||
                  testingConnector ||
                  !connectorName.trim()
                }
                onClick={() => void handleSaveConnector()}
              >
                {savingConnector
                  ? 'Saving…'
                  : testResultSaved
                    ? 'Connector saved'
                    : 'Save connector'}
              </button>
            </div>
          </>
        )}
      </section>

      <section
        className="dashboard-card phase2-card"
        hidden={activePage !== 'all' && activePage !== 'connector'}
      >
        <div className="phase2-section-heading">
          <div>
            <p className="eyebrow">SAVED CONFIGURATIONS</p>
            <h3>Project connectors</h3>
          </div>
          <span className="phase2-count">{connectors.length}</span>
        </div>
        {connectors.length === 0 ? (
          <p className="muted-text">
            Select a project and save a tested connector to see it here.
          </p>
        ) : (
          <div className="phase2-saved-connectors">
            {connectors.map((connector, index) => {
              const type = enabledTypes.find(
                (entryType) => entryType.type === connector.entry_point_type,
              );
              return (
                <article
                  className="phase2-provider-row"
                  key={connector.id ?? `${connector.entry_point_type}-${index}`}
                >
                  <div>
                    <strong>
                      {connector.name ??
                        type?.label ??
                        connector.entry_point_type}
                    </strong>
                    <small>
                      {connector.entry_point_type} · settings saved securely
                    </small>
                  </div>
                  {canManage && (
                    <div className="phase2-row-actions">
                      <button
                        className="secondary-button phase2-small-button"
                        type="button"
                        onClick={() => void handleRenameConnector(connector)}
                      >
                        Rename
                      </button>
                      <button
                        className="secondary-button phase2-small-button"
                        type="button"
                        onClick={() => void handleDeleteConnector(connector)}
                      >
                        Delete
                      </button>
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </section>
      {selectedProjectId &&
        ['all', 'dataset', 'evaluation', 'results'].includes(activePage) && (
          <DatasetStudio
            key={selectedProjectId}
            accessToken={accessToken}
            workspace={workspace}
            projectId={selectedProjectId}
          />
        )}
      {activePage === 'test-chat' && (
        <ProjectTestChat
          accessToken={accessToken}
          workspace={workspace}
          projectId={selectedProjectId}
          connectorType={
            connectors[connectors.length - 1]?.entry_point_type ?? null
          }
        />
      )}
      {userRole.toLowerCase() === 'admin' && (
        <p className="phase2-admin-note">
          Admin test override is not available in this phase. A successful test
          is required to save.
        </p>
      )}
    </section>
  );
}
