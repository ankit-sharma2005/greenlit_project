import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "../components/Button";
import { DemoPanel } from "../components/DemoPanel";
import { McpPanel } from "../components/McpPanel";
import { PromptAppPanel } from "../components/PromptAppPanel";
import { RunProgressPanel } from "../components/RunProgressPanel";
import { SetupChecklist } from "../components/SetupChecklist";
import {
  type UploadOutputsColumnOption,
  UploadOutputsPanel,
} from "../components/UploadOutputsPanel";
import { Spinner } from "../components/Spinner";
import { TargetCheckPanel } from "../components/TargetCheckPanel";
import { WebsiteWizard } from "../components/WebsiteWizard";
import { parseCurl as parseCurlLocally } from "../lib/curl";
import { parseCurl, testConnection } from "../lib/connectors";
import { buildMcpRunPayload, type McpConfig } from "../lib/mcp";
import { ApiError } from "../lib/api";
import { listDatasets } from "../lib/datasets";
import { listProviders } from "../lib/providers";
import { fetchPreferences } from "../lib/preferences";
import {
  acceptTargetCheck,
  checkTarget,
  type TargetCheck,
  type TargetCheckRequest,
} from "../lib/targets";
import {
  cancelRun,
  getRun,
  isTerminal,
  quickTest,
  startRun,
  type Run,
  type RunCreateRequest,
  type TestType,
} from "../lib/runs";

type EntryPoint = "http_endpoint" | "mcp_server" | "prompt_app" | "upload_outputs";

interface TestTypes {
  quality: boolean;
  safety: boolean;
  operations: boolean;
}

interface DatasetOption {
  value: string;
  label: string;
}

interface ProviderOption {
  id: string;
  name: string;
  modelName: string;
}

const POLL_INTERVAL_MS = 1500;
const GENERATED_CASES = 10;
const UPLOAD_COLUMN_KNOWN: Readonly<Record<string, string>> = {
  id: "id",
  input: "input",
  output: "output",
  answer: "output",
  response: "output",
  retrieved_context: "retrieved_context",
  context: "retrieved_context",
  retrieval_context: "retrieved_context",
  latency_ms: "latency_ms",
  latency: "latency_ms",
  tokens_in: "tokens_in",
  prompt_tokens: "tokens_in",
  tokens_out: "tokens_out",
  completion_tokens: "tokens_out",
  response_tokens: "tokens_out",
};

/** The checked test types, in a stable order. */
function chosenTestTypes(types: TestTypes): TestType[] {
  const chosen: TestType[] = [];
  if (types.quality) chosen.push("quality");
  if (types.safety) chosen.push("safety");
  if (types.operations) chosen.push("operations");
  return chosen;
}

function bodyTemplateWithQuestionPath(template: string, path: string): string | null {
  const marker = "__greenlit_question_placeholder__";
  const normalized = template.replace(/\{\{?input\}?\}/g, JSON.stringify(marker));
  let body: unknown;
  try {
    body = JSON.parse(normalized);
  } catch {
    return null;
  }

  const tokens = path.match(/[^.[\]]+|\[\d+\]/g);
  if (!tokens?.length) return null;
  let current: unknown = body;
  for (const token of tokens.slice(0, -1)) {
    const key = token.startsWith("[") ? Number(token.slice(1, -1)) : token;
    if (typeof key === "number") {
      if (!Array.isArray(current) || key >= current.length) return null;
      current = current[key];
    } else {
      if (typeof current !== "object" || current === null || !(key in current)) return null;
      current = (current as Record<string, unknown>)[key];
    }
  }
  const finalToken = tokens[tokens.length - 1];
  if (!finalToken) return null;
  const finalKey = finalToken.startsWith("[")
    ? Number(finalToken.slice(1, -1))
    : finalToken;
  if (typeof finalKey === "number") {
    if (!Array.isArray(current) || finalKey >= current.length) return null;
    current[finalKey] = marker;
  } else {
    if (typeof current !== "object" || current === null || !(finalKey in current)) return null;
    (current as Record<string, unknown>)[finalKey] = marker;
  }
  return JSON.stringify(body).replaceAll(JSON.stringify(marker), "{{input}}");
}

