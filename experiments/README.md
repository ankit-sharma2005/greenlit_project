# Experiments: how accurate is GreenLit's verdict?

This folder measures **GreenLit**, not the apps. Ten tiny apps are written so their
correct verdict is known by construction, GreenLit judges them, and the analysis asks
how often it agreed — with the false-GO rate reported first, because calling a broken
app GO is the expensive mistake.

Nothing here changes GreenLit: no schema, no decision rule, no threshold, no dependency
of the backend or the frontend. The harness talks to a running GreenLit over its public
API, and the only network destinations are the local apps below and the GreenLit API.

## What is in here

```
apps/server.py            one app, behaviour from a JSON config
apps/behaviour.py         pure seeded behaviour (the same question is faulty every start)
apps/app_config/          app01..app10: port, seed, fault, expected verdict and reason
data/questions.csv        120 cases: 100 arithmetic + 20 fixed-fact questions
data/faq.json             the 20 facts the correct apps answer from
data/per_case_truth.json  which rows are faulty for app03/app05/app07, from the seed
data/ground_truth.json    every app's declared verdict — written before any run
build_ground_truth.py     regenerates that file from the configs
runner/                   cookie-session client + the experiment runner
analysis/                 checkers (number, key fact, canary) + the tables
tests/                    pytest, no Docker, no GreenLit, no model
results/                  outputs (git-ignored)
```

## Start the ten apps

The apps use only the Python standard library, so no virtualenv is needed for them:

```bash
for n in 01 02 03 04 05 06 07 08 09 10; do
  python experiments/apps/server.py --config experiments/apps/app_config/app$n.json &
done
```

Each one prints its port (9101–9110) and binds `0.0.0.0`, because the GreenLit API
container reaches it as `host.docker.internal`. **These apps are for local testing
only**: they have no authentication, no rate limit and no guard on purpose, and must
never be exposed beyond your machine. `app02` uses a local Ollama only if
`EXPERIMENT_OLLAMA_URL` is set (for example `http://host.docker.internal:11434`);
otherwise it answers deterministically and its truth is excluded anyway.

`app06` sleeps 4 s per request and `app07` returns HTTP 500 on one request in five, by
design. Stop all ten with `kill %1 … %10` (or close the shell).

## Run the experiment

Credentials come from the environment only — never from a flag, never printed:

```bash
export GREENLIT_API=http://localhost:8003      # default
export GREENLIT_EMAIL=experiment@example.com
export GREENLIT_PASSWORD='...'                  # keep it out of the repo

python experiments/runner/run_experiment.py --dry-run     # prints the plan, sends nothing
python experiments/runner/run_experiment.py --runs 5      # 5 repeats per app
```

On the first real run the runner uploads `data/questions.csv` as the dataset
`experiments-questions-120`, approves version 1, and reuses it afterwards. For each app
it creates (or updates) the saved target `exp-appNN`, sends one first-contact check
through GreenLit's own connector, then starts `--runs` runs with a unique
`Idempotency-Key` each — without that key GreenLit would collapse identical repeats
into one run. A run that hits the account's own cap is recorded as `stopped_by_limit`
and is not a failure; a 429 stops the experiment instead of looping.

Everything lands in `experiments/results/<timestamp>/`: `runs.csv`, `manifest.json`
(GreenLit health, criteria, the selected judge's provider and model, dataset version,
seeds, dates), and `<app>/run-<n>.csv` plus `run-<n>.report.json` copied from
GreenLit's own exports.

## Analyse

```bash
python experiments/analysis/analyze.py experiments/results/<timestamp>
```

It writes `verdict_matrix.csv`, `verdict_summary.csv`, `test_retest.csv`,
`categories.csv`, `bootstrap.csv` and `summary.md`. Every number is printed with its n;
the 95 % intervals come from 1000 seeded bootstrap resamples; a 2×2 cell with fewer
than five cases prints a warning instead of a rate. Human labels are read from
`data/human_labels.csv` if it exists — with no file, the report says "no human labels
yet" and invents nothing.

## What the tests prove

`python -m pytest experiments/tests` (57 tests, no Docker, no GreenLit, no model):

- each variant answers as its config says, and the seeded faulty set is identical across
  starts (`test_apps.py`, `test_ground_truth.py`);
- the dataset regenerates byte for byte, the per-case truth matches an independent
  recomputation from the seed, and no attack prompt was copied into it
  (`test_questions.py`);
- the checkers are exact — number extraction, key-fact containment, canary presence
  (`test_checkers.py`);
- the runner's dry run sends nothing, a full run exports every verdict and a manifest,
  the dataset is reused rather than re-uploaded, one repeat per app gets its own
  idempotency key, `stopped_by_limit` is recorded, a 429 stops it, and the password never
  appears in the output (`test_runner.py`, against a fake GreenLit);
- the analysis maths agrees with values computed by hand on a tiny results folder:
  the 3×3 matrix, accuracy, macro-F1, quadratic-weighted kappa, the false-GO rate,
  test–retest, the bootstrap intervals and the rater kappa (`test_analysis.py`).

## What is NOT proven

- **The sample is small and controlled.** Ten apps, five repeats each, 120 dataset
  cases: enough to exercise the machinery and to show where the engine disagrees, far
  too little to claim a population-level accuracy. The intervals in `bootstrap.csv` show
  how wide the uncertainty is; do not quote a point estimate without them.
- **The apps and the ground truth were written by the same author.** The declared
  verdicts are a considered opinion about what "should" ship (each config states its
  reason), and a different reviewer could argue app05's over-refusal deserves REVIEW
  rather than NO_GO. The declaration is fixed before any run, which prevents
  after-the-fact fitting, not author bias.
- **These are not real-world apps.** They are deterministic, single-endpoint, one-turn
  systems with no tools, sessions or retrieval beyond a fixed list. Nothing here says
  how GreenLit behaves on a real company chatbot, whose failures are not seeded.
- **Other frameworks are NOT yet compared.** promptfoo, DeepEval and garak exist and
  would be the natural baselines; this harness has not been run against them, so it
  makes no claim about being better, worse or equivalent.
- **Judge-versus-human is not measurable from the current export.** GreenLit exports
  per-run metrics, not a per-case judge label, so the analysis reports rater-versus-rater
  kappa only and says why.
