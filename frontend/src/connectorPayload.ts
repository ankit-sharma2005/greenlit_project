import settingsFields from './connectorSettingsFields.json';

export interface ConnectorSettingsSchema {
  properties?: Record<string, unknown>;
}

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
