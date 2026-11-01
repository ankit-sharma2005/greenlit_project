/**
 * Shared fixtures for the Playwright suite: accounts, datasets and fake apps.
 *
 * Everything here runs against the disposable stack (`scripts/run-e2e.sh`) and
 * needs no real model: the HTTP fixtures below are ordinary JSON servers, and
 * `startFakeProvider` speaks the OpenAI-compatible chat shape the gateway uses.
 */

import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";

import { expect, request, type Page } from "@playwright/test";

import { GUARDED_REFUSAL, isDisallowed } from "./guard";

export const WEB = process.env.E2E_BASE_URL ?? "http://localhost:5177";
export const API = process.env.E2E_API_URL ?? "http://localhost:8003";
/** Host the API uses to reach a fake app started here (docker: host.docker.internal). */
export const TARGET_HOST = process.env.E2E_TARGET_HOST ?? "127.0.0.1";
export const PASSWORD = "password123456";
/** e2e-admin.spec.ts registers this account first; it is the admin. */
export const ADMIN_EMAIL = "admin@example.com";

export const GOLDEN_ANSWERS: Record<string, string> = {
  "What is GreenLit?": "GreenLit tests LLM apps before launch.",
  "Is it fast?": "Yes, it runs in a worker.",
};

/** Two cases whose expected answers the fixtures below return verbatim.
 *
 * The answers are quoted because they contain a comma: an unquoted comma is a
 * second CSV field, and both the dataset and upload readers would score the
 * truncated text before it. */
export const GOLDEN_CSV = [
  "question,answer",
  '"What is GreenLit?","GreenLit tests LLM apps before launch."',
  '"Is it fast?","Yes, it runs in a worker."',
].join("\n");

export interface FakeApp {
  port: number;
  close: () => Promise<void>;
}

type Reply = Record<string, unknown> | null;

/**
 * Tiny JSON app: the handler decides the reply, a null reply means HTTP 400.
 *
 * Bound on all interfaces so an API running in Docker can reach it too.
 */
export function startApp(
  reply: (data: Record<string, unknown>) => Reply,
  delayMs = 0,
): Promise<FakeApp> {
  return new Promise((resolve, reject) => {
    const server = createServer((req: IncomingMessage, res: ServerResponse) => {
      if (req.method === "POST") {
        let body = "";
        req.on("data", (chunk) => {
          body += chunk;
        });
        req.on("end", () => {
          let payload: Reply = null;
          try {
            payload = reply(JSON.parse(body) as Record<string, unknown>);
          } catch {
            payload = null;
          }
          if (payload === null) {
            res.writeHead(400);
            res.end();
            return;
          }
          const answer = () => {
            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(JSON.stringify(payload));
          };
          if (delayMs > 0) {
            setTimeout(answer, delayMs);
          } else {
            answer();
          }
        });
        return;
      }
      res.writeHead(200);
      res.end("ok");
    });
    server.on("error", reject);
    server.listen(0, "0.0.0.0", () => {
      const addr = server.address() as AddressInfo;
      resolve({
        port: addr.port,
        close: () => new Promise<void>((done) => server.close(() => done())),
      });
    });
  });
}

/** A healthy app: right answers, retrieved context, and a guardrail. */
export function startGuardedApp(delayMs = 0): Promise<FakeApp> {
  return startApp((data) => {
    const question = typeof data.question === "string" ? data.question : "";
    if (isDisallowed(question)) {
      return { answer: GUARDED_REFUSAL, context: "The helpdesk declines harmful requests." };
    }
    const answer = GOLDEN_ANSWERS[question] ?? "I am not sure about that.";
    return { answer, context: `${answer} (helpdesk handbook)` };
  }, delayMs);
}

/**
 * A vulnerable app: it repeats whatever it was asked, prompt injection and all.
 *
 * That is how a canary attack succeeds — the planted marker comes back in the
 * output — so the safety probes must hand this app a NO-GO.
 */
export function startEchoApp(): Promise<FakeApp> {
  return startApp((data) => {
    const question = typeof data.question === "string" ? data.question : "";
    return { answer: question, context: "Echoed back verbatim." };
  });
}

/**
 * A chatbot that streams its answer as Server-Sent Events.
 *
 * The real shape a company website uses: several `data:` events, each carrying
 * one piece of the answer, then `[DONE]`. The text is split so the client must
 * join the stream instead of reading one body.
 */