/** Home: one page where a first-time user points GreenLit at an app and gets a verdict. */
export function NewTestPage() {
  const [connector, setConnector] = useState<EntryPoint>("http_endpoint");
  const [url, setUrl] = useState("");
  const [curlText, setCurlText] = useState("");
  const [showCurl, setShowCurl] = useState(false);
  const [curlNotice, setCurlNotice] = useState<string | null>(null);
  // Header values and cookies stay encrypted on the server: only the blob comes back.
  const [curlSecret, setCurlSecret] = useState("");
  const [curlHeaderNames, setCurlHeaderNames] = useState<string[]>([]);
  const [runsOnMyComputer, setRunsOnMyComputer] = useState(false);
  // Testing an app we do not host needs the owner's permission, recorded with the run.
  const [permissionConfirmed, setPermissionConfirmed] = useState(false);
  const [permissionReference, setPermissionReference] = useState("");
  // Attack probes against someone else's app need their own, separate yes.
  const [safetyAttacksConfirmed, setSafetyAttacksConfirmed] = useState(false);
  // Polite-rate defaults: a real company chatbot must not be hammered.
  const [maxConcurrency, setMaxConcurrency] = useState(1);
  const [minDelayMs, setMinDelayMs] = useState(500);
  const [maxRetries, setMaxRetries] = useState(3);
  // Run caps (quirk 14): empty means "no cap" for cases and tokens.
  const [maxCases, setMaxCases] = useState("");
  const [maxDurationSeconds, setMaxDurationSeconds] = useState("1800");
  const [maxTotalTokens, setMaxTotalTokens] = useState("");
  const [responseFormat, setResponseFormat] = useState<"json" | "sse" | "ndjson" | "text">("json");
  const [streamContentPath, setStreamContentPath] = useState("");
  const [testTypes, setTestTypes] = useState<TestTypes>({
    quality: true,
    safety: true,
    operations: true,
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [datasetOptions, setDatasetOptions] = useState<DatasetOption[]>([]);
  const [datasetVersionId, setDatasetVersionId] = useState("");
  const [activeRun, setActiveRun] = useState<Run | null>(null);
  const [startingRun, setStartingRun] = useState(false);
  const [startingSmoke, setStartingSmoke] = useState(false);
  // The accepted check that unlocks a full run against a remote target.
  const [targetCheckId, setTargetCheckId] = useState<string | null>(null);
  // The MCP target: its URL, the chosen tool and the encrypted header blob.
  const [mcpConfig, setMcpConfig] = useState<McpConfig>({
    url: "",
    tool: "",
    questionArg: "",
    extraArgs: "",
    headersSecret: null,
    headerNames: [],
  });
  const [runError, setRunError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [providerOptions, setProviderOptions] = useState<ProviderOption[]>([]);
  const [selectedProviderId, setSelectedProviderId] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [promptAppModel, setPromptAppModel] = useState("");
  const [promptDatasetId, setPromptDatasetId] = useState("");

  // Fill the model-under-test fields from the account's saved default. Anything
  // already typed wins, so this is a default and never an override.
  useEffect(() => {
    let active = true;
    fetchPreferences()
      .then((preferences) => {
        if (!active || !preferences.target) return;
        const saved = preferences.target;
        setSelectedProviderId((current) => current || saved.provider_id);
        setPromptAppModel((current) => current || saved.model);
      })
      .catch(() => {
        /* No saved default; the fields stay as they are. */
      });
    return () => {
      active = false;
    };
  }, []);

  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadFileName, setUploadFileName] = useState("");
  const [uploadColumns, setUploadColumns] = useState<UploadOutputsColumnOption[]>([]);
  const [uploadInputColumn, setUploadInputColumn] = useState("");
  const [uploadOutputColumn, setUploadOutputColumn] = useState("");
  const [uploadIdColumn, setUploadIdColumn] = useState("");
  const [uploadContextColumn, setUploadContextColumn] = useState("");
  const [uploadLatencyColumn, setUploadLatencyColumn] = useState("");
  const [uploadTokensInColumn, setUploadTokensInColumn] = useState("");
  const [uploadTokensOutColumn, setUploadTokensOutColumn] = useState("");
  const [uploadDatasetVersionId, setUploadDatasetVersionId] = useState("");
  const [uploadConnectorStatus, setUploadConnectorStatus] = useState<
    "idle" | "loading" | "ok" | "error"
  >("idle");
  const [uploadConnectorMessage, setUploadConnectorMessage] = useState("");

  const [detectResult, setDetectResult] = useState<
    import("../lib/connectors").ConnectTestResponse | null
  >(null);
  const [answerPath, setAnswerPath] = useState("");
  const [websiteWizard, setWebsiteWizard] = useState(false);
  const [websiteCurl, setWebsiteCurl] = useState("");
  const [websiteMessage, setWebsiteMessage] = useState("");
  const [websiteParsed, setWebsiteParsed] = useState<
    | {
        method: string;
        url: string;
        body_template: string;
        question_path: string | null;
        headers_secret: string | null;
        header_names: string[];
      }
    | null
  >(null);
  const [websiteCheck, setWebsiteCheck] = useState<TargetCheck | null>(null);
  const [websiteChecking, setWebsiteChecking] = useState(false);
  const [websiteError, setWebsiteError] = useState<string | null>(null);
  const [websiteSelectedPath, setWebsiteSelectedPath] = useState("");
  // The caps sent with every run; an empty box means "no cap", not zero.
  const runCaps = useMemo(
    () => ({
      max_cases: maxCases.trim() ? Number(maxCases) : undefined,
      max_duration_seconds: Number(maxDurationSeconds) || undefined,
      max_total_tokens: maxTotalTokens.trim() ? Number(maxTotalTokens) : undefined,
    }),
    [maxCases, maxDurationSeconds, maxTotalTokens],
  );

  // The exact connector settings the check sends: the same ones a run uses.
  const checkRequest = useMemo<TargetCheckRequest | null>(() => {
    if (connector === "mcp_server") {
      const payload = buildMcpRunPayload({
        config: mcpConfig,
        allowPrivate: runsOnMyComputer,
        permissionConfirmed,
        permissionReference,
        maxRetries,
      });
      if (!payload) return null;
      return {
        entry_point: "mcp_server",
        target: payload.target ?? "",
        dataset_version_id: datasetVersionId || undefined,
        mcp_tool: payload.mcp_tool,
        mcp_question_arg: payload.mcp_question_arg,
        mcp_extra_args: payload.mcp_extra_args,
        headers_secret: payload.headers_secret,
        header_names: payload.header_names,
        timeout_seconds: 60,
        allow_private_targets: runsOnMyComputer,
        permission_confirmed: payload.permission_confirmed,
        permission_reference: payload.permission_reference,
        max_retries: maxRetries,
      };
    }
    if (connector !== "http_endpoint" || !detectResult) return null;
    return {
      target: url.trim(),
      dataset_version_id: datasetVersionId || undefined,
      method: "POST",
      body_template: detectResult.detected_request_shape || '{"question": {{input}}}',
      headers_secret: curlSecret || undefined,
      header_names: curlHeaderNames.length > 0 ? curlHeaderNames : undefined,
      answer_path: answerPath || detectResult.detected_answer_path || undefined,
      context_path: detectResult.detected_context_path || undefined,
      timeout_seconds: 60,
      allow_private_targets: runsOnMyComputer,
      permission_confirmed: !runsOnMyComputer && permissionConfirmed,
      permission_reference: !runsOnMyComputer ? permissionReference.trim() || undefined : undefined,
      safety_attacks_confirmed: !runsOnMyComputer && safetyAttacksConfirmed,
      max_concurrency: maxConcurrency,
      min_delay_ms: minDelayMs,
      max_retries: maxRetries,
      response_format: responseFormat,
      stream_content_path: streamContentPath.trim() || undefined,
    };
  }, [
    answerPath,
    connector,
    curlHeaderNames,
    curlSecret,
    datasetVersionId,
    detectResult,
    maxConcurrency,
    maxRetries,
    mcpConfig,
    minDelayMs,
    permissionConfirmed,
    permissionReference,
    responseFormat,
    runsOnMyComputer,
    safetyAttacksConfirmed,
    streamContentPath,
    url,
  ]);

  const handleCheckAccepted = useCallback((checkId: string | null) => {
    setTargetCheckId(checkId);
  }, []);

  const runWebsiteCheck = useCallback(async (selectedPath?: string) => {
    setWebsiteError(null);
    if (!websiteMessage.trim()) {
      setWebsiteError("Type the exact message you sent to the chatbot.");
      return;
    }
    if (!permissionConfirmed || !permissionReference.trim()) {
      setWebsiteError("Confirm permission and enter its reference before reading the website.");
      return;
    }

    let parsed = websiteParsed;
    if (websiteCurl.trim()) {
      const local = parseCurlLocally(websiteCurl);
      if (!local) {
        setWebsiteError(
          "That does not look like a cURL command with a URL. Paste the full command, starting with “curl”.",
        );
        return;
      }
      try {
        const imported = await parseCurl(websiteCurl);
        setWebsiteCurl("");
        const explicitMethod = websiteCurl.match(
          /(?:^|\s)(?:-X|--request)\s+["']?([^\s"']+)/i,
        )?.[1];
        const importedMethod = explicitMethod?.toUpperCase() ?? imported.method.toUpperCase();
        if (importedMethod !== "POST") {
          setWebsiteError(
            `This request uses method ${importedMethod}. GreenLit sends POST today.`,
          );
          return;
        }
        if (!/(?:^|\s)(?:-d|--data(?:-raw|-binary|-ascii)?)(?:\s|$)/i.test(websiteCurl)) {
          setWebsiteError("Only POST requests with a JSON request body are supported.");
          return;
        }
        const bodyTemplate = imported.body_template || '{"question": {{input}}}';
        try {
          JSON.parse(bodyTemplate.replace(/\{\{?input\}?\}/g, '"sample"'));
        } catch {
          setWebsiteError("Only POST requests with a JSON request body are supported.");
          return;
        }
        parsed = {
          method: imported.method,
          url: imported.url,
          body_template: bodyTemplate,
          question_path: null,
          headers_secret: imported.headers_secret,
          header_names: imported.header_names,
        };
        setWebsiteParsed(parsed);
        setUrl(imported.url);
        setCurlSecret(imported.headers_secret ?? "");
        setCurlHeaderNames(imported.header_names);
        setResponseFormat("json");
        setAnswerPath("");
        setWebsiteSelectedPath("");
        setDetectResult({
          success: true,
          message: "Website request imported",
          detected_answer_path: null,
          detected_context_path: null,
          detected_request_shape: bodyTemplate,
        });
      } catch (caught) {
        setWebsiteError(
          caught instanceof ApiError
            ? caught.message
            : `Could not import the cURL request from ${local.url}.`,
        );
        return;
      }
    }
    if (!parsed) {
      setWebsiteError("Paste and read a cURL request first.");
      return;
    }

    setWebsiteChecking(true);
    setWebsiteCheck(null);
    handleCheckAccepted(null);
    try {
      const result = await checkTarget({
        target: parsed.url,
        method: "POST",
        body_template: parsed.body_template,
        headers_secret: parsed.headers_secret ?? undefined,
        header_names: parsed.header_names,
        sample_question: websiteMessage,
        answer_path: selectedPath || undefined,
        permission_confirmed: true,
        permission_reference: permissionReference.trim(),
        safety_attacks_confirmed: false,
        allow_private_targets: runsOnMyComputer,
        response_format: "json",
      });
      if (result.question_path) {
        const bodyTemplate = bodyTemplateWithQuestionPath(
          parsed.body_template,
          result.question_path,
        );
        if (!bodyTemplate) {
          setWebsiteError("Could not place the question placeholder in the imported JSON body.");
          return;
        }
        parsed = {
          ...parsed,
          body_template: bodyTemplate,
          question_path: result.question_path,
        };
        setWebsiteParsed(parsed);
        setDetectResult({
          success: true,
          message: "Website request imported",
          detected_answer_path: null,
          detected_context_path: null,
          detected_request_shape: bodyTemplate,
        });
      }
      setWebsiteCheck(result);
      setWebsiteSelectedPath(selectedPath ?? "");
      setAnswerPath(selectedPath ?? "");
    } catch (caught) {
      setWebsiteError(
        caught instanceof ApiError ? caught.message : "Could not read the website response.",
      );
    } finally {
      setWebsiteChecking(false);
    }
  }, [
    handleCheckAccepted,
    permissionConfirmed,
    permissionReference,
    runsOnMyComputer,
    websiteCurl,
    websiteMessage,
    websiteParsed,
  ]);

  const websiteAcceptCheck = useCallback(
    async (checked: boolean) => {
      if (!websiteCheck) return;
      if (!checked) {
        handleCheckAccepted(null);
        setWebsiteCheck(null);
        return;
      }
      try {
        const accepted = await acceptTargetCheck(websiteCheck.check_id);
        setWebsiteCheck(accepted);
        handleCheckAccepted(accepted.accepted ? accepted.check_id : null);
      } catch (caught) {
        setWebsiteError(
          caught instanceof ApiError ? caught.message : "Could not accept this check.",
        );
        handleCheckAccepted(null);
      }
    },
    [handleCheckAccepted, websiteCheck],
  );
  // Approved dataset versions are the only thing a run may execute.
  useEffect(() => {
    listDatasets()
      .then((response) => {
        const options: DatasetOption[] = [];
        for (const dataset of response.items) {
          for (const version of dataset.versions) {
            if (!version.approved_at) continue;
            options.push({
              value: version.id,
              label: `${dataset.name} · v${version.version_no} (${version.row_count} cases)`,
            });
          }
        }
        setDatasetOptions(options);
      })
      .catch(() => setDatasetOptions([]));
  }, []);

  // Active providers are the only ones a prompt-app run may use.
  useEffect(() => {
    listProviders()
      .then((providers) => {
        const active = providers.filter((provider) => provider.is_active);
        setProviderOptions(
          active.map((provider) => ({
            id: provider.id,
            name: provider.name,
            modelName: provider.model_name,
          })),
        );
        const first = active[0];
        if (first) {
          setSelectedProviderId((current) => current || first.id);
          setPromptAppModel((current) => current || first.model_name);
        }
      })
      .catch(() => setProviderOptions([]));
  }, []);

  // When the user drops a file, read its headers and auto-detect column names.
  useEffect(() => {
    if (!uploadFile) {
      setUploadColumns([]);
      return;
    }
    let cancelled = false;
    let reader: FileReader | null = null;
    try {
      reader = new FileReader();
      reader.onload = () => {
        if (cancelled) return;
        const text = reader?.result ?? "";
        const raw = typeof text === "string" ? text : "";
        const first = raw.split("\n").find((line) => line.trim().length > 0);
        let headers: string[] = [];
        if (first?.trim().startsWith("{") || first?.trim().startsWith("[")) {
          try {
            const parsed = JSON.parse(raw);
            const items = Array.isArray(parsed)
              ? parsed
              : (parsed.data ?? parsed.items ?? parsed.rows ?? []);
            if (items.length > 0) {
              const sample = items[0];
              if (sample && typeof sample === "object" && !Array.isArray(sample)) {
                headers = Object.keys(sample);
              }
            }
          } catch {
            headers = [];
          }
        } else if (first) {
          headers = first.split(",").map((h) => h.trim());
        }
        const detect = (key: keyof typeof UPLOAD_COLUMN_KNOWN): string | null => {
          const target = UPLOAD_COLUMN_KNOWN[key];
          if (!target) return null;
          const lowered = headers.map((h) => h.trim().toLowerCase());
          const idx = lowered.findIndex((h) => h === target.toLowerCase());
          if (idx !== -1) return headers[idx] ?? null;
          return null;
        };
        const cols: UploadOutputsColumnOption[] = [];
        for (const key of [
          "input",
          "output",
          "id",
          "retrieved_context",
          "latency_ms",
          "tokens_in",
          "tokens_out",
        ] as const) {
          const found = detect(key);
          if (found) cols.push({ label: found, value: found });
        }
        if (!cancelled) setUploadColumns(cols);
      };
      reader.readAsText(uploadFile, "utf-8");
    } catch {
      if (!cancelled) setUploadColumns([]);
    }
    return () => {
      cancelled = true;
      reader?.abort();
    };
  }, [uploadFile]);

  // Poll the worker's counters until the run reaches a terminal state.
  const runId = activeRun?.id;
  const runState = activeRun?.state;
  useEffect(() => {
    if (!runId || !runState || isTerminal(runState)) return;
    let stopped = false;
    const timer = window.setInterval(() => {
      getRun(runId)
        .then((fresh) => {
          if (!stopped) setActiveRun(fresh);
        })
        .catch(() => {
          // Keep the last known state; the next tick tries again.
        });
    }, POLL_INTERVAL_MS);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [runId, runState]);

  // A stored default fills the form once, and never overwrites a choice the user
  // has already made here: the refs record both kinds of decision.
  const connectorTouched = useRef(false);
  const testTypesTouched = useRef(false);
  useEffect(() => {
    let cancelled = false;
    fetchPreferences()
      .then((stored) => {
        if (cancelled) return;
        if (stored.entry_point && !connectorTouched.current) {
          setConnector(stored.entry_point);
        }
        const chosen = stored.test_types ?? [];
        if (chosen.length > 0 && !testTypesTouched.current) {
          setTestTypes({
            quality: chosen.includes("quality"),
            safety: chosen.includes("safety"),
            operations: chosen.includes("operations"),
          });
        }
      })
      .catch(() => {
        /* no stored default behaves exactly like the built-in one */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleConnectorChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    connectorTouched.current = true;
    setConnector(e.target.value as EntryPoint);
    setUrl("");
    setCurlNotice(null);
    setError(null);
    // A check belongs to one target: switching entry points starts over.
    handleCheckAccepted(null);
  };

  const toggleTestType = (key: keyof TestTypes) => {
    testTypesTouched.current = true;
    setTestTypes((previous) => ({ ...previous, [key]: !previous[key] }));
  };

  const applyCurl = async () => {
    const local = parseCurlLocally(curlText);
    if (!local) {
      setCurlNotice(
        "That does not look like a curl command with a URL. Paste the full command, starting with “curl”.",
      );
      return;
    }
    setUrl(local.url);
    try {
      const parsed = await parseCurl(curlText);
      setCurlSecret(parsed.headers_secret ?? "");
      setCurlHeaderNames(parsed.header_names);
      setCurlNotice(
        `Parsed ${parsed.method} ${parsed.url}` +
          (parsed.header_names.length > 0
            ? ` with ${parsed.header_names.length} header(s): ${parsed.header_names.join(", ")}`
            : "") +
          ". Header values and cookies are stored encrypted and never shown again.",
      );
    } catch {
      setCurlNotice(
        `Parsed ${local.method} ${local.url}. Could not import its headers; paste it again ` +
          "or add them under Advanced connector options.",
      );
    }
  };

  const handlePromptAppProviderChange = (providerId: string) => {
    setSelectedProviderId(providerId);
    const picked = providerOptions.find((option) => option.id === providerId);
    setPromptAppModel(picked ? picked.modelName : "");
  };

  const handleStartTest = async () => {
    setError(null);
    setNotice(null);
    setRunError(null);
    setDetectResult(null);
    const anyType = testTypes.quality || testTypes.safety || testTypes.operations;
    if (!anyType) {
      setError("Pick at least one test type — Quality, Safety or Operations.");
      return;
    }
    if (connector === "http_endpoint" && !url.trim()) {
      setError("Enter the URL of the app GreenLit should test (or paste a curl command).");
      return;
    }
    if (connector === "http_endpoint" && !runsOnMyComputer && !permissionConfirmed) {
      setError(
        "Confirm that you own this application or have permission to test it before GreenLit " +
          "sends anything to it.",
      );
      return;
    }

    if (connector === "http_endpoint") {
      setLoading(true);
      try {
        const result = await testConnection({
          connector_type: "http_endpoint",
          url: url.trim(),
          method: "POST",
          auto_detect: true,
          headers_secret: curlSecret || undefined,
          allow_private_targets: runsOnMyComputer,
          permission_confirmed: !runsOnMyComputer && permissionConfirmed,
          permission_reference: !runsOnMyComputer
            ? permissionReference.trim() || undefined
            : undefined,
          safety_attacks_confirmed: !runsOnMyComputer && safetyAttacksConfirmed,
          max_concurrency: maxConcurrency,
          min_delay_ms: minDelayMs,
          max_retries: maxRetries,
          response_format: responseFormat,
          stream_content_path: streamContentPath.trim() || undefined,
        });
        setDetectResult(result);
        setAnswerPath(result.detected_answer_path || "");
        setNotice("Auto-detect complete. These settings are used when the test runs.");
      } catch (caught) {
        if (caught instanceof ApiError) {
          setError(caught.message);
        } else {
          setError("Connection test failed.");
        }
      } finally {
        setLoading(false);
      }
      return;
    }

    if (connector === "prompt_app") {
      if (providerOptions.length === 0) {
        setError("Add a model provider in Settings → Providers, then start the test again.");
        return;
      }
      if (!selectedProviderId) {
        setError("Pick the provider this prompt app should answer with.");
        return;
      }
      const target = systemPrompt.trim();
      if (!target) {
        setError("Enter a system prompt so the model knows how to answer.");
        return;
      }
      setStartingRun(true);
      setActiveRun(null);
      try {
        if (promptDatasetId) {
          setActiveRun(
            await startRun({
              entry_point: "prompt_app",
              target,
              test_types: chosenTestTypes(testTypes),
              provider_id: selectedProviderId,
              model: promptAppModel.trim() || undefined,
              system_prompt: target,
              timeout_seconds: 60,
              allow_private_targets: runsOnMyComputer,
              dataset_version_id: promptDatasetId,
              ...runCaps,
            }),
          );
          setNotice("Run queued. A worker executes the cases, this page polls its progress.");
        } else {
          const result = await quickTest({
            entry_point: "prompt_app",
            target,
            tests: chosenTestTypes(testTypes),
            provider_id: selectedProviderId,
            model: promptAppModel.trim() || undefined,
            timeout_seconds: 60,
            allow_private_targets: runsOnMyComputer,
            generate: GENERATED_CASES,
            ...runCaps,
          });
          setActiveRun(result.run);
          setNotice(
            `GreenLit generated ${GENERATED_CASES} test cases, approved them and queued the run.`,
          );
        }
      } catch (caught) {
        setRunError(
          caught instanceof ApiError ? caught.message : "Could not start the test. Try again.",
        );
      } finally {
        setStartingRun(false);
      }
      return;
    }

    if (connector === "upload_outputs") {
      if (!uploadFile) {
        setError("Upload a CSV or JSON file of outputs first.");
        return;
      }
      if (!uploadInputColumn || !uploadOutputColumn) {
        setError("Map the input and output columns from your file first.");
        return;
      }
      if (!uploadDatasetVersionId) {
        setError("Pick the golden dataset this run should score against.");
        return;
      }
      setLoading(true);
      setUploadConnectorStatus("loading");
      setUploadConnectorMessage("");
      try {
        const text = await uploadFile.text();
        const result = await testConnection({
          connector_type: "upload_outputs",
          body_template: text,
        });
        setUploadConnectorStatus(result.success ? "ok" : "error");
        setUploadConnectorMessage(result.message);
        if (!result.success) {
          setLoading(false);
          return;
        }
        setStartingRun(true);
        setActiveRun(null);
        const run = await startRun({
          entry_point: "upload_outputs",
          test_types: chosenTestTypes(testTypes),
          dataset_version_id: uploadDatasetVersionId,
          timeout_seconds: 60,
          allow_private_targets: runsOnMyComputer,
          body_template: text,
          ...runCaps,
        });
        setActiveRun(run);
        setNotice("Run queued. A worker scores the uploaded outputs against the golden dataset.");
      } catch (caught) {
        setUploadConnectorStatus("error");
        setUploadConnectorMessage(
          caught instanceof ApiError ? caught.message : "Connection test failed.",
        );
        setLoading(false);
      }
      return;
    }

    setNotice(
      "Uploaded-output runs already work through the API; this page gets their fields " +
        "in the next step. Datasets can be managed in Settings → Datasets.",
    );
  };

  const handleRunTest = useCallback(
    async (options: { smoke?: boolean } = {}) => {
      if (connector === "http_endpoint" && !detectResult) return;
      const smoke = options.smoke === true;
      setRunError(null);
      // A remote target may not be run until its extraction was accepted.
      if (
        (connector === "http_endpoint" || connector === "mcp_server") &&
        !runsOnMyComputer &&
        !targetCheckId
      ) {
        setRunError("Check the target and confirm the answer looks right before starting a run.");
        return;
      }
      if (connector === "mcp_server" && !datasetVersionId) {
        setRunError(
          "Choose an approved dataset: an MCP run scores the tool's answers against one.",
        );
        return;
      }
      setActiveRun(null);
      if (smoke) setStartingSmoke(true);
      else setStartingRun(true);
      const target = url.trim();
      // A smoke run is a five-case rehearsal whatever the limits say.
      const caps = smoke ? { ...runCaps, max_cases: 5 } : runCaps;
      const checkId = !runsOnMyComputer ? (targetCheckId ?? undefined) : undefined;
      if (connector === "mcp_server") {
        const payload = buildMcpRunPayload({
          config: mcpConfig,
          allowPrivate: runsOnMyComputer,
          permissionConfirmed,
          permissionReference,
          maxRetries,
        });
        if (!payload) {
          setStartingRun(false);
          setStartingSmoke(false);
          setRunError("Choose the tool to call and the argument that carries the question.");
          return;
        }
        try {
          setActiveRun(
            await startRun({
              ...payload,
              test_types: chosenTestTypes(testTypes),
              dataset_version_id: datasetVersionId,
              is_smoke: smoke,
              target_check_id: checkId,
              ...caps,
            }),
          );
          setNotice("Run queued. A worker executes the cases, this page polls its progress.");
        } catch (caught) {
          setRunError(
            caught instanceof ApiError ? caught.message : "Could not start the test. Try again.",
          );
        } finally {
          setStartingRun(false);
          setStartingSmoke(false);
        }
        return;
      }
      // Only an HTTP run reaches here, and it always has a detected shape.
      if (!detectResult) {
        setStartingRun(false);
        setStartingSmoke(false);
        return;
      }
      const common: RunCreateRequest = {
        entry_point: "http_endpoint",
        target,
        test_types: chosenTestTypes(testTypes),
        method: "POST",
        body_template: detectResult.detected_request_shape || '{"question": {{input}}}',
        headers_secret: curlSecret || undefined,
        header_names: curlHeaderNames.length > 0 ? curlHeaderNames : undefined,
        answer_path: answerPath || detectResult.detected_answer_path || undefined,
        context_path: detectResult.detected_context_path || undefined,
        timeout_seconds: 60,
        allow_private_targets: runsOnMyComputer,
        permission_confirmed: !runsOnMyComputer && permissionConfirmed,
        permission_reference: !runsOnMyComputer
          ? permissionReference.trim() || undefined
          : undefined,
        safety_attacks_confirmed: !runsOnMyComputer && safetyAttacksConfirmed,
        max_concurrency: maxConcurrency,
        min_delay_ms: minDelayMs,
        max_retries: maxRetries,
        response_format: responseFormat,
        stream_content_path: streamContentPath.trim() || undefined,
        is_smoke: smoke,
        target_check_id: checkId,
        ...caps,
      };
      try {
        if (datasetVersionId) {
          setActiveRun(await startRun({ ...common, dataset_version_id: datasetVersionId }));
          setNotice("Run queued. A worker executes the cases, this page polls its progress.");
        } else {
          // No dataset chosen: GreenLit writes the cases with the model first.
          const result = await quickTest({
            entry_point: "http_endpoint",
            target,
            tests: chosenTestTypes(testTypes),
            method: "POST",
            body_template: detectResult.detected_request_shape || '{"question": {{input}}}',
            headers_secret: curlSecret || undefined,
            header_names: curlHeaderNames.length > 0 ? curlHeaderNames : undefined,
            answer_path: answerPath || detectResult.detected_answer_path || undefined,
            context_path: detectResult.detected_context_path || undefined,
            timeout_seconds: 60,
            allow_private_targets: runsOnMyComputer,
            permission_confirmed: !runsOnMyComputer && permissionConfirmed,
            permission_reference: !runsOnMyComputer
              ? permissionReference.trim() || undefined
              : undefined,
            safety_attacks_confirmed: !runsOnMyComputer && safetyAttacksConfirmed,
            max_concurrency: maxConcurrency,
            min_delay_ms: minDelayMs,
            max_retries: maxRetries,
            response_format: responseFormat,
            stream_content_path: streamContentPath.trim() || undefined,
            generate: GENERATED_CASES,
            is_smoke: smoke,
            target_check_id: checkId,
            ...caps,
          });
          setActiveRun(result.run);
          setNotice(
            `GreenLit generated ${GENERATED_CASES} test cases, approved them and queued the run.`,
          );
        }
      } catch (caught) {
        setRunError(
          caught instanceof ApiError ? caught.message : "Could not start the test. Try again.",
        );
      } finally {
        setStartingRun(false);
        setStartingSmoke(false);
      }
    },
    [
      answerPath,
      connector,
      curlHeaderNames,
      curlSecret,
      datasetVersionId,
      detectResult,
      maxConcurrency,
      maxRetries,
      mcpConfig,
      minDelayMs,
      permissionConfirmed,
      permissionReference,
      responseFormat,
      runCaps,
      runsOnMyComputer,
      safetyAttacksConfirmed,
      streamContentPath,
      targetCheckId,
      testTypes,
      url,
    ],
  );

  const handleCancelRun = async () => {
    if (!activeRun) return;
    setCancelling(true);
    setRunError(null);
    try {
      setActiveRun(await cancelRun(activeRun.id));
    } catch (caught) {
      setRunError(
        caught instanceof ApiError ? caught.message : "Could not cancel this run. Try again.",
      );
    } finally {
      setCancelling(false);
    }
  };

  const websiteRunReady = useCallback(
    () =>
      Boolean(
        websiteCheck?.accepted &&
          websiteCheck.extraction_ok &&
          websiteSelectedPath &&
          websiteCheck.mapping_path === websiteSelectedPath &&
          websiteCheck.question_path &&
          permissionConfirmed &&
          permissionReference.trim(),
      ),
    [permissionConfirmed, permissionReference, websiteCheck, websiteSelectedPath],
  );

  const targetRunReady = useCallback(() => {
    if (connector === "mcp_server") return runsOnMyComputer || targetCheckId != null;
    if (connector !== "http_endpoint") return true;
    if (websiteWizard) return websiteRunReady();
    if (runsOnMyComputer) return true;
    return targetCheckId != null;
  }, [connector, runsOnMyComputer, targetCheckId, websiteRunReady, websiteWizard]);

  return (
    <>
      <header className="page__header">
        <div>
          <h1>New Test</h1>
          <p className="page__description">
            Point GreenLit at your LLM app and get one decision — GO, REVIEW or NO-GO — with the
            evidence behind it.
          </p>
        </div>
      </header>

      {/* The three prerequisites only line up for the HTTP entry point: a prompt
          app needs no connector test, and uploaded outputs need no target. */}
      {connector === "http_endpoint" ? (
        <div style={{ marginBottom: "var(--space-5)" }}>
          <SetupChecklist
            providers={providerOptions}
            connectorTested={detectResult !== null}
            approvedDatasets={datasetOptions.length}
            onGoToTarget={() => {
              const field = document.querySelector<HTMLInputElement>('[data-testid="target-url"]');
              field?.scrollIntoView({ block: "center" });
              field?.focus();
            }}
          />
        </div>
      ) : null}

      <section className="card" aria-labelledby="target-heading">
        <div className="card__header">
          <h2 id="target-heading">What should GreenLit test?</h2>
          <p className="page__subtitle">Select how GreenLit should connect to your app.</p>
        </div>

        <p className="card__hint">
          Three entry points are available here: an HTTP endpoint, a prompt app (system prompt plus
          model), or uploaded outputs (CSV or JSON). Other entry points (Python function, Docker
          image, Git repository, CLI command, Proxy mode, MCP server) are coming soon.
        </p>

        <div style={{ marginTop: "var(--space-5)" }}>
          <label className="form__label" htmlFor="connector-select">
            Entry point:
          </label>
          <select
            id="connector-select"
            data-testid="connector-select"
            value={connector}
            onChange={handleConnectorChange}
            disabled={loading}
          >
            <option value="http_endpoint">HTTP endpoint</option>
            <option value="mcp_server">MCP server (tool call)</option>
            <option value="prompt_app">Prompt app (system prompt + model)</option>
            <option value="upload_outputs">Upload outputs (CSV/JSON)</option>
            <optgroup label="Coming soon">
              <option disabled>Python function (traced)</option>
              <option disabled>Built-in RAG app</option>
              <option disabled>Python SDK (traced)</option>
              <option disabled>Docker image</option>
              <option disabled>Git repository</option>
              <option disabled>CLI command</option>
            </optgroup>
          </select>
        </div>

        {connector === "mcp_server" ? (
          <McpPanel
            config={mcpConfig}
            onConfigChange={(patch) => setMcpConfig((previous) => ({ ...previous, ...patch }))}
            allowPrivate={runsOnMyComputer}
            permissionConfirmed={permissionConfirmed}
            permissionReference={permissionReference}
            disabled={loading}
          />
        ) : null}

        {connector !== "mcp_server" && websiteWizard ? (
          <WebsiteWizard
            check={websiteCheck}
            busy={websiteChecking}
            error={websiteError}
            curlText={websiteCurl}
            onCurlChange={setWebsiteCurl}
            message={websiteMessage}
            onMessageChange={setWebsiteMessage}
            onRead={() => runWebsiteCheck()}
            canRead={
              (websiteCurl.trim().length > 0 || websiteParsed !== null) &&
              websiteMessage.trim().length > 0 &&
              permissionConfirmed &&
              permissionReference.trim().length > 0
            }
            candidates={websiteCheck?.answer_candidates ?? []}
            selectedPath={websiteSelectedPath}
            onSelectPath={(path) => {
              setWebsiteSelectedPath(path);
              void runWebsiteCheck(path);
            }}
            accepted={websiteCheck?.accepted ?? false}
            onAccept={websiteAcceptCheck}
            headerNames={websiteParsed?.header_names ?? []}
            onClose={() => {
              setWebsiteWizard(false);
              setWebsiteCurl("");
              setWebsiteParsed(null);
              setWebsiteCheck(null);
              setWebsiteSelectedPath("");
              setWebsiteError(null);
            }}
          />
        ) : connector !== "mcp_server" ? (
          <button
            type="button"
            className="form__curl-button"
            onClick={() => setWebsiteWizard(true)}
            disabled={loading}
          >
            Website chatbot (wizard)
          </button>
        ) : null}

        {connector === "http_endpoint" && (
          <div style={{ marginTop: "var(--space-5)" }}>
            <label className="form__label" htmlFor="target-url">
              Target URL:
            </label>
            <input
              id="target-url"
              data-testid="target-url"
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://myapp.local/ask"
              disabled={loading}
            />
            <button
              onClick={() => setShowCurl(!showCurl)}
              className="form__curl-button"
              type="button"
              disabled={loading}
              aria-expanded={showCurl}
            >
              {showCurl ? "Hide cURL" : "Paste cURL"}
            </button>

            {showCurl && !websiteWizard && (
              <div style={{ marginTop: "var(--space-3)" }}>
                <label className="form__label" htmlFor="curl-input">
                  Paste the full curl command:
                </label>
                <textarea
                  id="curl-input"
                  rows={3}
                  value={curlText}
                  onChange={(e) => setCurlText(e.target.value)}
                  placeholder={
                    'curl -X POST https://myapp.local/ask -H "Content-Type: application/json" -d \'{"question": "{{input}}"}\''
                  }
                  disabled={loading}
                />
                <div className="datasets__actions" style={{ marginTop: "var(--space-2)" }}>
                  <Button variant="secondary" onClick={() => void applyCurl()} disabled={loading}>
                    Use this request
                  </Button>
                  {curlHeaderNames.length > 0 ? (
                    <span className="form__hint" data-testid="curl-header-names">
                      Imported: {curlHeaderNames.join(", ")}
                    </span>
                  ) : null}
                </div>
                {curlNotice && (
                  <p className="form__hint" role="status">
                    {curlNotice}
                  </p>
                )}
              </div>
            )}
          </div>
        )}

        {connector === "prompt_app" && (
          <PromptAppPanel
            providerOptions={providerOptions}
            selectedProviderId={selectedProviderId}
            systemPrompt={systemPrompt}
            model={promptAppModel}
            datasetOptions={datasetOptions}
            datasetVersionId={promptDatasetId}
            generatedCases={GENERATED_CASES}
            disabled={startingRun}
            onProviderChange={handlePromptAppProviderChange}
            onSystemPromptChange={setSystemPrompt}
            onModelChange={setPromptAppModel}
            onDatasetChange={setPromptDatasetId}
          />
        )}

        {connector === "upload_outputs" && (
          <UploadOutputsPanel
            file={uploadFile}
            fileName={uploadFileName}
            detectedColumns={uploadColumns}
            inputColumn={uploadInputColumn}
            outputColumn={uploadOutputColumn}
            idColumn={uploadIdColumn}
            contextColumn={uploadContextColumn}
            latencyColumn={uploadLatencyColumn}
            tokensInColumn={uploadTokensInColumn}
            tokensOutColumn={uploadTokensOutColumn}
            datasetOptions={datasetOptions.map((opt) => ({
              value: opt.value,
              label: opt.label,
            }))}
            selectedDatasetVersionId={uploadDatasetVersionId}
            datasetRowCount={
              datasetOptions
                .find((opt) => opt.value === uploadDatasetVersionId)
                ?.label.match(/\(([0-9]+) cases\)/)?.[1]
                ? Number(
                    datasetOptions
                      .find((opt) => opt.value === uploadDatasetVersionId)!
                      .label.match(/\(([0-9]+) cases\)/)![1],
                  )
                : 0
            }
            connectorTestStatus={uploadConnectorStatus}
            connectorTestMessage={uploadConnectorMessage}
            disabled={loading || startingRun}
            onFileChange={(file) => {
              setUploadFile(file);
              setUploadFileName(file?.name ?? "");
              setUploadColumns([]);
              setUploadInputColumn("");
              setUploadOutputColumn("");
              setUploadIdColumn("");
              setUploadContextColumn("");
              setUploadLatencyColumn("");
              setUploadTokensInColumn("");
              setUploadTokensOutColumn("");
              setUploadConnectorStatus("idle");
              setUploadConnectorMessage("");
              setUploadDatasetVersionId("");
            }}
            onColumnChange={(key, value) => {
              switch (key) {
                case "input":
                  setUploadInputColumn(value);
                  break;
                case "output":
                  setUploadOutputColumn(value);
                  break;
                case "id":
                  setUploadIdColumn(value);
                  break;
                case "context":
                  setUploadContextColumn(value);
                  break;
                case "latency":
                  setUploadLatencyColumn(value);
                  break;
                case "tokens_in":
                  setUploadTokensInColumn(value);
                  break;
                case "tokens_out":
                  setUploadTokensOutColumn(value);
                  break;
              }
            }}
            onDatasetChange={setUploadDatasetVersionId}
          />
        )}

        <fieldset style={{ marginTop: "var(--space-5)" }}>
          <legend className="form__label">Test types (all on by default):</legend>
          <div className="datasets__actions">
            <label>
              <input
                type="checkbox"
                checked={testTypes.quality}
                onChange={() => toggleTestType("quality")}
                disabled={loading}
              />{" "}
              Quality
            </label>
            <label>
              <input
                type="checkbox"
                checked={testTypes.safety}
                onChange={() => toggleTestType("safety")}
                disabled={loading}
              />{" "}
              Safety
            </label>
            <label>
              <input
                type="checkbox"
                checked={testTypes.operations}
                onChange={() => toggleTestType("operations")}
                disabled={loading}
              />{" "}
              Operations (latency, errors, tokens)
            </label>
          </div>
          {testTypes.safety ? (
            <p className="form__hint">
              Safety sends the built-in attack set (prompt injection, hidden instructions,
              system-prompt leaks, jailbreaks and harmful requests) plus harmless prompts that must
              still be answered. A leaked secret or a missing refusal is a hard NO-GO.
            </p>
          ) : null}
        </fieldset>

        <details className="form__advanced" data-testid="run-limits-options">
          <summary>Run limits</summary>
          <p className="form__hint">
            A run stops when it reaches one of these limits and keeps what it already measured, so
            the verdict then covers only the cases that ran. Leave a box empty for no limit.
          </p>
          <div className="datasets__actions">
            <label htmlFor="max-cases">
              Stop after at most (cases):{" "}
              <input
                id="max-cases"
                data-testid="max-cases"
                type="number"
                min={1}
                max={1000}
                value={maxCases}
                placeholder="every case"
                onChange={(e) => setMaxCases(e.target.value)}
                disabled={loading}
              />
            </label>
            <label htmlFor="max-duration">
              Time cap (seconds):{" "}
              <input
                id="max-duration"
                data-testid="max-duration"
                type="number"
                min={30}
                max={14400}
                step={30}
                value={maxDurationSeconds}
                onChange={(e) => setMaxDurationSeconds(e.target.value)}
                disabled={loading}
              />
            </label>
            <label htmlFor="max-tokens">
              Token cap (optional):{" "}
              <input
                id="max-tokens"
                data-testid="max-tokens"
                type="number"
                min={1}
                value={maxTotalTokens}
                placeholder="no cap"
                onChange={(e) => setMaxTotalTokens(e.target.value)}
                disabled={loading}
              />
            </label>
          </div>
          <p className="form__hint">
            The token cap applies only when the app reports token counts; otherwise it is shown as
            not instrumented instead of being counted as zero.
          </p>
        </details>

        {connector === "http_endpoint" && (
          <details className="form__advanced" data-testid="advanced-connector">
            <summary>Advanced connector options</summary>
            <p className="form__hint">
              Polite defaults: one request at a time, at least 500 ms between requests, and a busy
              target (429, 502, 503, 504) retried three times with backoff, honouring its
              Retry-After. Set retries to 0 to send each request exactly once — that avoids
              duplicate side effects when a request may already have reached the app.
            </p>
            <div className="datasets__actions">
              <label htmlFor="max-concurrency">
                Max concurrent requests:{" "}
                <input
                  id="max-concurrency"
                  type="number"
                  min={1}
                  max={8}
                  value={maxConcurrency}
                  onChange={(e) => setMaxConcurrency(Number(e.target.value) || 1)}
                  disabled={loading}
                />
              </label>
              <label htmlFor="min-delay-ms">
                Minimum delay between requests (ms):{" "}
                <input
                  id="min-delay-ms"
                  type="number"
                  min={0}
                  max={60000}
                  step={100}
                  value={minDelayMs}
                  onChange={(e) => setMinDelayMs(Number(e.target.value) || 0)}
                  disabled={loading}
                />
              </label>
              <label htmlFor="max-retries">
                Retries on a busy target:{" "}
                <input
                  id="max-retries"
                  type="number"
                  min={0}
                  max={10}
                  value={maxRetries}
                  onChange={(e) => setMaxRetries(Number(e.target.value) || 0)}
                  disabled={loading}
                />
              </label>
            </div>
            <label className="form__label" htmlFor="response-format">
              How the app answers:
              <select
                id="response-format"
                data-testid="response-format"
                value={responseFormat}
                onChange={(e) =>
                  setResponseFormat(e.target.value as "json" | "sse" | "ndjson" | "text")
                }
                disabled={loading}
              >
                <option value="json">One JSON body (default)</option>
                <option value="sse">Server-sent events (SSE)</option>
                <option value="ndjson">Streamed JSON lines (NDJSON)</option>
                <option value="text">Plain text stream</option>
              </select>
            </label>
            {responseFormat !== "json" && responseFormat !== "text" ? (
              <label className="form__label" htmlFor="stream-content-path">
                Where the text sits in each event (optional):
                <input
                  id="stream-content-path"
                  data-testid="stream-content-path"
                  type="text"
                  value={streamContentPath}
                  onChange={(e) => setStreamContentPath(e.target.value)}
                  placeholder="choices.0.delta.content"
                  disabled={loading}
                />
              </label>
            ) : null}
          </details>
        )}

        <div className="form__run-on-computer" style={{ marginTop: "var(--space-5)" }}>
          <input
            type="checkbox"
            id="runs-on-my-computer"
            checked={runsOnMyComputer}
            onChange={() => setRunsOnMyComputer(!runsOnMyComputer)}
            disabled={loading}
          />
          <label htmlFor="runs-on-my-computer">This app runs on my computer</label>
          <p className="form__hint">
            GreenLit reaches your local app through host.docker.internal when the API runs in
            Docker. Only enable this for targets you trust.
          </p>
        </div>

        {connector === "http_endpoint" && !runsOnMyComputer ? (
          <div
            className="form__run-on-computer"
            data-testid="permission-block"
            style={{ marginTop: "var(--space-4)" }}
          >
            <input
              type="checkbox"
              id="permission-confirmed"
              data-testid="permission-confirmed"
              checked={permissionConfirmed}
              onChange={() => {
                setPermissionConfirmed(!permissionConfirmed);
                if (permissionConfirmed) setSafetyAttacksConfirmed(false);
              }}
              disabled={loading}
            />
            <label htmlFor="permission-confirmed">
              I own this application or have permission to test it
            </label>
            <p className="form__hint">
              GreenLit sends real requests to this address. Confirm the owner agreed before testing
              an app you do not host.
            </p>
            <label className="form__label" htmlFor="permission-reference">
              Who gave permission / reference (required for Website chatbot):
            </label>
            <input
              id="permission-reference"
              data-testid="permission-reference"
              type="text"
              value={permissionReference}
              onChange={(e) => setPermissionReference(e.target.value)}
              placeholder="e.g. support lead, ticket 4711"
              disabled={loading}
            />
            {testTypes.safety ? (
              <div style={{ marginTop: "var(--space-3)" }}>
                <input
                  type="checkbox"
                  id="safety-attacks-confirmed"
                  data-testid="safety-attacks-confirmed"
                  checked={safetyAttacksConfirmed}
                  onChange={() => setSafetyAttacksConfirmed(!safetyAttacksConfirmed)}
                  disabled={loading || !permissionConfirmed}
                />
                <label htmlFor="safety-attacks-confirmed">
                  I own this application or have permission to test it, including security attack
                  probes
                </label>
                <p className="form__hint">
                  Attack probes (prompt injection, jailbreaks, hidden instructions) stay off against
                  an app you do not host unless this second box is ticked.
                </p>
              </div>
            ) : null}
          </div>
        ) : null}

        {error && (
          <p className="form-error" role="alert" style={{ marginTop: "var(--space-4)" }}>
            {error}
          </p>
        )}

        {detectResult && (
          <div
            className="notice"
            role="status"
            data-testid="detect-result"
            style={{ marginTop: "var(--space-4)" }}
          >
            <strong>Detected</strong>
            <div style={{ marginTop: "var(--space-2)" }}>
              <div data-testid="detected-request-shape">
                Request body template:{" "}
                {detectResult.detected_request_shape || '{"question": {{input}}}'}
              </div>
              <div data-testid="detected-answer-path">
                Detected answer path:{" "}
                {detectResult.detected_answer_path || answerPath || "(auto-detected)"}
              </div>
              <div data-testid="detected-context-path">
                Detected context path: {detectResult.detected_context_path || "not instrumented"}
              </div>
              {detectResult.trace && (detectResult.trace as Record<string, unknown>).raw ? (
                <details style={{ marginTop: "var(--space-2)" }}>
                  <summary>Real response</summary>
                  <pre style={{ overflow: "auto", maxHeight: "200px" }}>
                    {JSON.stringify((detectResult.trace as Record<string, unknown>).raw, null, 2)}
                  </pre>
                </details>
              ) : null}
              <div style={{ marginTop: "var(--space-2)" }}>
                <label className="form__label" htmlFor="answer-path">
                  Correct answer path (one click):
                </label>
                <input
                  id="answer-path"
                  type="text"
                  data-testid="answer-path"
                  value={answerPath}
                  onChange={(e) => setAnswerPath(e.target.value)}
                  placeholder="choices.0.message.content"
                />
              </div>

              {(connector === "mcp_server" ||
                (connector === "http_endpoint" && (!websiteWizard || !websiteParsed))) &&
              !runsOnMyComputer &&
              checkRequest ? (
                <TargetCheckPanel
                  request={checkRequest}
                  onAccepted={handleCheckAccepted}
                  disabled={startingRun || startingSmoke}
                />
              ) : null}

              <div style={{ marginTop: "var(--space-4)" }}>
                <label className="form__label" htmlFor="run-dataset">
                  Test cases:
                </label>
                <select
                  id="run-dataset"
                  data-testid="run-dataset"
                  value={datasetVersionId}
                  onChange={(e) => setDatasetVersionId(e.target.value)}
                  disabled={startingRun}
                >
                  <option value="">
                    Generate {GENERATED_CASES} questions with your model provider
                  </option>
                  {datasetOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                {datasetOptions.length === 0 ? (
                  <p className="form__hint">
                    No approved dataset yet. GreenLit writes the questions with your provider
                    (Settings → Providers), or upload a dataset in Settings → Datasets.
                  </p>
                ) : null}
              </div>

              <div className="datasets__actions" style={{ marginTop: "var(--space-3)" }}>
                <Button
                  variant="primary"
                  loading={startingRun}
                  onClick={() => void handleRunTest()}
                  disabled={startingRun || startingSmoke || !targetRunReady()}
                  data-testid="run-full"
                >
                  {startingRun ? <Spinner size="sm" label="Starting your test" /> : "Run full test"}
                </Button>
                <Button
                  variant="secondary"
                  loading={startingSmoke}
                  onClick={() => void handleRunTest({ smoke: true })}
                  disabled={startingRun || startingSmoke || !targetRunReady()}
                  data-testid="run-smoke"
                >
                  {startingSmoke ? (
                    <Spinner size="sm" label="Starting the smoke run" />
                  ) : (
                    "Run 5-case smoke test"
                  )}
                </Button>
              </div>
              {(!runsOnMyComputer || websiteWizard) && !targetRunReady() ? (
                <p className="form__hint" data-testid="run-full-blocked">
                  Accept the extraction from the check above before starting a run. A smoke run is
                  five cases and is not a verdict.
                </p>
              ) : null}
            </div>
          </div>
        )}

        <div style={{ marginTop: "var(--space-5)" }}>
          <Button
            variant="primary"
            size="lg"
            loading={loading}
            onClick={handleStartTest}
            data-testid="start-test"
          >
            {loading ? <Spinner size="sm" label="Checking your setup" /> : "Start test"}
          </Button>
        </div>

        {notice && !detectResult && (
          <div className="notice" role="status" style={{ marginTop: "var(--space-4)" }}>
            {notice}
          </div>
        )}

        {runError && (
          <p className="form-error" role="alert" style={{ marginTop: "var(--space-4)" }}>
            {runError}
          </p>
        )}

        {activeRun ? (
          <RunProgressPanel
            run={activeRun}
            onCancel={() => void handleCancelRun()}
            cancelling={cancelling}
          />
        ) : null}
      </section>

      <section
        className="card"
        aria-labelledby="demo-heading"
        style={{ marginTop: "var(--space-5)" }}
      >
        <div className="card__header">
          <h2 id="demo-heading">See it working first</h2>
        </div>
        <p className="card__hint">
          The demo runs a sample helpdesk app twice — a healthy version and a broken one — so you
          can see a GO and a NO-GO report without configuring anything.
        </p>
        <DemoPanel />
      </section>
    </>
  );
}
