# GreenLit — five-minute demo script

Every step below is exercised by a command in this repo: the Playwright suite
(`frontend/tests`, 16 tests in 10 specs) or a backend/frontend unit test. Nothing here is
scripted or precomputed. The last section says what is **not** proven.

## Before you start (do this once, off camera)

```bash
docker compose up --build -d          # web on 5177, api on 8003
docker compose --profile demo up -d   # the two helpdesk demo apps
```

Wait for `docker compose ps` to show the api as `healthy`, then open
<http://localhost:5177>. Keep a terminal with `docker compose logs -f api worker` handy.

---

## 1. Register (20 s) — the first account is the admin

1. On the sign-in page press **Create an account** (or open `/register`).
2. Enter a name, an email like `demo@example.com` and a password of 12+ characters, press
   **Create account**.

**Expected:** you land on **New Test** signed in. Because the database is fresh, this
account is `admin`: **Settings** shows the **Audit log** tab, which is admin-only.

*If it goes wrong:* a "already registered" error means the volume is not fresh — sign in
with that account instead; the demo does not need the admin role except for step 3.

## 2. Try the demo — GO and NO-GO with no model (60 s)

1. On **New Test**, press **Try the demo**.

**Expected after ~30–60 s, side by side:** the healthy app shows **Go**, score **1.00**, reason
naming *"GO threshold 0.80"*; the broken app shows **No-Go** with a score below 1.00 and a
reason that names the **weighted score** and the **REVIEW threshold 0.60**. No provider and
no key are involved.

*If it goes wrong:* a red **demo app not reachable** banner means the two demo containers are
down — `docker compose --profile demo up -d` and press **Try the demo** again.

## 3. Settings → Providers and models (30 s)

1. **Settings → Providers and models → Use Ollama defaults → Add provider** (kind `ollama`,
   base URL `http://host.docker.internal:11434/v1`, model `hermes3:8b`).
2. Press **Test connection**.

**Expected:** a green **healthy** badge. Keys are encrypted at rest and never returned.

*If it goes wrong:* "unreachable" means Ollama is not running (`ollama list`) or the model
name differs — the badge is a live call, not a cached status.

## 4. New Test over HTTP, with auto-detect (60 s)

1. **New Test** → entry point **HTTP endpoint**.
2. Target URL: your app's chat endpoint (for the demo stack,
   `http://host.docker.internal:9301/chat`), tick **runs on my computer**.
3. Press **Start test**.

**Expected:** a detection panel appears with the request shape it guessed (question field and
answer path). Choose an approved dataset, press **Start test** again: the progress panel runs
case by case, then the verdict card with the word, the score, the reason rule, the metric table
and the failed cases.

*If it goes wrong:* "cannot reach" for `localhost` means you forgot **runs on my computer**,
or the address must be `host.docker.internal` because the API runs in a container.

## 5. Upload outputs (45 s)

1. **New Test** → entry point **Upload outputs (CSV/JSON)**.
2. Drop a CSV with `input,output` columns (extra columns are fine).

**Expected:** the detected columns appear as badges and `input`/`output` are mapped
automatically; pick the same approved dataset, press **Start test** → progress panel, then
**Go**, score **1.00**, and `answer match` in the metric table. Uploaded files are scored
against the dataset, so missing rows are reported as failures with a reason, never as zeros.

*If it goes wrong:* "column not found" means the header row is missing — map the columns by
hand in the mapping view; the run then proceeds the same way.

## 6. The Safety section (30 s)

1. Open the finished run (**Results** → the run) and scroll to **Safety**.

**Expected:** attacks tried and resisted, the over-refusal rate on the harmless prompts, and
the list of failed critical checks (empty for a guarded app). A vulnerable app that leaks the
canary is a **No-Go** whose reason names the safety gate.

*If it goes wrong:* "not instrumented" means the run was started with only the quality test
type — rerun with **Safety** ticked.

## 7. The Judge (45 s)

1. **Settings → Judge** → pick the saved provider and model, press **Save judge** (the first
   profile is selected automatically, so new runs use it).
2. Run a test again (step 4 or 5).

**Expected:** the verdict card names the **judge model** and the **rubric version**; there is
no "judge skipped" note. Choosing the same model the app uses shows the self-grading warning.

*If it goes wrong:* "judge skipped" on the card means no profile is selected; a judge error
never fails the run — those cases fall to **Review**.

## 8. Baseline and BLOCK (45 s)

1. **Results** → open the healthy demo run → **Set as baseline**.
2. Run the broken demo app against the same dataset version.

**Expected:** the broken run's card shows regression status **Block**, a reason saying a
metric dropped *beyond the* tolerance, and the metric deltas naming **answer match**; the
baseline name is shown next to it. The same comparison is in the HTML export.

*If it goes wrong:* no status means the two runs are on different dataset versions — a
baseline only compares within one version.

## 9. Calibration (45 s)

1. **Calibration** in the sidebar.

**Expected:** the queue lists the cases the judge could not settle, each with a reason such as
*"the judge was unsure about this case"*. Press **Approve** on one and **Reject** on another:
the labelled count becomes **2** and the panel shows raw agreement and **Cohen's kappa** with a
plain-language reading.

*If it goes wrong:* **No labelled cases yet** just means the queue is empty — the demo runs are
fully settled; use a run where the judge was unavailable.

## 10. Export the report (20 s)

1. On any verdict page press **Export → HTML**.

**Expected:** `greenlit-run-<id>.html` downloads and opens offline: inline CSS only, no
external request, containing the verdict, the weighted score, *"GO threshold 0.80"*, the
dataset name, the connector, the metric table, the safety section and (when used) the judge
model and rubric version. No header or key ever appears in it.

*If it goes wrong:* a **403/404** means the run belongs to another account — reports are
owner-scoped.

---

## What is not proven by a test

The **JSON and CSV export buttons** are covered by pytest only (a browser download test exists
for HTML), the **Set as baseline** button click is covered by its Vitest component test while
Playwright proves the stored comparison through the API, and **Test Chat**, the **"soon"**
entry points (Python function, RAG app, SDK, Docker image, Git repo, CLI) and the user
administration screen do not exist yet — the UI marks them "soon" rather than faking them.
