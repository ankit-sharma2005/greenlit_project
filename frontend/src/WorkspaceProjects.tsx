import { FormEvent, useEffect, useMemo, useState } from 'react';
import { apiRequest, Workspace } from './api';

interface WorkspaceProjectsProps {
  accessToken: string;
  userRole: string;
  workspace: Workspace;
}

interface Project {
  id: string;
  name: string;
  description?: string | null;
}

interface Provider {
  id: string;
  name: string;
  provider_type: string;
  base_url?: string | null;
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
}

interface Connector {
  id?: string;
  entry_point_type?: string;
  settings?: Record<string, unknown>;
  created_at?: string;
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
    coming_in: 'Phase 3',
  },
  {
    type: 'GIT_REPO',
    label: 'Git repository',
    description: 'Git repository + entrypoint',
    coming_in: 'Phase 3',
  },
  {
    type: 'CLI_COMMAND',
    label: 'CLI command',
    description: 'Command-line program with an input template',
    coming_in: 'Phase 3',
  },
  {
    type: 'PROXY_MODE',
    label: 'Proxy mode',
    description: 'Point your app LLM base URL at GreenLit',
    coming_in: 'Phase 3',
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

const promptAppSchema: EntryPointType['settings_schema'] = {
  type: 'object',
  required: ['system_prompt', 'model'],
  properties: {
    system_prompt: {
      type: 'string',
      title: 'System prompt',
      description: 'Instructions sent to the model for every request.',
    },
    model: {
      type: 'string',
      title: 'Model',
      description: 'Model identifier supported by the selected provider.',
    },
    temperature: {
      type: 'number',
      title: 'Temperature',
      default: 0.2,
    },
    output_schema: {
      type: 'string',
      title: 'Output JSON schema (optional)',
      description: 'Optional JSON Schema used to describe structured output.',
    },
  },
};

const ragAppSchema: EntryPointType['settings_schema'] = {
  type: 'object',
  required: ['documents', 'prompt', 'model'],
  properties: {
    documents: {
      type: 'string',
      title: 'Documents',
      description:
        'Paste sample documents, one per line, for the built-in RAG app.',
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
    embedding_model: {
      type: 'string',
      title: 'Embedding model',
      default: 'text-embedding-3-small',
    },
    top_k: {
      type: 'integer',
      title: 'Retrieved chunks (top-k)',
      default: 4,
    },
    reranker: {
      type: 'string',
      title: 'Reranker (optional)',
    },
    prompt: {
      type: 'string',
      title: 'Answer prompt',
      description: 'Prompt used to answer using retrieved document context.',
    },
    model: {
      type: 'string',
      title: 'Model',
    },
    vector_store: {
      type: 'string',
      title: 'Vector store',
      enum: ['Chroma', 'FAISS'],
      default: 'Chroma',
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
        enum: ['POST', 'PUT'],
        default: 'POST',
      },
      headers: { type: 'string', title: 'Headers (JSON, optional)' },
      input_field: {
        type: 'string',
        title: 'Input field (optional)',
        default: 'input',
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
    required: ['model'],
    properties: {
      model: { type: 'string', title: 'Model' },
      max_steps: { type: 'integer', title: 'Maximum steps', default: 5 },
      tool_definitions: {
        type: 'string',
        title: 'Tool definitions (JSON, optional)',
      },
    },
  },
  UPLOAD_OUTPUTS: {
    type: 'object',
    required: ['sample_output'],
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
  if (!schema?.properties?.entry_point_type) return schema;

  const properties: Record<string, SettingsField> = { ...schema.properties };
  delete properties.entry_point_type;
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

function phaseLabel(entryType: EntryPointType) {
  if (entryType.coming_in !== undefined && entryType.coming_in !== null) {
    const phase = String(entryType.coming_in);
    return /^phase/i.test(phase) ? phase : `Phase ${phase}`;
  }
  return ['DOCKER_IMAGE', 'GIT_REPO', 'CLI_COMMAND', 'PROXY_MODE'].includes(
    entryType.type,
  )
    ? 'Phase 3'
    : 'Phase 4';
}

function formatJson(value: unknown) {
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}

function SettingsEditor({
  entryType,
  settings,
  onChange,
}: {
  entryType: EntryPointType;
  settings: Record<string, unknown>;
  onChange: (nextSettings: Record<string, unknown>) => void;
}) {
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

        return (
          <label className="phase2-field" key={key}>
            <span>
              {label}
              {required ? <em aria-hidden="true"> *</em> : null}
            </span>
            {field.enum ? (
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
  workspace,
}: WorkspaceProjectsProps) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [entryTypes, setEntryTypes] = useState<EntryPointType[]>(fallbackTypes);
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [projectName, setProjectName] = useState('');
  const [projectDescription, setProjectDescription] = useState('');
  const [providerName, setProviderName] = useState('');
  const [providerType, setProviderType] = useState('github_models');
  const [providerBaseUrl, setProviderBaseUrl] = useState('');
  const [providerApiKey, setProviderApiKey] = useState('');
  const [providerRpm, setProviderRpm] = useState('60');
  const [providerRpd, setProviderRpd] = useState('1000');
  const [providerInputTokens, setProviderInputTokens] = useState('8192');
  const [providerOutputTokens, setProviderOutputTokens] = useState('2048');
  const [providerTestId, setProviderTestId] = useState('');
  const [searchText, setSearchText] = useState('');
  const [selectedType, setSelectedType] = useState('');
  const [selectedProviderId, setSelectedProviderId] = useState('');
  const [connectorSettings, setConnectorSettings] = useState<
    Record<string, unknown>
  >({});
  const [connectorApiKey, setConnectorApiKey] = useState('');
  const [testInput, setTestInput] = useState('');
  const [testResult, setTestResult] = useState<TestCallResult | null>(null);
  const [testResultSaved, setTestResultSaved] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [savingProject, setSavingProject] = useState(false);
  const [savingProvider, setSavingProvider] = useState(false);
  const [testingConnector, setTestingConnector] = useState(false);
  const [savingConnector, setSavingConnector] = useState(false);

  const enabledTypes = useMemo(
    () =>
      entryTypes.map((entryType) => ({
        ...entryType,
        implemented: phaseTwoTypes.has(entryType.type),
      })),
    [entryTypes],
  );
  const filteredTypes = useMemo(() => {
    const query = searchText.trim().toLowerCase();
    return enabledTypes.filter(
      (entryType) =>
        !query ||
        entryType.label.toLowerCase().includes(query) ||
        entryType.type.toLowerCase().includes(query) ||
        entryType.description.toLowerCase().includes(query),
    );
  }, [enabledTypes, searchText]);
  const activeType = enabledTypes.find((item) => item.type === selectedType);
  const activeProvider = providers.find(
    (provider) => provider.id === selectedProviderId,
  );
  const currentSchema = getSettingsSchema(activeType);
  const requiredSettings = currentSchema?.required ?? [];
  const canTest =
    Boolean(activeType) &&
    Boolean(testInput.trim()) &&
    requiredSettings.every((key) => {
      const value = connectorSettings[key];
      return (
        value !== undefined && value !== null && String(value).trim() !== ''
      );
    }) &&
    !testingConnector &&
    !savingConnector;

  useEffect(() => {
    let isCurrent = true;
    const projectPath = makeWorkspacePath(workspace.id, '/projects');
    const providerPath = makeWorkspacePath(workspace.id, '/providers');

    async function loadWorkspaceData() {
      const [projectResponse, providerResponse, typeResponse] =
        await Promise.allSettled([
          apiRequest<Project[]>(projectPath, {}, accessToken),
          apiRequest<Provider[]>(providerPath, {}, accessToken),
          apiRequest<EntryPointType[]>('/entry-point-types', {}, accessToken),
        ]);
      if (!isCurrent) return;

      if (projectResponse.status === 'fulfilled') {
        setProjects(projectResponse.value);
        setSelectedProjectId(
          (current) => current || projectResponse.value[0]?.id || '',
        );
      } else {
        setError(
          'Projects could not be loaded. Refresh the page to try again.',
        );
      }
      if (providerResponse.status === 'fulfilled') {
        setProviders(providerResponse.value.map(safeProvider));
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
      }
      setLoading(false);
    }

    void loadWorkspaceData();
    return () => {
      isCurrent = false;
    };
  }, [accessToken, workspace.id]);

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

  function updateConnectorSettings(nextSettings: Record<string, unknown>) {
    setConnectorSettings(nextSettings);
    setTestResult(null);
    setTestResultSaved(false);
    setMessage('');
  }

  async function handleCreateProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
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
        },
        accessToken,
      );
      setProjects((current) => [...current, createdProject]);
      setSelectedProjectId(createdProject.id);
      setConnectors([]);
      setTestResult(null);
      setTestResultSaved(false);
      setProjectName('');
      setProjectDescription('');
      setMessage('Project created.');
    } catch {
      setError(
        'Project could not be created. Check the details and try again.',
      );
    } finally {
      setSavingProject(false);
    }
  }

  async function handleCreateProvider(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setMessage('');
    setSavingProvider(true);
    const secret = providerApiKey;
    const providerPayload: Record<string, unknown> = {
      name: providerName.trim(),
      provider_type: providerType,
      base_url: providerBaseUrl.trim() || null,
      rpm: Number(providerRpm),
      rpd: Number(providerRpd),
      max_input_tokens: Number(providerInputTokens),
      max_output_tokens: Number(providerOutputTokens),
    };
    if (secret) providerPayload.api_key = secret;

    try {
      const createdProvider = await apiRequest<Provider>(
        makeWorkspacePath(workspace.id, '/providers'),
        {
          method: 'POST',
          body: JSON.stringify(providerPayload),
        },
        accessToken,
      );
      setProviders((current) => [...current, safeProvider(createdProvider)]);
      setSelectedProviderId(createdProvider.id);
      setTestResult(null);
      setTestResultSaved(false);
      setProviderName('');
      setProviderBaseUrl('');
      setProviderApiKey('');
      setMessage('Provider saved. Test its connection before using it.');
    } catch {
      setProviderApiKey('');
      setError(
        'Provider could not be saved. Check the configuration and retry.',
      );
    } finally {
      setSavingProvider(false);
    }
  }

  async function handleTestProvider(providerId: string) {
    setError('');
    setMessage('');
    setProviderTestId(providerId);
    try {
      await apiRequest(
        makeWorkspacePath(
          workspace.id,
          `/providers/${encodeURIComponent(providerId)}/test-connection`,
        ),
        { method: 'POST', body: JSON.stringify({}) },
        accessToken,
      );
      setMessage('Provider connection successful.');
    } catch {
      setError(
        'Provider connection failed. Verify the provider configuration.',
      );
    } finally {
      setProviderTestId('');
    }
  }

  async function handleTestConnector(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeType || !canTest) return;
    setError('');
    setMessage('');
    setTestingConnector(true);
    setTestResultSaved(false);
    const secretValues = [
      connectorApiKey,
      ...secretSettings(connectorSettings),
    ].filter(Boolean);
    const credentials: Record<string, string> = {};
    if (connectorApiKey) credentials.api_key = connectorApiKey;
    const settings = selectedProviderId
      ? { ...connectorSettings, provider_id: selectedProviderId }
      : connectorSettings;
    try {
      const result = await apiRequest<TestCallResult>(
        makeWorkspacePath(workspace.id, '/connectors/test-call'),
        {
          method: 'POST',
          body: JSON.stringify({
            entry_point_type: activeType.type,
            settings,
            credentials,
            input: testInput,
          }),
        },
        accessToken,
      );
      setTestResult(scrubSecrets(result, secretValues) as TestCallResult);
      setTestResultSaved(false);
      setMessage('Test call succeeded. You can now save this connector.');
    } catch {
      setTestResult(null);
      setConnectorApiKey('');
      setError('Test call failed. Review the settings and try again.');
    } finally {
      setTestingConnector(false);
    }
  }

  async function handleSaveConnector() {
    if (!activeType || !selectedProjectId || !testResult) return;
    setError('');
    setMessage('');
    setSavingConnector(true);
    const secret = connectorApiKey;
    const credentials: Record<string, string> = {};
    if (secret) credentials.api_key = secret;
    const settings = selectedProviderId
      ? { ...connectorSettings, provider_id: selectedProviderId }
      : connectorSettings;
    try {
      const createdConnector = await apiRequest<Connector>(
        makeWorkspacePath(
          workspace.id,
          `/projects/${encodeURIComponent(selectedProjectId)}/connectors`,
        ),
        {
          method: 'POST',
          body: JSON.stringify({
            entry_point_type: activeType.type,
            settings,
            credentials,
            test_call_id: testResult.test_call_id,
          }),
        },
        accessToken,
      );
      setConnectors((current) => [...current, safeConnector(createdConnector)]);
      setTestResultSaved(true);
      setConnectorApiKey('');
      setConnectorSettings((current) =>
        Object.fromEntries(
          Object.entries(current).filter(
            ([key]) =>
              !/api[_-]?key|secret|token|password|credential/i.test(key),
          ),
        ),
      );
      setMessage('Connector saved.');
    } catch {
      setConnectorApiKey('');
      setTestResult(null);
      setTestResultSaved(false);
      setError('Connector could not be saved. Run a new test and try again.');
    } finally {
      setSavingConnector(false);
    }
  }

  const secretInputId = 'connector-api-key';
  const providerRequiresKey = providerType !== 'ollama';

  return (
    <section
      className="phase2-workspace"
      aria-label={`${workspace.name} projects`}
    >
      <div className="phase2-heading">
        <div>
          <p className="eyebrow">PHASE 2 · PROJECT SETUP</p>
          <h2>{workspace.name} projects</h2>
          <p className="muted-text">
            Configure an LLM provider, choose an app entry point, and verify it
            with a test call before saving.
          </p>
        </div>
        <span className="phase2-workspace-tag">{workspace.slug}</span>
      </div>

      {(error || message) && (
        <div
          className={error ? 'phase2-alert phase2-alert-error' : 'phase2-alert'}
          role={error ? 'alert' : 'status'}
        >
          {error || message}
        </div>
      )}

      <div className="phase2-top-grid">
        <section className="dashboard-card phase2-card">
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
                onChange={(event) => setProjectName(event.target.value)}
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
                onChange={(event) => setProjectDescription(event.target.value)}
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
                <button
                  className={`phase2-project-option ${
                    selectedProjectId === project.id ? 'selected' : ''
                  }`}
                  key={project.id}
                  onClick={() => {
                    setSelectedProjectId(project.id);
                    setConnectors([]);
                    setTestResult(null);
                    setTestResultSaved(false);
                  }}
                  type="button"
                >
                  <span>
                    <strong>{project.name}</strong>
                    <small>{project.description || 'No description'}</small>
                  </span>
                  <span aria-hidden="true">›</span>
                </button>
              ))
            )}
          </div>
        </section>

        <section className="dashboard-card phase2-card">
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
                onChange={(event) => setProviderName(event.target.value)}
                placeholder="Team GitHub Models"
              />
            </label>
            <label className="phase2-field">
              <span>Provider *</span>
              <select
                value={providerType}
                onChange={(event) => setProviderType(event.target.value)}
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
                  onChange={(event) => setProviderBaseUrl(event.target.value)}
                  placeholder={
                    providerType === 'ollama'
                      ? 'http://localhost:11434'
                      : 'https://api.example.com/v1'
                  }
                />
              </label>
            )}
            {providerRequiresKey && (
              <label className="phase2-field">
                <span>API key {providerRequiresKey ? '*' : '(optional)'}</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  required={providerRequiresKey}
                  value={providerApiKey}
                  onChange={(event) => setProviderApiKey(event.target.value)}
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
                  onChange={(event) => setProviderRpm(event.target.value)}
                />
              </label>
              <label className="phase2-field">
                <span>RPD</span>
                <input
                  type="number"
                  min="1"
                  required
                  value={providerRpd}
                  onChange={(event) => setProviderRpd(event.target.value)}
                />
              </label>
              <label className="phase2-field">
                <span>Max input tokens</span>
                <input
                  type="number"
                  min="1"
                  required
                  value={providerInputTokens}
                  onChange={(event) =>
                    setProviderInputTokens(event.target.value)
                  }
                />
              </label>
              <label className="phase2-field">
                <span>Max output tokens</span>
                <input
                  type="number"
                  min="1"
                  required
                  value={providerOutputTokens}
                  onChange={(event) =>
                    setProviderOutputTokens(event.target.value)
                  }
                />
              </label>
            </div>
            <button
              className="secondary-button"
              type="submit"
              disabled={savingProvider || !providerName.trim()}
            >
              {savingProvider ? 'Saving provider…' : 'Save provider'}
            </button>
          </form>
          <div className="phase2-provider-list" aria-label="Saved providers">
            {providers.map((provider) => (
              <article className="phase2-provider-row" key={provider.id}>
                <div>
                  <strong>{provider.name}</strong>
                  <small>
                    {provider.provider_type} ·{' '}
                    {provider.has_api_key ? 'API key configured' : 'No API key'}
                  </small>
                </div>
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
              </article>
            ))}
          </div>
        </section>
      </div>

      <section className="dashboard-card phase2-card connector-wizard">
        <div className="phase2-section-heading">
          <div>
            <p className="eyebrow">PROJECT CONNECTOR</p>
            <h3>Connect and test your app</h3>
          </div>
          <span className="phase2-step-tag">TEST REQUIRED TO SAVE</span>
        </div>
        {!selectedProjectId ? (
          <p className="muted-text">
            Create a project or select one above to configure its connector.
          </p>
        ) : (
          <>
            <div className="phase2-wizard-grid">
              <section className="phase2-wizard-step">
                <h4>1. Choose an entry point</h4>
                <label className="phase2-field">
                  <span>Search entry-point types</span>
                  <input
                    type="search"
                    value={searchText}
                    onChange={(event) => setSearchText(event.target.value)}
                    placeholder="Search by name or type…"
                    aria-label="Search entry-point types"
                  />
                </label>
                <label className="phase2-field">
                  <span>Entry-point type</span>
                  <select
                    size={Math.min(filteredTypes.length || 1, 8)}
                    value={selectedType}
                    onChange={(event) => {
                      const nextType = event.target.value;
                      setSelectedType(nextType);
                      setConnectorSettings(
                        initialSettings(
                          enabledTypes.find((item) => item.type === nextType),
                        ),
                      );
                      setTestResult(null);
                      setTestResultSaved(false);
                    }}
                    aria-label="Select entry-point type"
                  >
                    {filteredTypes.map((entryType) => (
                      <option
                        key={entryType.type}
                        value={entryType.type}
                        disabled={!entryType.implemented}
                      >
                        {entryType.label}{' '}
                        {!entryType.implemented
                          ? `— ${phaseLabel(entryType)}`
                          : '— Phase 2'}
                      </option>
                    ))}
                  </select>
                </label>
                {activeType && (
                  <div className="phase2-type-description">
                    <strong>{activeType.label}</strong>
                    <p>{activeType.description}</p>
                    <small>
                      {activeType.access_level
                        ? `Access: ${activeType.access_level}`
                        : 'Available in Phase 2'}
                    </small>
                  </div>
                )}

                {activeType && (
                  <div className="phase2-settings">
                    <h4>2. Configure settings</h4>
                    <SettingsEditor
                      entryType={activeType}
                      settings={connectorSettings}
                      onChange={updateConnectorSettings}
                    />
                    <label className="phase2-field" htmlFor={secretInputId}>
                      <span>Connector API key (optional)</span>
                      <input
                        id={secretInputId}
                        type="password"
                        autoComplete="new-password"
                        value={connectorApiKey}
                        onChange={(event) => {
                          setConnectorApiKey(event.target.value);
                          setTestResult(null);
                          setTestResultSaved(false);
                        }}
                        placeholder="Used for the test and cleared after save"
                      />
                    </label>
                    {providers.length > 0 && (
                      <label className="phase2-field">
                        <span>Provider (optional)</span>
                        <select
                          value={selectedProviderId}
                          onChange={(event) => {
                            setSelectedProviderId(event.target.value);
                            setTestResult(null);
                            setTestResultSaved(false);
                          }}
                        >
                          <option value="">No provider selected</option>
                          {providers.map((provider) => (
                            <option key={provider.id} value={provider.id}>
                              {provider.name} ({provider.provider_type})
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                  </div>
                )}
              </section>

              <section className="phase2-wizard-step">
                <h4>3. Run a sample test</h4>
                <form onSubmit={handleTestConnector}>
                  <label className="phase2-field">
                    <span>Sample input</span>
                    <textarea
                      required
                      rows={5}
                      value={testInput}
                      onChange={(event) => {
                        setTestInput(event.target.value);
                        setTestResult(null);
                        setTestResultSaved(false);
                      }}
                      placeholder="Ask a question or provide an example input…"
                    />
                  </label>
                  {activeProvider && (
                    <p className="phase2-inline-note">
                      Using {activeProvider.name}. Provider credentials are not
                      displayed.
                    </p>
                  )}
                  <button
                    className="primary-button"
                    type="submit"
                    disabled={!canTest}
                  >
                    {testingConnector ? 'Running test…' : 'Test call'}
                  </button>
                </form>
                {testResult && (
                  <div className="phase2-test-result" role="region">
                    <div className="phase2-result-summary">
                      <span className="phase2-result-success">
                        Test succeeded
                      </span>
                      <strong>{testResult.latency_ms} ms</strong>
                    </div>
                    <div className="phase2-result-fields">
                      <div>
                        <strong>Detected fields</strong>
                        <p>
                          {testResult.detected_fields?.length
                            ? testResult.detected_fields.join(', ')
                            : 'None reported'}
                        </p>
                      </div>
                      <div>
                        <strong>Missing fields</strong>
                        <p>
                          {testResult.missing_fields?.length
                            ? testResult.missing_fields.join(', ')
                            : 'None reported'}
                        </p>
                      </div>
                    </div>
                    <details>
                      <summary>Parsed trace</summary>
                      <pre>{formatJson(testResult.trace)}</pre>
                    </details>
                    <details>
                      <summary>Raw output</summary>
                      <pre>{formatJson(testResult.raw_response)}</pre>
                    </details>
                  </div>
                )}
              </section>
            </div>
            <div className="phase2-save-row">
              <p className="muted-text">
                {testResult
                  ? 'The latest test passed. Save to add this connector to the project.'
                  : 'Save is locked until a test call succeeds.'}
              </p>
              <button
                className="primary-button"
                type="button"
                disabled={!testResult || testResultSaved || savingConnector}
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

      <section className="dashboard-card phase2-card">
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
                    <strong>{type?.label ?? connector.entry_point_type}</strong>
                    <small>
                      {connector.entry_point_type} · settings saved securely
                    </small>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>
      {userRole.toLowerCase() === 'admin' && (
        <p className="phase2-admin-note">
          Admin test override is not available in this phase. A successful test
          is required to save.
        </p>
      )}
    </section>
  );
}
