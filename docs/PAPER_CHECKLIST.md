# Reproducibility checklist for the paper

Everything here is a step the repository can already do; nothing below asks for a tool that
does not exist. Where the harness records a value automatically, the file that holds it is
named. Where it does not, the value has to be written down by hand before the run.

## 1. Record these versions and settings for every experiment

| What | Where it comes from | Recorded automatically? |
| --- | --- | --- |
| GreenLit commit | `git rev-parse HEAD` in the repository that served the run | no — put it in the caption |
| Criteria profile and its version | `GET /api/v1/criteria` (the same source the Criteria tab reads); the run stores the profile key, the weights, thresholds and hard gates | yes — `manifest.json` → `criteria` |
| Safety set version | `backend/app/safety/data/attacks.json` and `safe_prompts.json`; both are versioned and the version is copied into each run's `attack_resisted` / `over_refusal` details (`set_version`) | yes — in the run and the report's Safety block |
| Judge provider and model | `GET /api/v1/judge-profiles` / the run's selected judge; the run stores model, provider, rubric version and prompt hash | yes — `manifest.json` → `judge`, and each run's `settings_snapshot.judge` |
| Judge rubric version and prompt hash | `backend/app/services/judge.py` (`JUDGE_RUBRIC_VERSION`) and the profile's stored `prompt_template_hash` | yes — in the run snapshot |
| Generator model, if a model wrote the data | the dataset draft / prompt-app settings used before the run | no — record it by hand; the ten experiment apps are rule-based and call no model |
| App models | `experiments/apps/app_config/*.json` are rule-based servers with **no model and no network**; the behaviour is fixed by the config's `seed` and `fault` | partly — `manifest.json` → `apps[].seed`, `apps[].fault` |
| N repeats | `python experiments/runner/run_experiment.py --runs N` | yes — `manifest.json` → `runs_per_app` |
| Seeds | the app seeds above; the analysis bootstrap is seeded and uses 1000 resamples | yes for the analysis; `--seed` on `make_label_sheet.py` |
| Dates | run start and finish | yes — `manifest.json` → `started_at`, `finished_at` |
| Hardware | the machine that ran GreenLit, the worker and the ten local apps | no — record CPU/GPU/RAM/OS by hand |
| Dataset | `experiments/data/questions.csv` (120 cases) uploaded as `experiments-questions-120`, version approved | yes — `manifest.json` → `dataset` |

A run whose manifest is missing any automatic value above is not reportable: say the value
is missing rather than filling it in from memory.

## 2. Lock the ground truth before the first run

1. Regenerate the declared truth from the app configs:
   `python experiments/build_ground_truth.py` → `experiments/data/ground_truth.json`.
2. Read `experiments/data/ground_truth.json` and check every app's `expected_verdict`,
   `expected_reason` and `uncertain_truth` against its config. Do this **once**, before any
   run.
3. Tag the commit that holds the locked truth:
   `git tag experiment-ground-truth-v1` (and push the tag if the paper refers to it).
4. From then on, never edit an expected verdict after a run has been scored. If the truth
   was wrong, tag `experiment-ground-truth-v2`, re-run everything, and report both versions
   — do not patch v1 in place.
5. Keep the run directory (`experiments/results/<timestamp>/`) unmodified. The analysis
   reads it; nothing writes back into it.

## 3. Blind labelling, two raters

1. Run the experiment first: `experiments/results/<timestamp>/<app>/run-<n>.cases.csv` holds
   each case's question and the judge's own label.
2. Produce one sheet per rater, shuffled with a fixed seed and **without** the app id or the
   judge's label:
   `python experiments/analysis/make_label_sheet.py experiments/results/<timestamp> --rater rater1`
   (repeat with `--rater rater2`; `--seed` defaults to `20261110`).
3. Each rater fills `pass`, `fail` or `unsure` — and nothing else. The template is
   `experiments/data/human_labels_TEMPLATE.csv`.
4. Merge the filled sheets: `python experiments/analysis/make_label_sheet.py --merge`.
5. Analyse: `python experiments/analysis/analyze.py experiments/results/<timestamp>`. It
   reports rater-versus-rater kappa over shared cases, keeps `unsure` as its own answer on
   both sides, and says "one rater only" instead of inventing agreement when a second sheet
   is missing.

## 4. What the paper must report

1. **The false-GO rate first** — how often a run said GO when the locked truth said not-GO —
   with its n (`verdict_summary.csv` → `false_go`).
2. **Confusion matrices with n** over NO_GO / REVIEW / GO, never a bare percentage
   (`verdict_matrix.csv`). A cell with fewer than five cases carries a warning instead of a
   rate.
3. **Bootstrap 95 % intervals** on accuracy, not-GO recall and false-GO rate — 1000 seeded
   resamples, point estimate and n beside each interval (`bootstrap.csv`).
4. **Test–retest agreement** across the repeated runs of the same app
   (`test_retest.csv`): the same verdict every time, or the disagreement named.
5. **`unsure` shown separately** and never folded into pass or fail, for both the judge and
   the human labels.
6. **Judge versus human** with accuracy, precision, recall, F1 and quadratic-weighted kappa
   (`python -m pytest experiments/tests` covers the arithmetic; `analyze.py` prints the
   comparison once labels exist).
7. The manifest's versions, seeds and dates, and the hardware note, in the appendix.

## 5. Limits to state plainly

- The sample is **small and controlled**: ten author-built apps, 120 fixed questions, a few
  repeated runs each. It supports a claim about these apps, not a population.
- The apps and the ground truth were **built by the same authors** as GreenLit. The
  expectation is declared in each config before the run, but it is not independent.
- **No real company application was tested.** The connector handles a real endpoint; the
  evaluation does not include one.
- **Other frameworks are not compared.** The numbers describe GreenLit's verdicts against
  its own truth, not its accuracy relative to another tool.
- A run that hit a limit is `stopped_by_limit` and covers only the cases that ran; it is
  never counted as a full-dataset result.
- A metric the app never reported (token counts, retrieved context) is **not measured**: it
  is left out of the weighted score and never counted as zero, so a run with missing
  instrumentation has a thinner score, not a worse one. Say so wherever a score is quoted.
