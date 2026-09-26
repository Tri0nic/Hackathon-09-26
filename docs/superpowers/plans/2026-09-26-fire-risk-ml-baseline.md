# Fire Risk ML Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a resumable CatBoost training CLI and stable Python inference contract for proxy targets `now`, `6h`, `12h`, and `24h`.

**Architecture:** Polars performs temporal selection and deterministic sampling without loading the full Parquet at once. Four CatBoost models train sequentially, validation raw scores receive sigmoid calibration, and a JSON manifest plus native `.cbm` files form the versioned artifact. Inference loads that artifact, applies calibration and forecast monotonicity, and returns real feature-value explanations.

**Tech Stack:** Python 3.12, Polars, CatBoost, NumPy, scikit-learn, Pydantic 2, Typer, pytest.

**Spec:** `docs/superpowers/specs/2026-09-26-fire-risk-ml-baseline-design.md`

## Global Constraints

- Work only in `feature/data-foundation`; do not merge into `main`.
- Split by time: 2019–2024 train, 2025 validation, 2026 test.
- Exclude every non-null episode group present in more than one split.
- Fit sampling, fill values, class weights, calibration, and thresholds without test data.
- Mark all reported quality as proxy-label reproduction, not confirmed-fire detection.
- Train horizons sequentially and save each completed horizon for `--resume`.
- Keep FastAPI and exhaustive tuning out of scope.

## Review Focus

- A censored target row must be absent for that horizon: covered by Task 1 availability assertions.
- A group crossing 2024/2025 or 2025/2026 must appear nowhere: covered by Task 1 boundary-group assertions.
- Constant or single-class validation data must fail with a clear message: covered by Task 2 calibration assertions.
- Arbitrary model outputs must still satisfy `p_6h <= p_12h <= p_24h`: covered by Task 2 monotonicity assertions.
- Missing known and extra unknown inference fields must preserve the response schema: covered by Task 3 round-trip assertions.

---

### Task 1: Temporal Dataset Selection

**Files:**
- Create: `services/ml/src/fire_risk/ml/__init__.py`
- Create: `services/ml/src/fire_risk/ml/data.py`
- Test: `services/ml/tests/test_ml_data.py`

**Interfaces:**
- Consumes: feature-snapshot Parquet with timestamps, availability flags, targets, and episode groups.
- Produces: `feature_columns(schema) -> list[str]`, `split_frame(source, horizon) -> SplitFrames`, and `sample_training(frame, target, max_rows, seed) -> pl.DataFrame`.

- [ ] **Step 1: Write failing split tests**

Assert exact year assignment, removal of a group crossing a boundary, horizon-specific censorship removal, exclusion of identifiers/targets from feature columns, and deterministic class-aware sampling.

- [ ] **Step 2: Verify the tests fail**

Run: `python -m pytest tests/test_ml_data.py -q`
Expected: FAIL because `fire_risk.ml.data` does not exist.

- [ ] **Step 3: Implement the data boundary**

Define immutable `SplitFrames(train, validation, test, features)` and lazy Polars operations. Use a stable row hash from `object_id`, `scoring_timestamp`, horizon, and seed; keep positives and negatives deterministically up to the configured cap without using validation/test rows to fit training state.

- [ ] **Step 4: Verify Task 1**

Run: `python -m pytest tests/test_ml_data.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/ml/src/fire_risk/ml services/ml/tests/test_ml_data.py
git commit -m "feat(ml): add leak-free temporal datasets"
```

### Task 2: CatBoost Training, Calibration, and Metrics

**Files:**
- Modify: `services/ml/pyproject.toml`
- Create: `services/ml/src/fire_risk/ml/training.py`
- Test: `services/ml/tests/test_ml_training.py`

**Interfaces:**
- Consumes: `SplitFrames` from Task 1.
- Produces: `Calibration(coefficient, intercept, threshold)`, `calibrate(raw_scores, calibration) -> np.ndarray`, `enforce_monotonic(probabilities) -> dict[str, np.ndarray]`, and `train_all(config) -> Path`.

- [ ] **Step 1: Write failing training-utility tests**

Assert sigmoid outputs remain in `[0, 1]`, single-class calibration raises `ValueError`, validation-F1 threshold is stored, and monotonic correction returns cumulative maxima while leaving `now` unchanged.

