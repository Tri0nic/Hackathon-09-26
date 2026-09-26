# Fire Risk ML Baseline — Minimal Design

## Goal

Train a reproducible hackathon baseline from `60-feature-snapshots.parquet` and
produce calibrated predictions for `now`, `6h`, `12h`, and `24h`. Metrics are
explicitly proxy-label reproduction metrics, not confirmed real-fire quality.

## Scope

- Four sequential `CatBoostClassifier` models, trained by one CLI command.
- Temporal split: 2019–2024 train, 2025 validation, 2026 test.
- Any non-null `episode_group_id` crossing split boundaries is excluded from
  every split to prevent episode leakage.
- Censored targets are excluded per horizon using the matching availability
  flag.
- Training uses a deterministic, class-aware row cap; validation and test
  evaluation remain deterministic.
- Sigmoid (Platt) calibration is fitted on validation predictions; the
  classification threshold maximising validation F1 is then stored per horizon.
- Forecast probabilities are corrected with cumulative maxima so that
  `p_6h <= p_12h <= p_24h`; `now` remains independent.
- User-facing factors come from CatBoost feature contributions and the actual
  feature values supplied for a prediction.
- Models, calibration parameters, feature schema, thresholds, split periods,
  metrics, seed, and package versions are stored in a versioned artifact.
- Stable Python `predict` function and CLI training entry point. FastAPI is
  intentionally deferred.

## Training Workflow

The CLI accepts input Parquet, output directory, CPU/GPU choice, seed, row
limits, and `--resume`. It trains `now`, `6h`, `12h`, and `24h` sequentially,
saving each completed horizon immediately. Console output reports the current
horizon, class balance, CatBoost progress, elapsed time, validation score, and
artifact path. A restarted run skips validated completed horizons.

GPU is the default recommendation for the available RTX 4070. The saved seed
and configuration make the run repeatable, while minor GPU floating-point
variation is documented rather than presented as bit-for-bit determinism.

## Metrics

For each horizon the report contains PR-AUC, ROC-AUC when both classes exist,
precision, recall, F1, Brier score, threshold, row counts, positive counts, and
the label source marker `proxy`. Metrics are calculated on the 2026 test split.
No target quality claim is made without the generated report.

## Artifact and Prediction Contract

The output directory contains one native CatBoost model per horizon plus a
JSON manifest. Prediction input is a mapping containing the saved numeric
feature schema. Output contains model version, calculation time, independent
`p_now`, monotonic `p_6h/p_12h/p_24h`, threshold decisions, and top factors.
Missing numeric features use the training-time fill values recorded in the
manifest; unknown extra fields are ignored.

## Minimal Verification

Only high-value automated checks are required:

1. Temporal split and cross-boundary episode exclusion.
2. Monotonic correction for forecast probabilities.
3. Artifact save/load and prediction-contract round trip on a tiny fixture.

A small CPU smoke run validates the full workflow before the user launches the
full sequential GPU training command.

## Deferred

FastAPI, exhaustive hyperparameter tuning, object holdout benchmarking, full
DATA-epic reporting, and production serving are outside this minimal stage.
