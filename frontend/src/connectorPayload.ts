import settingsFields from './connectorSettingsFields.json';

export interface ConnectorSettingsSchema {
  properties?: Record<string, unknown>;
}

export interface ConnectorPayloadValues {
  settings: Record<string, unknown>;
  credentials?: Record<string, string>;
  provider_id?: string;
  model?: string;
  input?: string;
  test_call_id?: string;
  name?: string;
}

const providerEntryPoints = new Set([
  'PROMPT_APP',
  'BUILTIN_RAG_APP',
  'BUILTIN_AGENT_APP',
]);

export function buildConnectorSettings(
  entryPointType: string,
  values: Record<string, unknown>,
  schema?: ConnectorSettingsSchema,
): Record<string, unknown> {
  const declaredFields =
    settingsFields[entryPointType as keyof typeof settingsFields] ?? [];
  const schemaFields = schema?.properties
    ? Object.keys(schema.properties)
    : declaredFields;
  const allowList = new Set(
    schemaFields.filter((field) => declaredFields.includes(field)),
  );
  return Object.fromEntries(
    Object.entries(values).filter(([key]) => allowList.has(key)),
  );
}

export function buildConnectorPayload(
  entryPointType: string,
  values: ConnectorPayloadValues,
  schema?: ConnectorSettingsSchema,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    entry_point_type: entryPointType,
    settings: buildConnectorSettings(entryPointType, values.settings, schema),
  };

  if (
    entryPointType === 'HTTP_ENDPOINT' &&
    values.credentials &&
    Object.keys(values.credentials).length > 0
  ) {
    payload.credentials = values.credentials;
  }
  if (values.input !== undefined) payload.input = values.input;
  if (values.test_call_id !== undefined) {
    payload.test_call_id = values.test_call_id;
  }
  if (values.name !== undefined) payload.name = values.name;
  if (providerEntryPoints.has(entryPointType)) {
    if (values.provider_id) payload.provider_id = values.provider_id;
    if (values.model) payload.model = values.model;
  }

  return payload;
}