export function startStreamingApp(): Promise<FakeApp> {
  return new Promise((resolve, reject) => {
    const server = createServer((req: IncomingMessage, res: ServerResponse) => {
      if (req.method !== "POST") {
        res.writeHead(200);
        res.end("ok");
        return;
      }
      let body = "";
      req.on("data", (chunk) => {
        body += chunk;
      });
      req.on("end", () => {
        let question = "";
        try {
          const payload = JSON.parse(body) as { question?: string };
          question = payload.question ?? "";
        } catch {
          question = "";
        }
        const answer = GOLDEN_ANSWERS[question] ?? "I am not sure about that.";
        const pieces = answer.match(/.{1,12}/g) ?? [answer];
        res.writeHead(200, {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
        });
        let index = 0;
        const writeNext = () => {
          if (index < pieces.length) {
            res.write(`data: ${JSON.stringify({ token: pieces[index] })}\n\n`);
            index += 1;
            setTimeout(writeNext, 10);
            return;
          }
          res.write("data: [DONE]\n\n");
          res.end();
        };
        writeNext();
      });
    });
    server.on("error", reject);
    server.listen(0, "0.0.0.0", () => {
      const addr = server.address() as AddressInfo;
      resolve({
        port: addr.port,
        close: () => new Promise<void>((done) => server.close(() => done())),
      });
    });
  });
}

export interface FakeProviderOptions {
  /** Answers for the app under test, keyed by a substring of the question. */
  answers?: Record<string, string>;
  /** What to reply when the request is the judge's rubric prompt. */
  judgeReply?: { score: number; reason: string; confidence: number };
  /** What to reply when Dataset Studio asks for generated cases. */
  generationReply?: string;
  /** Token usage the fake reports; defaults to 120 in / 40 out. */
  usage?: { prompt_tokens?: number; completion_tokens?: number };
}

/**
 * An OpenAI-compatible chat endpoint, so a run needs no real model.
 *
 * The gateway posts to `<base_url>/chat/completions`. A judge call is recognised
 * by its rubric system message (it is the only prompt that asks for a bare JSON
 * object), so one server can act as both the app and its judge.
 */
export function startFakeProvider(options: FakeProviderOptions = {}): Promise<FakeApp> {
  const answers = options.answers ?? {};
  const judgeReply = options.judgeReply ?? {
    score: 1,
    reason: "The answer states the expected fact.",
    confidence: 0.95,
  };
  return new Promise((resolve, reject) => {
    const server = createServer((req: IncomingMessage, res: ServerResponse) => {
      if (req.method !== "POST" || req.url !== "/v1/chat/completions") {
        res.writeHead(404);
        res.end();
        return;
      }
      let body = "";
      req.on("data", (chunk) => {
        body += chunk;
      });
      req.on("end", () => {
        let messages: Array<{ role: string; content: string }> = [];
        try {
          const payload = JSON.parse(body) as { messages?: typeof messages };
          messages = payload.messages ?? [];
        } catch {
          messages = [];
        }
        const system = messages
          .filter((message) => message.role === "system")
          .map((message) => message.content)
          .join("\n");
        const userMessages = messages.filter((message) => message.role === "user");
        const question = userMessages[userMessages.length - 1]?.content ?? "";
        const isJudge = system.includes("Reply with ONLY a JSON object");
        const isGeneration = system.includes("You write evaluation test cases");
        let content: string;
        if (isJudge) {
          content = JSON.stringify(judgeReply);
        } else if (isGeneration && options.generationReply !== undefined) {
          content = options.generationReply;
        } else if (isDisallowed(question)) {
          content = GUARDED_REFUSAL;
        } else {
          content =
            Object.entries(answers).find(([asked]) => question.includes(asked))?.[1] ??
            "GreenLit tests LLM apps before launch.";
        }
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(
          JSON.stringify({
            id: "fake-chat",
            object: "chat.completion",
            created: Math.floor(Date.now() / 1000),
            model: "fake-model",
            choices: [{ index: 0, message: { role: "assistant", content }, finish_reason: "stop" }],
            // A real provider reports usage; the operations block and the cost
            // estimate need it, so the fake one does too.
            usage: {
              prompt_tokens: options.usage?.prompt_tokens ?? 120,
              completion_tokens: options.usage?.completion_tokens ?? 40,
              total_tokens:
                (options.usage?.prompt_tokens ?? 120) + (options.usage?.completion_tokens ?? 40),
            },
          }),
        );
      });
    });
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address() as AddressInfo;
      resolve({
        port: addr.port,
        close: () => new Promise<void>((done) => server.close(() => done())),
      });
    });
  });
}

/** Register a fresh account and land on the signed-in app. */
export async function register(page: Page, name: string, email: string): Promise<void> {
  await page.goto(`${WEB}/register`);
  await page.fill('#register-name, input[name="name"]', name);
  await page.fill('#register-email, input[type="email"], input[name="email"]', email);
  await page.fill('#register-password, input[type="password"]', PASSWORD);
  const registered = page.waitForResponse(
    (response) => response.url().includes("/api/v1/auth/register") && response.status() === 201,
  );
  await page.click('button[type="submit"]');
  await (await registered).json();
  await page.waitForURL((url) => !url.pathname.includes("/register"), { timeout: 15_000 });
}

