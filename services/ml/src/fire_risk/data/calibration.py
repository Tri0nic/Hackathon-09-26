"""Deterministic train-only quality calibration and frozen JSON artifacts."""

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from hashlib import sha256
from math import ceil
from pathlib import Path

import polars as pl

from fire_risk.data.quality import QualityThresholds

SCHEMA_VERSION = "fire-risk-quality-thresholds-v1"
CALIBRATION_VERSION = "train-p95-linear-v1"
TRAIN_PERIODS = (
    "2019-01-01..2020-12-31",
    "2021-01-01..2021-12-31 (admissible intervals only)",
    "2022-01-01..2024-12-31",
)
_METRICS = (
    "event_count",
    "max_repeats_per_second",
    "longest_identical_state_run",
    "event_rate_deviation",
)
_RATIONALE = (
    "Train 2019-2024 only, retaining admissible 2021 channel-days; exclude only "
    "pre-existing historical_artifact/exclude_from_fire_training flags. "
    "Use the linear 95th percentile of each eligible channel-day metric; ceil "
    "integer cutoffs, round rate deviation to 12 decimal places, enforce schema "
    "floors (counts >= 2, rate >= 2.0). Null rate deviations (no prior history) "
    "do not contribute; an entirely null rate uses the schema floor. No sampling "
    "or sentinel discovery; seed is recorded for provenance."
)


class CalibrationLeakageError(ValueError):
    """A calibration input includes unknown or out-of-train source years."""


@dataclass(frozen=True)
class CalibratedThresholds:
    schema_version: str
    calibration_version: str
    train_periods: tuple[str, ...]
    source_sha256: dict[str, str]
    seed: int
    rationale: str
    implementation_revision: str
    thresholds: QualityThresholds

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("Unsupported schema_version")
        if self.calibration_version != CALIBRATION_VERSION:
            raise ValueError("Unsupported calibration_version")
        if self.train_periods != TRAIN_PERIODS:
            raise ValueError("Unexpected train_periods")
        if type(self.seed) is not int:
            raise ValueError("seed must be an integer")
        for name in ("rationale", "implementation_revision"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be nonempty")
        if not isinstance(self.thresholds, QualityThresholds):
            raise TypeError("thresholds must be QualityThresholds")
        if not isinstance(self.source_sha256, dict) or not self.source_sha256:
            raise ValueError("source_sha256 must contain source hashes")
        for name, digest in self.source_sha256.items():
            if (
                not isinstance(name, str)
                or not name.strip()
                or not isinstance(digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            ):
                raise ValueError("source_sha256 requires source names and SHA-256 hex")
        object.__setattr__(
            self, "source_sha256", dict(sorted(self.source_sha256.items()))
        )


def _source_revision() -> str:
    """Source digest is usable outside Git; orchestrators may pass a Git revision."""
    root = Path(__file__).parent
    return (
        "sha256:"
        + sha256(
            (root / "calibration.py").read_bytes() + (root / "quality.py").read_bytes()
        ).hexdigest()
    )


def calibrate_thresholds(
    profiles: pl.LazyFrame | pl.DataFrame,
    source_hashes: Mapping[str, str],
    seed: int,
    *,
    implementation_revision: str | None = None,
) -> CalibratedThresholds:
    """Reject mixed splits before metric access; calibrate only supplied train rows.

    Callers must select train sources before profiling; filtering a mixed-year
    profile after it was aggregated cannot undo contaminated historical metrics.
    source_year is the source journal year, not a UTC-derived calendar year.
    """
    lazy = profiles.lazy() if isinstance(profiles, pl.DataFrame) else profiles
    schema = lazy.collect_schema()
    required = {"source_year", *_METRICS}
    if missing := required.difference(schema.names()):
        raise ValueError(f"Missing calibration profile columns: {sorted(missing)}")
    if not schema["source_year"].is_integer():
        raise CalibrationLeakageError("source_year must be an integer in 2019-2024")
    invalid_years = (
        lazy.select("source_year")
        .filter(
            pl.col("source_year").is_null()
            | ~pl.col("source_year").is_between(2019, 2024)
        )
        .unique()
        .collect()
    )
    if invalid_years.height:
        raise CalibrationLeakageError(
            f"source_year outside train 2019-2024: {invalid_years['source_year'].to_list()}"
        )
    admissible = pl.lit(True)
    for flag in ("historical_artifact", "exclude_from_fire_training"):
        if flag in schema:
            if schema[flag] != pl.Boolean:
                raise ValueError(f"{flag} must be Boolean")
            admissible &= ~pl.col(flag).fill_null(False)
    selected = lazy.filter(admissible).select(_METRICS)
    for metric in _METRICS:
        if not schema[metric].is_numeric():
            raise ValueError(f"{metric} must be numeric")
    invalid_metrics = [
        (~pl.col(name).is_finite())
        | (pl.col(name) < (0 if name == _METRICS[-1] else 1))
        | (pl.col(name).is_null() if name != _METRICS[-1] else pl.lit(False))
        for name in _METRICS
    ]
    check = (
        selected.select(
            pl.len().alias("count"),
            pl.any_horizontal(invalid_metrics).any().alias("invalid"),
        )
        .collect()
        .row(0, named=True)
    )
    if check["count"] == 0:
        raise ValueError("No admissible train profiles")
    if check["invalid"]:
        raise ValueError(
            "Profile metrics must be finite, nonnegative and counts nonnull"
        )
    quantiles = (
        selected.select(
            pl.col(name).quantile(0.95, interpolation="linear").alias(name)
            for name in _METRICS
        )
        .collect()
        .row(0, named=True)
    )
    thresholds = QualityThresholds(
        min_burst_events=max(
            QualityThresholds.MIN_COUNT, ceil(quantiles["event_count"])
        ),
        max_repeats_per_second=max(
            QualityThresholds.MIN_COUNT, ceil(quantiles["max_repeats_per_second"])
        ),
        min_stuck_run=max(
            QualityThresholds.MIN_COUNT, ceil(quantiles["longest_identical_state_run"])
        ),
        max_event_rate_deviation=max(
            QualityThresholds.MIN_RATE_DEVIATION,
            round(
                quantiles["event_rate_deviation"]
                or QualityThresholds.MIN_RATE_DEVIATION,
                12,
            ),
        ),
    )
    return CalibratedThresholds(
        SCHEMA_VERSION,
        CALIBRATION_VERSION,
        TRAIN_PERIODS,
        dict(source_hashes),
        seed,
        _RATIONALE,
        implementation_revision or _source_revision(),
        thresholds,
    )


def write_calibration(path: Path, value: CalibratedThresholds) -> None:
    """Persist canonical UTF-8 JSON (sorted keys, finite floats, LF newline)."""
    payload = json.dumps(
        asdict(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    path.write_bytes((payload + "\n").encode("utf-8"))


def read_calibration(path: Path) -> CalibratedThresholds:
    """Validate a supported frozen artifact without recalculating any cutoff."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    try:
        if set(payload["thresholds"]) != {
            field.name for field in fields(QualityThresholds)
        }:
            raise ValueError("Frozen thresholds must explicitly include every cutoff")
        payload["thresholds"] = QualityThresholds(**payload["thresholds"])
        payload["train_periods"] = tuple(payload["train_periods"])
        return CalibratedThresholds(**payload)
    except (KeyError, TypeError) as exc:
        raise ValueError("Invalid calibration artifact") from exc
