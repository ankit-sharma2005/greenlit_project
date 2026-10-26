/** The "Prompt app" entry point form: system prompt, provider/model and cases. */

export interface PromptAppProviderOption {
  id: string;
  name: string;
  modelName: string;
}

export interface PromptAppDatasetOption {
  value: string;
  label: string;
}

export interface PromptAppPanelProps {
  providerOptions: PromptAppProviderOption[];
  selectedProviderId: string;
  systemPrompt: string;
  model: string;
  datasetOptions: PromptAppDatasetOption[];
  datasetVersionId: string;
  generatedCases: number;
  disabled: boolean;
  onProviderChange: (providerId: string) => void;
  onSystemPromptChange: (value: string) => void;
  onModelChange: (value: string) => void;
  onDatasetChange: (versionId: string) => void;
}

/**
 * Prompt app connector form.
 *
 * The system prompt is required; the provider and model are the ones saved in
 * Settings → Providers, and the case source is either an approved dataset or
 * cases GreenLit generates with that provider.
 */
export function PromptAppPanel({
  providerOptions,
  selectedProviderId,
  systemPrompt,
  model,
  datasetOptions,
  datasetVersionId,
  generatedCases,
  disabled,
  onProviderChange,
  onSystemPromptChange,
  onModelChange,
  onDatasetChange,
}: PromptAppPanelProps) {
  const selected = providerOptions.find((option) => option.id === selectedProviderId);

  return (
    <div style={{ marginTop: "var(--space-5)" }}>
      <label className="form__label" htmlFor="prompt-system-prompt">
        System prompt (required):
      </label>
      <textarea
        id="prompt-system-prompt"
        data-testid="prompt-system-prompt"
        rows={4}
        value={systemPrompt}
        onChange={(e) => onSystemPromptChange(e.target.value)}
        placeholder="You are a concise support assistant. Answer only from the handbook."
        disabled={disabled}
      />

      {providerOptions.length === 0 ? (
        <p className="form__hint" style={{ marginTop: "var(--space-3)" }}>
          No active model provider yet. Add one in{" "}
          <a href="/settings" data-testid="prompt-app-provider-link">
            Settings → Providers
          </a>
          , then start the test again.
        </p>
      ) : (
        <>
          <label className="form__label" htmlFor="prompt-provider-select">
            Model provider:
          </label>
          <select
            id="prompt-provider-select"
            data-testid="prompt-provider-select"
            value={selectedProviderId}
            onChange={(e) => onProviderChange(e.target.value)}
            disabled={disabled}
          >
            <option value="">Pick a provider</option>
            {providerOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {option.name}
              </option>
            ))}
          </select>

          <label className="form__label" htmlFor="prompt-app-model">
            Model:
          </label>
          <input
            id="prompt-app-model"
            data-testid="prompt-app-model"
            type="text"
            value={model}
            onChange={(e) => onModelChange(e.target.value)}
            placeholder="e.g. hermes3:8b, gpt-4o"
            disabled={disabled}
          />

          <p className="card__hint" data-testid="prompt-app-target">
            This run will use:{" "}
            {selected ? `${selected.name} · ${selected.modelName || "default model"}` : "no provider yet"}
          </p>
        </>
      )}

      <label className="form__label" htmlFor="prompt-app-dataset">
        Test cases:
      </label>
      <select
        id="prompt-app-dataset"
        data-testid="prompt-app-dataset"
        value={datasetVersionId}
        onChange={(e) => onDatasetChange(e.target.value)}
        disabled={disabled}
      >
        <option value="">Generate {generatedCases} questions with this provider</option>
        {datasetOptions.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