- [ ] **Step 2: Verify the tests fail**

Run: `python -m pytest tests/test_ml_training.py -q`
Expected: FAIL because training utilities do not exist.

- [ ] **Step 3: Add runtime dependencies**

Add `catboost>=1.2,<2`, `numpy>=1.26,<3`, and `scikit-learn>=1.5,<2` to project dependencies.

- [ ] **Step 4: Implement sequential training**

Define `TrainingConfig` with defaults: seed `42`, train cap `1_000_000` rows per horizon, calibration cap `300_000`, `600` iterations, depth `8`, learning rate `0.08`, early stopping `75`, and progress every `25` iterations. Fit train medians and balanced class weights on train only; fit sigmoid calibration and F1 threshold on validation raw scores; evaluate the full eligible 2026 split; save each `.cbm` and horizon JSON atomically before moving to the next horizon.

- [ ] **Step 5: Implement metrics and resume validation**

Store row/positive counts, PR-AUC, ROC-AUC when defined, precision, recall, F1, Brier score, threshold, elapsed time, and `label_source: proxy`. Resume only when the model and horizon metadata match the input identity, feature schema, horizon, and configuration.

- [ ] **Step 6: Verify Task 2**

Run: `python -m pytest tests/test_ml_training.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add services/ml/pyproject.toml services/ml/src/fire_risk/ml/training.py services/ml/tests/test_ml_training.py
git commit -m "feat(ml): train calibrated catboost horizons"
```

### Task 3: Artifact, Inference Contract, CLI, and Smoke Run

**Files:**
- Create: `services/ml/src/fire_risk/ml/inference.py`
- Create: `services/ml/src/fire_risk/ml_cli.py`
- Create: `services/ml/tests/test_ml_artifact.py`
- Modify: `services/ml/README.md`

**Interfaces:**
- Consumes: four `.cbm` files and manifest generated by `train_all`.
- Produces: `load_predictor(path) -> Predictor`, `Predictor.predict(features, top_k=5) -> Prediction`, and CLI command `python -m fire_risk.ml_cli train`.

- [ ] **Step 1: Write failing artifact round-trip test**

Train tiny CPU models, load the artifact, predict with one missing known feature and one extra field, and assert model version, timestamp, all four probabilities, monotonic horizons, decisions, and factors containing actual input values.

- [ ] **Step 2: Verify the test fails**

Run: `python -m pytest tests/test_ml_artifact.py -q`
Expected: FAIL because inference and CLI modules do not exist.

- [ ] **Step 3: Implement manifest and inference**

Define Pydantic `Prediction`/`Factor` responses. Load native CatBoost models once, fill missing features from recorded train medians, ignore extras, apply stored sigmoid calibration, enforce cumulative forecast maxima, and obtain top absolute CatBoost SHAP contributions with feature values.

- [ ] **Step 4: Implement the CLI and documentation**

Expose input/output, CPU/GPU, seed, row caps, CatBoost parameters, and `--resume`. Print `[1/4]` through `[4/4]`, class counts, CatBoost progress, elapsed time, validation score, save path, and final metrics path. Document the exact PowerShell full-training and resume command.

- [ ] **Step 5: Run focused verification**

Run: `python -m pytest tests/test_ml_data.py tests/test_ml_training.py tests/test_ml_artifact.py -q`
Expected: PASS.

- [ ] **Step 6: Run quality checks**

Run: `python -m ruff check src tests` and `python -m mypy src` from `services/ml`.
Expected: both exit successfully.

- [ ] **Step 7: Run bounded CPU smoke training**

Run the CLI against the real Parquet with `--task-type CPU --train-max-rows 20000 --calibration-max-rows 10000 --iterations 20` into an ignored smoke directory.
Expected: four models and a manifest are written; prediction round trip succeeds. Do not claim production metrics from this run.

- [ ] **Step 8: Commit**

```bash
git add services/ml/src/fire_risk/ml/inference.py services/ml/src/fire_risk/ml_cli.py services/ml/tests/test_ml_artifact.py services/ml/README.md
git commit -m "feat(ml): add resumable training and inference CLI"
```
