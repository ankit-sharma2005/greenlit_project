import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import { apiRequest, streamApiEvents, Workspace } from './api';

interface DatasetItem {
  id: string;
  position: number;
  input_text: string;
  reference_answer: string | null;
  reference_context: string | null;
  category: string;
  provenance: string;
  review_status: string;
  split: string;
  data: Record<string, unknown>;
}

interface DatasetVersion {
  dataset_id: string;
  dataset_name: string;
  task_type: string;
  version_id: string;
  version: number;
  content_hash: string;
  total_items: number;
  approved_items: number;
  pending_items: number;
  rejected_items: number;
  split_counts: Record<string, number>;
  category_counts: Record<string, number>;
  locked_at: string | null;
  validation_errors: Array<{ row?: number; message: string }>;
  duplicate_count: number;
  items: DatasetItem[];
}

interface AppVersion {
  id: string;
  version: number;
  connector_profile_id: string | null;
  access_level: string | null;
}

interface EvalRun {
  id: string;
  app_version_id: string;
  dataset_version_id: string;
  status: string;
  total_items: number;
  completed_items: number;
  failed_items: number;
  pause_reason: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  item_statuses?: Record<string, number>;
}

interface EvalRunItem {
  id: string;
  dataset_item_id: string;
  position: number;
  category: string;
  status: string;
  output: string | null;
  trace: Record<string, unknown>;
  scores: MetricScore[];
  error: string | null;
  attempts: number;
  completed_at: string | null;
}

interface VerdictCriteria {
  go_threshold: number;
  review_threshold: number;
  category_weights: Record<string, number>;
  hard_gates: Record<string, number>;
}

interface RunReportCategory {
  category: string;
  score: number;
  weight: number;
  metric_count: number;
}

interface RunReport {
  run_id: string;
  status: string;
  criteria: VerdictCriteria;
  verdict: {
    verdict: 'GO' | 'REVIEW' | 'NO_GO';
    score: number | null;
    summary: string;
    reasons: string[];
    categories: RunReportCategory[];
    readiness: {
      status: 'ready' | 'needs_attention';
      issues: Array<{
        component: string;
        message: string;
        run_item_id: string | null;
      }>;
    };
  };
  items: EvalRunItem[];
}

interface MetricScore {
  name: string;
  category: string;
  method: 'rule' | 'llm_judge';
  status: 'scored' | 'not_instrumented' | 'not_configured' | 'error';
  score: number | null;
  reason: string;
  judge_role: string | null;
  cache_hit: boolean;
}

interface MetricDefinition {
  name: string;
  category: string;
  description: string;
  requires: string[];
  mode: 'reference_based' | 'reference_free';
  method: 'rule' | 'llm_judge';
  rubric_version: number;
}

interface JudgeProfile {
  id: string;
  role: 'dev' | 'final' | 'secondary';
  provider_id: string;
  model: string;
  temperature: number;
  rubric_prompt: string;
  rubric_version: number;
}

interface Provider {
  id: string;
  name: string;
  provider_type: string;
  has_api_key: boolean;
}

interface DatasetStudioProps {
  accessToken: string;
  workspace: Workspace;
  projectId: string;
}

const taskTypes = ['rag', 'chatbot', 'agent', 'extraction'] as const;
const terminalStatuses = new Set(['completed', 'failed', 'cancelled']);

