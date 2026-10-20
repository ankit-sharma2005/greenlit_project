# GreenLit demo verdict run

This demo uses the real verdict engine and the sample CSVs in this folder:

- `golden_dataset.csv` - the approved reference dataset
- `outputs_good.csv` - a passing output set
- `outputs_broken.csv` - a failing output set intentionally designed to miss the launch gate

## Run it

From the repository root:

```powershell
python backend\app\services\demo_verdict.py
```

The script loads the golden dataset, scores the good and broken outputs through the real metric + verdict engine, and prints the resulting verdict and reasons.

Expected outcome:

- GOOD => `GO`
- BROKEN => `NO_GO`

The verdict is driven by the real metrics and the configured thresholds in `app.phase5_schemas.DEFAULT_VERDICT_CRITERIA` (`go_threshold=0.8`, `review_threshold=0.6`). The broken example is intentionally low because it misses the answer match and context-recall checks and exceeds the latency budget, so it falls below the configured thresholds.

The `answer_match` metric is the normalized answer comparison metric used for free-text QA. It returns 1.0 for exact normalized equivalence and otherwise falls back to token-overlap and sequence-similarity scoring so valid paraphrases still pass when they preserve the same meaning; unrelated answers remain low-scoring. The old `answer_exact_match` name is still accepted as a legacy alias for older stored runs.

## Screens to capture

Use the app after signing in and opening a workspace/project:

1. Dataset Studio with the uploaded `golden_dataset.csv` loaded and approved
2. The evaluation run screen showing a new run created from the dataset
3. The Results/Reports page with the verdict banner (GO for the good outputs, NO_GO for the broken outputs)
4. The reasons panel showing the exact metric thresholds that caused the verdict

The demo is intentionally deterministic and does not hard-code a verdict; it calls the same evaluation engine used by the app.