/**
 * Create the admin account when this spec runs on its own.
 *
 * The first account on a fresh database is the admin. When the whole suite runs
 * in order, e2e-admin.spec.ts has already registered it and this is a no-op.
 */
export async function ensureAdmin(): Promise<void> {
  const api = await request.newContext({ baseURL: API });
  try {
    const created = await api.post("/api/v1/auth/register", {
      data: { email: ADMIN_EMAIL, name: "Admin", password: PASSWORD },
    });
    expect([201, 409]).toContain(created.status());
  } finally {
    await api.dispose();
  }
}

/** Sign in through the form (e2e-admin.spec.ts, or `ensureAdmin`, seeds the account). */
export async function login(page: Page, email: string): Promise<void> {
  await page.goto(`${WEB}/login`);
  await page.fill("#login-email", email);
  await page.fill("#login-password", PASSWORD);
  const signedIn = page.waitForResponse(
    (response) => response.url().includes("/api/v1/auth/login") && response.status() === 200,
  );
  await page.click('button[type="submit"]');
  await signedIn;
  await page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 15_000 });
}

/** Upload a CSV and approve version 1, using the signed-in session's cookies. */
export async function uploadApprovedDataset(
  page: Page,
  name: string,
  csv: string,
): Promise<{ rows: number; label: string }> {
  const created = await page.request.post(`${API}/api/v1/datasets`, {
    multipart: {
      name,
      file: { name: "golden.csv", mimeType: "text/csv", buffer: Buffer.from(csv) },
    },
  });
  expect(created.status(), await created.text()).toBe(201);
  const dataset = (await created.json()) as { id: string };
  const approved = await page.request.post(
    `${API}/api/v1/datasets/${dataset.id}/versions/1/approve`,
  );
  expect(approved.status(), await approved.text()).toBe(200);
  const rows = Math.max(csv.trim().split("\n").length - 1, 0);
  return { rows, label: `${name} · v1 (${rows} cases)` };
}

/** Save a provider as the signed-in (admin) user and return its id. */
export async function createProvider(
  page: Page,
  fields: {
    name: string;
    model: string;
    baseUrl: string;
    connector?: string;
    /** The provider's own limit; the local doubles absorb the 64 safety probes. */
    rateLimitPerMinute?: number;
  },
): Promise<string> {
  const created = await page.request.post(`${API}/api/v1/providers`, {
    data: {
      name: fields.name,
      kind: "openai-compatible",
      model_name: fields.model,
      base_url: fields.baseUrl,
      connector: fields.connector ?? "prompt_app",
      timeout_seconds: 30,
      rate_limit_per_minute: fields.rateLimitPerMinute ?? 600,
      is_active: true,
    },
  });
  expect(created.status(), await created.text()).toBe(201);
  return ((await created.json()) as { id: string }).id;
}

/** Save a judge profile for the signed-in user and return its id. */
export async function createJudgeProfile(
  page: Page,
  fields: { name: string; providerId: string; model: string },
): Promise<string> {
  const created = await page.request.post(`${API}/api/v1/judge-profiles`, {
    data: { name: fields.name, provider_id: fields.providerId, model: fields.model },
  });
  expect(created.status(), await created.text()).toBe(201);
  return ((await created.json()) as { id: string }).id;
}

/** Select the judge profile a run should use after creating it. */
export async function selectJudgeProfile(page: Page, profileId: string): Promise<void> {
  const selected = await page.request.post(`${API}/api/v1/judge-profiles/${profileId}/select`);
  expect(selected.status(), await selected.text()).toBe(200);
}

/** Land on the New Test page, failing loudly if the session did not survive. */
export async function openNewTestPage(page: Page): Promise<void> {
  await page.goto(`${WEB}/`);
  const outcome = await Promise.race([
    page
      .waitForSelector('[data-testid="connector-select"]', { timeout: 20_000 })
      .then(() => "ready" as const),
    page
      .waitForSelector('input[type="password"]', { timeout: 20_000 })
      .then(() => "login" as const),
  ]);
  if (outcome === "login") {
    throw new Error(`Redirected to the login page at ${page.url()} while ${WEB}/ was expected.`);
  }
}

/** Point the one-box flow at a fake HTTP app and press Start test until it detects. */
export async function detectTarget(page: Page, app: FakeApp): Promise<void> {
  await page.selectOption('[data-testid="connector-select"]', "http_endpoint");
  await page.fill('[data-testid="target-url"]', `http://${TARGET_HOST}:${app.port}/chat`);
  await page.check("#runs-on-my-computer");
  await page.click('[data-testid="start-test"]');
  await expect(page.getByTestId("detect-result")).toBeVisible({ timeout: 60_000 });
}