function pathFor(workspaceId: string, projectId: string, suffix: string) {
  return `/workspaces/${encodeURIComponent(workspaceId)}/projects/${encodeURIComponent(projectId)}${suffix}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export default function DatasetStudio({
  accessToken,
  workspace,
  projectId,
}: DatasetStudioProps) {
  const [versions, setVersions] = useState<DatasetVersion[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState('');
  const [selectedVersion, setSelectedVersion] = useState<DatasetVersion | null>(
    null,
  );
  const [appVersions, setAppVersions] = useState<AppVersion[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [selectedRun, setSelectedRun] = useState<EvalRun | null>(null);
  const [runItems, setRunItems] = useState<EvalRunItem[]>([]);
  const [runReport, setRunReport] = useState<RunReport | null>(null);
  const [criteria, setCriteria] = useState<VerdictCriteria | null>(null);
  const [metricCatalog, setMetricCatalog] = useState<MetricDefinition[]>([]);
  const [judgeProfiles, setJudgeProfiles] = useState<JudgeProfile[]>([]);
  const [judgeRole, setJudgeRole] = useState<JudgeProfile['role']>('dev');
  const [judgeProvider, setJudgeProvider] = useState('');
  const [judgeModel, setJudgeModel] = useState('');
  const [judgeRubric, setJudgeRubric] = useState('');
  const [selectedItems, setSelectedItems] = useState<string[]>([]);
  const [uploadName, setUploadName] = useState('');
  const [uploadTaskType, setUploadTaskType] =
    useState<(typeof taskTypes)[number]>('chatbot');
  const [file, setFile] = useState<File | null>(null);
  const [inputField, setInputField] = useState('input');
  const [answerField, setAnswerField] = useState('');
  const [contextField, setContextField] = useState('');
  const [categoryField, setCategoryField] = useState('');
  const [splitField, setSplitField] = useState('');
  const [template, setTemplate] = useState<(typeof taskTypes)[number]>('rag');
  const [generationName, setGenerationName] = useState('');
  const [generationCount, setGenerationCount] = useState('20');
  const [generationProvider, setGenerationProvider] = useState('');
  const [generationModel, setGenerationModel] = useState('');
  const [sourceMaterial, setSourceMaterial] = useState('');
  const [selectedAppVersion, setSelectedAppVersion] = useState('');
  const [selectedSplit, setSelectedSplit] = useState<'all' | 'dev' | 'test'>(
    'all',
  );
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const selectedProvider = providers.find(
    (provider) => provider.id === generationProvider,
  );
  const selectedRunId = selectedRun?.id;
  const selectedRunStatus = selectedRun?.status;
  const appVersionsWithConnectors = useMemo(
    () => appVersions.filter((version) => version.connector_profile_id),
    [appVersions],
  );
  const pendingItems = selectedVersion?.items.filter(
    (item) => item.review_status === 'pending',
  );

  const reload = useCallback(async () => {
    const base = pathFor(workspace.id, projectId, '');
    const [
      datasetRows,
      versionRows,
      providerRows,
      runRows,
      metricRows,
      judgeRows,
      verdictCriteria,
    ] = await Promise.all([
      apiRequest<DatasetVersion[]>(`${base}/datasets`, {}, accessToken),
      apiRequest<AppVersion[]>(`${base}/app-versions`, {}, accessToken),
      apiRequest<Provider[]>(
        `/workspaces/${encodeURIComponent(workspace.id)}/providers`,
        {},
        accessToken,
      ),
      apiRequest<EvalRun[]>(`${base}/runs`, {}, accessToken),
      apiRequest<MetricDefinition[]>(`${base}/metrics`, {}, accessToken),
      apiRequest<JudgeProfile[]>(`${base}/judge-profiles`, {}, accessToken),
      apiRequest<VerdictCriteria>(`${base}/verdict-criteria`, {}, accessToken),
    ]);
    setVersions(datasetRows);
    setAppVersions(versionRows);
    setProviders(providerRows);
    setRuns(runRows);
    setMetricCatalog(metricRows);
    setJudgeProfiles(judgeRows);
    setCriteria(verdictCriteria);
    setSelectedVersionId((current) =>
      current && datasetRows.some((row) => row.version_id === current)
        ? current
        : (datasetRows[0]?.version_id ?? ''),
    );
    setSelectedAppVersion((current) =>
      current &&
      versionRows.some(
        (version) =>
          version.id === current && version.connector_profile_id !== null,
      )
        ? current
        : (versionRows.find((version) => version.connector_profile_id)?.id ??
          ''),
    );
    setGenerationProvider((current) =>
      current && providerRows.some((provider) => provider.id === current)
        ? current
        : (providerRows[0]?.id ?? ''),
    );
    const savedJudge = judgeRows.find((profile) => profile.role === judgeRole);
    if (savedJudge) {
      setJudgeProvider(savedJudge.provider_id);
      setJudgeModel(savedJudge.model);
      setJudgeRubric(savedJudge.rubric_prompt);
    } else {
      setJudgeProvider((current) =>
        current && providerRows.some((provider) => provider.id === current)
          ? current
          : (providerRows[0]?.id ?? ''),
      );
    }
    if (runRows.length) setSelectedRun(runRows[0]);
  }, [accessToken, judgeRole, projectId, workspace.id]);

  useEffect(() => {
    let active = true;
    void Promise.resolve()
      .then(reload)
      .catch((reason: unknown) => {
        if (active)
          setError(
            reason instanceof Error
              ? reason.message
              : 'Unable to load datasets and runs.',
          );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [reload]);

  useEffect(() => {
    if (!selectedVersionId) return;
    const match = versions.find(
      (version) => version.version_id === selectedVersionId,
    );
    if (!match) return;
    let active = true;
    void apiRequest<DatasetVersion>(
      pathFor(
        workspace.id,
        projectId,
        `/datasets/${encodeURIComponent(match.dataset_id)}/versions/${match.version}`,
      ),
      {},
      accessToken,
    )
      .then((version) => {
        if (active) setSelectedVersion(version);
      })
      .catch((reason: unknown) => {
        if (active)
          setError(
            reason instanceof Error
              ? reason.message
              : 'Unable to load this dataset version.',
          );
      });
    return () => {
      active = false;
    };
  }, [accessToken, projectId, selectedVersionId, versions, workspace.id]);

  const loadRunReport = useCallback(
    async (runId: string) => {
      const report = await apiRequest<RunReport>(
        pathFor(
          workspace.id,
          projectId,
          `/runs/${encodeURIComponent(runId)}/report`,
        ),
        {},
        accessToken,
      );
      setRunReport(report);
      setRunItems(report.items);
    },
    [accessToken, projectId, workspace.id],
  );

  useEffect(() => {
    if (!selectedRunId) return;
    void Promise.resolve()
      .then(() => loadRunReport(selectedRunId))
      .catch((reason: unknown) => {
        setRunItems([]);
        setRunReport(null);
        setError(
          reason instanceof Error
            ? reason.message
            : 'Unable to load the run report.',
        );
      });
  }, [loadRunReport, selectedRunId]);

  useEffect(() => {
    if (
      !selectedRunId ||
      !selectedRunStatus ||
      terminalStatuses.has(selectedRunStatus)
    )
      return;
    const controller = new AbortController();
    const eventsPath = pathFor(
      workspace.id,
      projectId,
      `/runs/${encodeURIComponent(selectedRunId)}/events`,
    );
    void streamApiEvents<EvalRun>(
      eventsPath,
      accessToken,
      (event) => {
        setSelectedRun(event);
        setRuns((current) =>
          current.map((run) => (run.id === event.id ? event : run)),
        );
        void loadRunReport(event.id).catch((reason: unknown) => {
          if (reason instanceof Error) setError(reason.message);
        });
      },
      controller.signal,
    ).catch((reason: unknown) => {
      if (!controller.signal.aborted && reason instanceof Error)
        setError(reason.message);
    });
    return () => controller.abort();
  }, [
    accessToken,
    loadRunReport,
    projectId,
    selectedRunId,
    selectedRunStatus,
    workspace.id,
  ]);

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setError('Choose a CSV, JSON, JSONL, or XLSX file first.');
      return;
    }
    setWorking(true);
    setError('');
    setNotice('');
    const form = new FormData();
    form.set('name', uploadName.trim());
    form.set('task_type', uploadTaskType);
    const mapping = {
      input_field: inputField.trim(),
      ...(answerField.trim() && {
        reference_answer_field: answerField.trim(),
      }),
      ...(contextField.trim() && {
        reference_context_field: contextField.trim(),
      }),
      ...(categoryField.trim() && { category_field: categoryField.trim() }),
      ...(splitField.trim() && { split_field: splitField.trim() }),
    };
    form.set('column_mapping', JSON.stringify(mapping));
    form.set('file', file);
    try {
      const result = await apiRequest<DatasetVersion>(
        pathFor(workspace.id, projectId, '/datasets/upload'),
        { method: 'POST', body: form },
        accessToken,
      );
      setNotice(
        `Imported ${result.total_items} valid items. ${result.validation_errors.length} rows need correction; ${result.duplicate_count} duplicates were removed.`,
      );
      await reload();
      setSelectedVersionId(result.version_id);
      setSelectedVersion(result);
      setUploadName('');
      setFile(null);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : 'Dataset upload failed.',
      );
    } finally {
      setWorking(false);
    }
  }

  async function handleGenerate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!generationProvider) {
      setError('Add a provider before generating a dataset.');
      return;
    }
    setWorking(true);
    setError('');
    setNotice('');
    try {
      const result = await apiRequest<DatasetVersion>(
        pathFor(workspace.id, projectId, '/datasets/generate'),
        {
          method: 'POST',
          body: JSON.stringify({
            name: generationName.trim(),
            template,
            item_count: Number(generationCount),
            categories: ['normal', 'edge', 'adversarial', 'safety'],
            difficulty: 'medium',
            language: 'English',
            source_material: sourceMaterial,
            provider_id: generationProvider,
            model: generationModel.trim(),
          }),
        },
        accessToken,
      );
      setNotice(
        `Generated ${result.total_items} items. Review and approve them before using this dataset in a run.`,
      );
      await reload();
      setSelectedVersionId(result.version_id);
      setSelectedVersion(result);
      setGenerationName('');
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : 'Dataset generation failed.',
      );
    } finally {
      setWorking(false);
    }
  }

  async function reviewSelected(reviewStatus: 'approved' | 'rejected') {
    if (!selectedVersion || selectedItems.length === 0) return;
    setWorking(true);
    setError('');
    try {
      const result = await apiRequest<DatasetVersion>(
        pathFor(
          workspace.id,
          projectId,
          `/datasets/${encodeURIComponent(selectedVersion.dataset_id)}/versions/${selectedVersion.version}/review`,
        ),
        {
          method: 'POST',
          body: JSON.stringify({
            item_ids: selectedItems,
            review_status: reviewStatus,
          }),
        },
        accessToken,
      );
      setSelectedVersion(result);
      setSelectedItems([]);
      await reload();
      setSelectedVersion(result);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : 'Review update failed.',
      );
    } finally {
      setWorking(false);
    }
  }

  async function startRun(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedVersion || !selectedAppVersion) {
      setError('Choose a saved app version and a dataset version.');
      return;
    }
    setWorking(true);
    setError('');
    try {
      const run = await apiRequest<EvalRun>(
        pathFor(workspace.id, projectId, '/runs'),
        {
          method: 'POST',
          headers: { 'Idempotency-Key': crypto.randomUUID() },
          body: JSON.stringify({
            app_version_id: selectedAppVersion,
            dataset_version_id: selectedVersion.version_id,
            split: selectedSplit,
          }),
        },
        accessToken,
      );
      setSelectedRun(run);
      await reload();
      setSelectedRun(run);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : 'Run could not start.',
      );
    } finally {
      setWorking(false);
    }
  }

  async function saveVerdictCriteria(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!criteria) return;
    setWorking(true);
    setError('');
    setNotice('');
    try {
      const saved = await apiRequest<VerdictCriteria>(
        pathFor(workspace.id, projectId, '/verdict-criteria'),
        { method: 'PUT', body: JSON.stringify(criteria) },
        accessToken,
      );
      setCriteria(saved);
      setNotice('Verdict criteria saved for future evaluation runs.');
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'Verdict criteria could not be saved.',
      );
    } finally {
      setWorking(false);
    }
  }

  async function saveJudgeProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!judgeProvider) {
      setError('Choose a provider for the judge profile.');
      return;
    }
    setWorking(true);
    setError('');
    setNotice('');
    try {
      const profile = await apiRequest<JudgeProfile>(
        pathFor(workspace.id, projectId, `/judge-profiles/${judgeRole}`),
        {
          method: 'PUT',
          body: JSON.stringify({
            role: judgeRole,
            provider_id: judgeProvider,
            model: judgeModel.trim(),
            temperature: 0,
            rubric_prompt: judgeRubric,
          }),
        },
        accessToken,
      );
      setJudgeProfiles((current) => [
        ...current.filter((candidate) => candidate.role !== profile.role),
        profile,
      ]);
      setNotice(
        `${profile.role} judge saved at rubric v${profile.rubric_version}.`,
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'Judge profile could not be saved.',
      );
    } finally {
      setWorking(false);
    }
  }

  async function runAction(action: 'pause' | 'resume' | 'cancel') {
    if (!selectedRun) return;
    setError('');
    try {
      const run = await apiRequest<EvalRun>(
        pathFor(
          workspace.id,
          projectId,
          `/runs/${encodeURIComponent(selectedRun.id)}/${action}`,
        ),
        { method: 'POST' },
        accessToken,
      );
      setSelectedRun(run);
      setRuns((current) =>
        current.map((candidate) => (candidate.id === run.id ? run : candidate)),
      );
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : `Could not ${action} run.`,
      );
    }
  }

  return (
    <section
      className="dataset-studio"
      aria-label="Dataset studio and evaluation runs"
    >
      <div className="phase2-section-heading">
        <div>
          <p className="eyebrow">PHASE 3 · DATASET STUDIO</p>
          <h3>Build a golden dataset and run an evaluation</h3>
        </div>
        <span className="phase2-step-tag">HUMAN APPROVAL REQUIRED</span>
      </div>
      {(error || notice) && (
        <div
          className={error ? 'phase2-alert phase2-alert-error' : 'phase2-alert'}
          role={error ? 'alert' : 'status'}
        >
          {error || notice}
        </div>
      )}
      {loading ? (
        <p className="muted-text">Loading datasets and runs…</p>
      ) : (
        <>
          <section
            className="phase4-metric-catalog"
            aria-label="Metric library"
          >
            <strong>Metric library</strong>
            <div>
              {metricCatalog.map((metric) => (
                <span key={metric.name} title={metric.description}>
                  {metric.name} · {metric.category}
                </span>
              ))}
            </div>
          </section>
          <section className="dashboard-card phase2-card phase4-judge-card">
            <div className="phase2-section-heading">
              <div>
                <p className="eyebrow">LLM JUDGE</p>
                <h4>Configure a versioned judge profile</h4>
              </div>
              <span className="phase2-step-tag">
                {judgeProfiles.length} saved
              </span>
            </div>
            <form
              className="phase4-judge-form"
              onSubmit={(event) => void saveJudgeProfile(event)}
            >
              <label className="phase2-field">
                <span>Profile role</span>
                <select
                  value={judgeRole}
                  onChange={(event) => {
                    const role = event.target.value as JudgeProfile['role'];
                    setJudgeRole(role);
                    const profile = judgeProfiles.find(
                      (candidate) => candidate.role === role,
                    );
                    setJudgeProvider(
                      profile?.provider_id ?? providers[0]?.id ?? '',
                    );
                    setJudgeModel(profile?.model ?? '');
                    setJudgeRubric(profile?.rubric_prompt ?? '');
                  }}
                >
                  <option value="dev">Development judge</option>
                  <option value="final">Final report judge</option>
                  <option value="secondary">Secondary judge</option>
                </select>
              </label>
              <label className="phase2-field">
                <span>Provider</span>
                <select
                  required
                  value={judgeProvider}
                  onChange={(event) => setJudgeProvider(event.target.value)}
                >
                  <option value="">Choose provider</option>
                  {providers.map((provider) => (
                    <option key={provider.id} value={provider.id}>
                      {provider.name} · {provider.provider_type}
                    </option>
                  ))}
                </select>
              </label>
              <label className="phase2-field">
                <span>Judge model</span>
                <input
                  required
                  maxLength={200}
                  value={judgeModel}
                  onChange={(event) => setJudgeModel(event.target.value)}
                  placeholder="Model identifier"
                />
              </label>
              <label className="phase2-field phase4-rubric-field">
                <span>Rubric instructions</span>
                <textarea
                  maxLength={10_000}
                  value={judgeRubric}
                  onChange={(event) => setJudgeRubric(event.target.value)}
                  placeholder="Define correctness, relevance, completeness, and task-specific criteria."
                />
              </label>
              <button
                className="primary-button"
                type="submit"
                disabled={working || !judgeProvider || !judgeModel.trim()}
              >
                Save judge profile
              </button>
              {judgeProfiles
                .filter((profile) => profile.role === judgeRole)
                .map((profile) => (
                  <small key={profile.id}>
                    Saved model {profile.model} · rubric v
                    {profile.rubric_version}
                  </small>
                ))}
            </form>
          </section>
          <div className="phase3-creation-grid">
            <section className="dashboard-card phase2-card">
              <div className="phase2-section-heading">
                <div>
                  <p className="eyebrow">UPLOAD</p>
                  <h4>Import existing examples</h4>
                </div>
              </div>
              <form className="phase2-form-stack" onSubmit={handleUpload}>
                <label className="phase2-field">
                  <span>Dataset name *</span>
                  <input
                    required
                    value={uploadName}
                    onChange={(event) => setUploadName(event.target.value)}
                    placeholder="Support QA set"
                  />
                </label>
                <label className="phase2-field">
                  <span>App task *</span>
                  <select
                    value={uploadTaskType}
                    onChange={(event) =>
                      setUploadTaskType(
                        event.target.value as (typeof taskTypes)[number],
                      )
                    }
                  >
                    {taskTypes.map((task) => (
                      <option key={task} value={task}>
                        {task}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="phase2-field">
                  <span>CSV, JSON, JSONL, or XLSX file *</span>
                  <input
                    required
                    type="file"
                    accept=".csv,.json,.jsonl,.xlsx"
                    onChange={(event) =>
                      setFile(event.target.files?.[0] ?? null)
                    }
                  />
                </label>
                <div className="phase3-mapping-grid">
                  <label className="phase2-field">
                    <span>Input column *</span>
                    <input
                      required
                      value={inputField}
                      onChange={(event) => setInputField(event.target.value)}
                    />
                  </label>
                  <label className="phase2-field">
                    <span>Reference answer column</span>
                    <input
                      value={answerField}
                      onChange={(event) => setAnswerField(event.target.value)}
                    />
                  </label>
                  <label className="phase2-field">
                    <span>Reference context column</span>
                    <input
                      value={contextField}
                      onChange={(event) => setContextField(event.target.value)}
                      placeholder="Optional"
                    />
                  </label>
                  <label className="phase2-field">
                    <span>Category column</span>
                    <input
                      value={categoryField}
                      onChange={(event) => setCategoryField(event.target.value)}
                      placeholder="Optional"
                    />
                  </label>
                  <label className="phase2-field">
                    <span>Split column</span>
                    <input
                      value={splitField}
                      onChange={(event) => setSplitField(event.target.value)}
                      placeholder="Optional; otherwise stratified 80/20"
                    />
                  </label>
                </div>
                <button
                  className="primary-button"
                  type="submit"
                  disabled={working}
                >
                  {working ? 'Importing…' : 'Validate and import'}
                </button>
              </form>
            </section>

            <section className="dashboard-card phase2-card">
              <div className="phase2-section-heading">
                <div>
                  <p className="eyebrow">GENERATE</p>
                  <h4>Create test cases by app type</h4>
                </div>
              </div>
              <form className="phase2-form-stack" onSubmit={handleGenerate}>
                <label className="phase2-field">
                  <span>Dataset name *</span>
                  <input
                    required
                    value={generationName}
                    onChange={(event) => setGenerationName(event.target.value)}
                    placeholder="Generated RAG questions"
                  />
                </label>
                <div className="phase3-mapping-grid">
                  <label className="phase2-field">
                    <span>Template *</span>
                    <select
                      value={template}
                      onChange={(event) =>
                        setTemplate(
                          event.target.value as (typeof taskTypes)[number],
                        )
                      }
                    >
                      {taskTypes.map((task) => (
                        <option key={task} value={task}>
                          {task}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="phase2-field">
                    <span>Item count *</span>
                    <input
                      type="number"
                      min={1}
                      max={100}
                      value={generationCount}
                      onChange={(event) =>
                        setGenerationCount(event.target.value)
                      }
                      required
                    />
                  </label>
                </div>
                <label className="phase2-field">
                  <span>Provider and model *</span>
                  <select
                    value={generationProvider}
                    onChange={(event) =>
                      setGenerationProvider(event.target.value)
                    }
                    required
                  >
                    <option value="">Choose provider</option>
                    {providers.map((provider) => (
                      <option key={provider.id} value={provider.id}>
                        {provider.name} · {provider.provider_type}
                      </option>
                    ))}
                  </select>
                  {!selectedProvider?.has_api_key &&
                    selectedProvider?.provider_type !== 'ollama' && (
                      <small>Configure a provider credential first.</small>
                    )}
                </label>
                <label className="phase2-field">
                  <span>Model *</span>
                  <input
                    required
                    value={generationModel}
                    onChange={(event) => setGenerationModel(event.target.value)}
                    placeholder="Model identifier"
                  />
                </label>
                <label className="phase2-field">
                  <span>Source material or template instructions</span>
                  <textarea
                    rows={4}
                    value={sourceMaterial}
                    onChange={(event) => setSourceMaterial(event.target.value)}
                    placeholder="RAG: paste source passages. Other templates: describe the app behavior or schema."
                  />
                </label>
                <button
                  className="primary-button"
                  type="submit"
                  disabled={
                    working || !generationProvider || !generationModel.trim()
                  }
                >
                  {working ? 'Generating…' : 'Generate draft items'}
                </button>
              </form>
            </section>
          </div>

          <section className="dashboard-card phase2-card">
            <div className="phase2-section-heading">
              <div>
                <p className="eyebrow">APPROVAL QUEUE</p>
                <h4>Review dataset versions</h4>
              </div>
              <span className="phase2-count">{versions.length}</span>
            </div>
            {versions.length === 0 ? (
              <p className="muted-text">
                Imported and generated datasets will appear here.
              </p>
            ) : (
              <>
                <label className="phase2-field phase3-version-select">
                  <span>Dataset version</span>
                  <select
                    value={selectedVersionId}
                    onChange={(event) => {
                      setSelectedVersionId(event.target.value);
                      setSelectedItems([]);
                    }}
                  >
                    {versions.map((version) => (
                      <option
                        key={version.version_id}
                        value={version.version_id}
                      >
                        {version.dataset_name} · v{version.version} ·{' '}
                        {version.total_items} items
                      </option>
                    ))}
                  </select>
                </label>
                {selectedVersion && (
                  <>
                    <div className="phase3-dataset-summary">
                      <span>{selectedVersion.approved_items} approved</span>
                      <span>{selectedVersion.pending_items} pending</span>
                      <span>{selectedVersion.rejected_items} rejected</span>
                      <span>
                        Dev {selectedVersion.split_counts.dev ?? 0} · Test{' '}
                        {selectedVersion.split_counts.test ?? 0}
                      </span>
                      <span>
                        Coverage:{' '}
                        {Object.entries(selectedVersion.category_counts)
                          .map(([category, count]) => `${category} ${count}`)
                          .join(' · ') || 'No categories'}
                      </span>
                      {selectedVersion.locked_at && (
                        <span>Locked by a run</span>
                      )}
                      <span className="phase3-hash">
                        SHA-256 {selectedVersion.content_hash.slice(0, 16)}…
                      </span>
                    </div>
                    {selectedVersion.items.some(
                      (item) => item.provenance === 'synthetic',
                    ) && (
                      <p className="phase3-warning">
                        Synthetic examples are unverified until a human reviews
                        and approves them.
                      </p>
                    )}
                    {selectedVersion.validation_errors.length > 0 && (
                      <details className="phase3-errors">
                        <summary>
                          {selectedVersion.validation_errors.length} validation
                          issue(s)
                        </summary>
                        <ul>
                          {selectedVersion.validation_errors.map(
                            (validationError, index) => (
                              <li
                                key={`${validationError.row ?? 'row'}-${index}`}
                              >
                                {validationError.row
                                  ? `Row ${validationError.row}: `
                                  : ''}
                                {validationError.message}
                              </li>
                            ),
                          )}
                        </ul>
                      </details>
                    )}
                    <div className="phase3-review-actions">
                      <button
                        className="secondary-button"
                        type="button"
                        onClick={() =>
                          setSelectedItems(
                            pendingItems?.map((item) => item.id) ?? [],
                          )
                        }
                        disabled={
                          !pendingItems?.length ||
                          selectedVersion.locked_at !== null
                        }
                      >
                        Select all pending
                      </button>
                      <button
                        className="primary-button"
                        type="button"
                        onClick={() => void reviewSelected('approved')}
                        disabled={
                          working ||
                          selectedItems.length === 0 ||
                          selectedVersion.locked_at !== null
                        }
                      >
                        Approve selected
                      </button>
                      <button
                        className="secondary-button"
                        type="button"
                        onClick={() => void reviewSelected('rejected')}
                        disabled={
                          working ||
                          selectedItems.length === 0 ||
                          selectedVersion.locked_at !== null
                        }
                      >
                        Reject selected
                      </button>
                    </div>
                    <div className="phase3-item-list">
                      {selectedVersion.items.map((item) => (
                        <article className="phase3-item" key={item.id}>
                          {item.review_status === 'pending' && (
                            <input
                              aria-label={`Select item ${item.position}`}
                              type="checkbox"
                              checked={selectedItems.includes(item.id)}
                              onChange={(event) =>
                                setSelectedItems((current) =>
                                  event.target.checked
                                    ? [...current, item.id]
                                    : current.filter((id) => id !== item.id),
                                )
                              }
                            />
                          )}
                          <div>
                            <div className="phase3-item-meta">
                              <strong>#{item.position}</strong>
                              <span>{item.category}</span>
                              <span>{item.split}</span>
                              <span>{item.provenance}</span>
                              <span
                                className={`phase3-status ${item.review_status}`}
                              >
                                {item.review_status}
                              </span>
                            </div>
                            <p>{item.input_text}</p>
                            {item.reference_answer && (
                              <small>Reference: {item.reference_answer}</small>
                            )}
                          </div>
                        </article>
                      ))}
                    </div>
                  </>
                )}
              </>
            )}
          </section>

          <section className="dashboard-card phase2-card">
            <div className="phase2-section-heading">
              <div>
                <p className="eyebrow">EVALUATION RUN</p>
                <h4>Run approved examples against an app version</h4>
              </div>
            </div>
            <form className="phase3-run-form" onSubmit={startRun}>
              <label className="phase2-field">
                <span>Saved app version *</span>
                <select
                  required
                  value={selectedAppVersion}
                  onChange={(event) =>
                    setSelectedAppVersion(event.target.value)
                  }
                >
                  <option value="">Choose a tested connector version</option>
                  {appVersionsWithConnectors.map((version) => (
                    <option key={version.id} value={version.id}>
                      App v{version.version} · {version.access_level}
                    </option>
                  ))}
                </select>
              </label>
              <label className="phase2-field">
                <span>Dataset version *</span>
                <select
                  required
                  value={selectedVersionId}
                  onChange={(event) => setSelectedVersionId(event.target.value)}
                >
                  <option value="">Choose a dataset</option>
                  {versions.map((version) => (
                    <option
                      key={version.version_id}
                      value={version.version_id}
                      disabled={version.approved_items === 0}
                    >
                      {version.dataset_name} · v{version.version} ·{' '}
                      {version.approved_items} approved
                    </option>
                  ))}
                </select>
              </label>
              <label className="phase2-field">
                <span>Split</span>
                <select
                  value={selectedSplit}
                  onChange={(event) =>
                    setSelectedSplit(
                      event.target.value as 'all' | 'dev' | 'test',
                    )
                  }
                >
                  <option value="all">All approved</option>
                  <option value="dev">Development</option>
                  <option value="test">Test</option>
                </select>
              </label>
              <button
                className="primary-button"
                type="submit"
                disabled={
                  working ||
                  !selectedVersion?.approved_items ||
                  !selectedAppVersion
                }
              >
                Start evaluation run
              </button>
            </form>

            <section
              className="phase5-criteria"
              aria-labelledby="criteria-title"
            >
              <div className="phase2-section-heading">
                <div>
                  <p className="eyebrow">VERDICT CRITERIA</p>
                  <h5 id="criteria-title">Configure run decision rules</h5>
                </div>
                <p className="muted-text">
                  Saved criteria are snapshotted when a new run starts.
                </p>
              </div>
              {criteria ? (
                <form
                  className="phase5-criteria-form"
                  onSubmit={saveVerdictCriteria}
                >
                  <label className="phase2-field">
                    <span>GO threshold</span>
                    <input
                      type="number"
                      min="0"
                      max="1"
                      step="0.01"
                      required
                      value={criteria.go_threshold}
                      onChange={(event) =>
                        setCriteria((current) =>
                          current
                            ? {
                                ...current,
                                go_threshold: Number(event.target.value),
                              }
                            : current,
                        )
                      }
                    />
                  </label>
                  <label className="phase2-field">
                    <span>REVIEW threshold</span>
                    <input
                      type="number"
                      min="0"
                      max="1"
                      step="0.01"
                      required
                      value={criteria.review_threshold}
                      onChange={(event) =>
                        setCriteria((current) =>
                          current
                            ? {
                                ...current,
                                review_threshold: Number(event.target.value),
                              }
                            : current,
                        )
                      }
                    />
                  </label>
                  {Object.entries(criteria.category_weights).map(
                    ([category, weight]) => (
                      <label className="phase2-field" key={category}>
                        <span>{category} category weight</span>
                        <input
                          type="number"
                          min="0.01"
                          max="10"
                          step="0.1"
                          required
                          value={weight}
                          onChange={(event) =>
                            setCriteria((current) =>
                              current
                                ? {
                                    ...current,
                                    category_weights: {
                                      ...current.category_weights,
                                      [category]: Number(event.target.value),
                                    },
                                  }
                                : current,
                            )
                          }
                        />
                      </label>
                    ),
                  )}
                  <fieldset className="phase5-gates">
                    <legend>Hard gates</legend>
                    <p className="muted-text">
                      Any scored result below its gate forces NO_GO.
                    </p>
                    <div className="phase5-gate-list">
                      {metricCatalog.map((metric) => {
                        const threshold = criteria.hard_gates[metric.name];
                        return (
                          <div className="phase5-gate-row" key={metric.name}>
                            <label>
                              <input
                                type="checkbox"
                                checked={threshold !== undefined}
                                onChange={(event) =>
                                  setCriteria((current) => {
                                    if (!current) return current;
                                    const hardGates = {
                                      ...current.hard_gates,
                                    };
                                    if (event.target.checked) {
                                      hardGates[metric.name] = 0.7;
                                    } else {
                                      delete hardGates[metric.name];
                                    }
                                    return {
                                      ...current,
                                      hard_gates: hardGates,
                                    };
                                  })
                                }
                              />
                              <span>
                                {metric.name} · {metric.category}
                              </span>
                            </label>
                            {threshold !== undefined && (
                              <input
                                aria-label={`${metric.name} hard-gate threshold`}
                                type="number"
                                min="0"
                                max="1"
                                step="0.01"
                                value={threshold}
                                onChange={(event) =>
                                  setCriteria((current) =>
                                    current
                                      ? {
                                          ...current,
                                          hard_gates: {
                                            ...current.hard_gates,
                                            [metric.name]: Number(
                                              event.target.value,
                                            ),
                                          },
                                        }
                                      : current,
                                  )
                                }
                              />
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </fieldset>
                  <button
                    className="secondary-button"
                    type="submit"
                    disabled={working}
                  >
                    Save verdict criteria
                  </button>
                </form>
              ) : (
                <p className="muted-text">Loading verdict criteria…</p>
              )}
            </section>

            <div className="phase3-run-grid">
              <div className="phase3-run-history">
                <h5>Recent runs</h5>
                {runs.length === 0 ? (
                  <p className="muted-text">Runs appear here when started.</p>
                ) : (
                  runs.map((run) => (
                    <button
                      className={`phase3-run-option ${
                        selectedRun?.id === run.id ? 'selected' : ''
                      }`}
                      key={run.id}
                      type="button"
                      onClick={() => setSelectedRun(run)}
                    >
                      <span>{run.status.replace(/_/g, ' ')}</span>
                      <small>
                        {run.completed_items + run.failed_items}/
                        {run.total_items} items
                      </small>
                    </button>
                  ))
                )}
              </div>
              {selectedRun && (
                <div className="phase3-run-detail" aria-live="polite">
                  <div className="phase2-section-heading">
                    <div>
                      <p className="eyebrow">RUN PROGRESS</p>
                      <h5>{selectedRun.status.replace(/_/g, ' ')}</h5>
                    </div>
                    <span className="phase2-count">
                      {selectedRun.completed_items + selectedRun.failed_items}/
                      {selectedRun.total_items}
                    </span>
                  </div>
                  <progress
                    max={Math.max(selectedRun.total_items, 1)}
                    value={
                      selectedRun.completed_items + selectedRun.failed_items
                    }
                  />
                  {selectedRun.pause_reason === 'quota' && (
                    <p className="phase3-warning">
                      Waiting for provider quota. Resume when the quota is
                      available.
                    </p>
                  )}
                  <div className="phase3-run-actions">
                    {selectedRun.status === 'paused' ? (
                      <button
                        className="primary-button"
                        type="button"
                        onClick={() => void runAction('resume')}
                      >
                        Resume
                      </button>
                    ) : (
                      <button
                        className="secondary-button"
                        type="button"
                        onClick={() => void runAction('pause')}
                        disabled={
                          selectedRun.status !== 'running' &&
                          selectedRun.status !== 'queued'
                        }
                      >
                        Pause
                      </button>
                    )}
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={() => void runAction('cancel')}
                      disabled={terminalStatuses.has(selectedRun.status)}
                    >
                      Cancel run
                    </button>
                  </div>
                  {runReport && (
                    <section className="phase5-results">
                      <div
                        className={`phase5-verdict ${runReport.verdict.verdict.toLowerCase()}`}
                        aria-live="polite"
                      >
                        <div>
                          <p className="eyebrow">RUN VERDICT</p>
                          <h4>{runReport.verdict.verdict}</h4>
                          <p>{runReport.verdict.summary}</p>
                        </div>
                        <strong>
                          {runReport.verdict.score === null
                            ? 'No score'
                            : `${(runReport.verdict.score * 100).toFixed(1)}%`}
                        </strong>
                      </div>
                      <ul className="phase5-verdict-reasons">
                        {runReport.verdict.reasons.map((reason) => (
                          <li key={reason}>{reason}</li>
                        ))}
                      </ul>
                      <div className="phase5-result-grid">
                        <section aria-labelledby="category-results-title">
                          <h5 id="category-results-title">Category scores</h5>
                          <div className="phase5-category-cards">
                            {runReport.verdict.categories.map((category) => (
                              <article
                                className="phase5-category-card"
                                key={category.category}
                              >
                                <strong>{category.category}</strong>
                                <span>
                                  {(category.score * 100).toFixed(1)}%
                                </span>
                                <small>
                                  Weight {category.weight} ·{' '}
                                  {category.metric_count} metrics
                                </small>
                              </article>
                            ))}
                          </div>
                        </section>
                        {runReport.verdict.categories.length >= 3 && (
                          <section aria-labelledby="radar-title">
                            <h5 id="radar-title">Category radar</h5>
                            <svg
                              className="phase5-radar"
                              viewBox="0 0 220 200"
                              role="img"
                              aria-label={`Radar chart for ${runReport.verdict.categories
                                .map(
                                  (category) =>
                                    `${category.category} ${(category.score * 100).toFixed(0)} percent`,
                                )
                                .join(', ')}`}
                            >
                              {runReport.verdict.categories.map(
                                (category, index, categories) => {
                                  const angle =
                                    -Math.PI / 2 +
                                    (index * 2 * Math.PI) / categories.length;
                                  const x2 = 110 + 70 * Math.cos(angle);
                                  const y2 = 100 + 70 * Math.sin(angle);
                                  const labelX = 110 + 88 * Math.cos(angle);
                                  const labelY = 100 + 88 * Math.sin(angle);
                                  return (
                                    <g key={category.category}>
                                      <line x1="110" y1="100" x2={x2} y2={y2} />
                                      <text
                                        x={labelX}
                                        y={labelY}
                                        textAnchor="middle"
                                      >
                                        {category.category}
                                      </text>
                                    </g>
                                  );
                                },
                              )}
                              <circle cx="110" cy="100" r="70" />
                              <circle cx="110" cy="100" r="35" />
                              <polygon
                                points={runReport.verdict.categories
                                  .map((category, index, categories) => {
                                    const angle =
                                      -Math.PI / 2 +
                                      (index * 2 * Math.PI) / categories.length;
                                    return `${110 + category.score * 70 * Math.cos(angle)},${100 + category.score * 70 * Math.sin(angle)}`;
                                  })
                                  .join(' ')}
                              />
                            </svg>
                          </section>
                        )}
                      </div>
                      <section
                        className={`phase5-readiness ${runReport.verdict.readiness.status}`}
                        aria-labelledby="readiness-title"
                      >
                        <h5 id="readiness-title">Readiness Report</h5>
                        {runReport.verdict.readiness.issues.length === 0 ? (
                          <p>No failing or uninstrumented components found.</p>
                        ) : (
                          <ul>
                            {runReport.verdict.readiness.issues.map(
                              (issue, index) => (
                                <li
                                  key={`${issue.run_item_id ?? 'run'}-${issue.component}-${index}`}
                                >
                                  <strong>{issue.component}</strong>:{' '}
                                  {issue.message}
                                </li>
                              ),
                            )}
                          </ul>
                        )}
                      </section>
                    </section>
                  )}
                  <div className="phase3-item-list">
                    {runItems.map((item) => (
                      <article className="phase3-item" key={item.id}>
                        <div>
                          <div className="phase3-item-meta">
                            <strong>#{item.position}</strong>
                            <span>{item.category}</span>
                            <span className={`phase3-status ${item.status}`}>
                              {item.status}
                            </span>
                            <small>attempt {item.attempts}</small>
                          </div>
                          {item.output && <p>{item.output}</p>}
                          {item.scores.length > 0 && (
                            <ul className="phase4-score-list">
                              {item.scores.map((score) => (
                                <li key={score.name}>
                                  <strong>{score.name}</strong>
                                  {score.judge_role && (
                                    <span> · {score.judge_role}</span>
                                  )}
                                  <span>
                                    {' '}
                                    ·{' '}
                                    {score.score === null
                                      ? score.status.replace(/_/g, ' ')
                                      : score.score.toFixed(2)}
                                  </span>
                                  {score.cache_hit && <small> · cached</small>}
                                  <small> — {score.reason}</small>
                                </li>
                              ))}
                            </ul>
                          )}
                          {item.error && (
                            <p className="phase3-run-error">{item.error}</p>
                          )}
                          <details className="phase5-trace-viewer">
                            <summary>Trace waterfall and context</summary>
                            <div className="phase5-trace-columns">
                              <div>
                                <h6>Answer</h6>
                                <pre>{item.output ?? 'No answer recorded'}</pre>
                              </div>
                              <ol className="phase5-waterfall">
                                {(() => {
                                  const steps = isRecord(item.trace.steps)
                                    ? item.trace.steps
                                    : {};
                                  const stepForMetric: Record<string, string> =
                                    {
                                      retrieval_context_recall:
                                        'retrieved_chunks',
                                      tool_call_match: 'tool_calls',
                                    };
                                  const failingSteps = new Set(
                                    item.scores
                                      .filter(
                                        (entry) =>
                                          entry.status === 'scored' &&
                                          entry.score !== null &&
                                          (entry.score === 0 ||
                                            entry.score <
                                              (runReport?.criteria.hard_gates[
                                                entry.name.split(':', 1)[0]
                                              ] ?? 0)),
                                      )
                                      .map(
                                        (entry) =>
                                          stepForMetric[entry.name] ?? 'output',
                                      ),
                                  );
                                  return (
                                    <>
                                      <li
                                        className={
                                          failingSteps.has('output')
                                            ? 'failed'
                                            : ''
                                        }
                                      >
                                        <strong>application output</strong>
                                        <p>
                                          {item.output ?? 'No answer recorded'}
                                        </p>
                                      </li>
                                      {Object.entries(steps).map(
                                        ([name, value]) => (
                                          <li
                                            className={
                                              failingSteps.has(name)
                                                ? 'failed'
                                                : ''
                                            }
                                            key={name}
                                          >
                                            <strong>
                                              {name.replace(/_/g, ' ')}
                                            </strong>
                                            {name === 'retrieved_chunks' &&
                                            Array.isArray(value) ? (
                                              <ul className="phase5-chunks">
                                                {value.map((chunk, index) => (
                                                  <li key={`${name}-${index}`}>
                                                    {isRecord(chunk) &&
                                                      typeof chunk.source ===
                                                        'string' && (
                                                        <strong>
                                                          {chunk.source}
                                                        </strong>
                                                      )}
                                                    <p>
                                                      {isRecord(chunk) &&
                                                      typeof chunk.text ===
                                                        'string'
                                                        ? chunk.text
                                                        : JSON.stringify(chunk)}
                                                    </p>
                                                  </li>
                                                ))}
                                              </ul>
                                            ) : (
                                              <pre>
                                                {JSON.stringify(value, null, 2)}
                                              </pre>
                                            )}
                                          </li>
                                        ),
                                      )}
                                    </>
                                  );
                                })()}
                              </ol>
                            </div>
                          </details>
                        </div>
                      </article>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </section>
        </>
      )}
    </section>
  );
}
