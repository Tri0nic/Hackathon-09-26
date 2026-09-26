"""Leak-free temporal datasets for model training."""

from dataclasses import dataclass

import polars as pl

_NON_FEATURES = {"object_id", "scoring_timestamp", "episode_group_id"}


@dataclass(frozen=True)
class SplitFrames:
    train: pl.LazyFrame
    validation: pl.LazyFrame
    test: pl.LazyFrame
    features: list[str]


def feature_columns(schema: pl.Schema) -> list[str]:
    """Return numeric and boolean model inputs, never identifiers or targets."""
    return [
        name
        for name, dtype in schema.items()
        if name not in _NON_FEATURES
        and not name.startswith("target_")
        and (dtype.is_numeric() or dtype == pl.Boolean)
    ]


def split_frame(source: pl.LazyFrame, horizon: str) -> SplitFrames:
    """Split by calendar year and remove groups crossing split boundaries."""
    target = f"target_{horizon}"
    available = f"{target}_available"
    schema = source.collect_schema()
    missing = {target, available, "episode_group_id"} - set(schema.names())
    if missing:
        raise ValueError(f"snapshot schema is missing: {sorted(missing)}")

    prepared = source.with_columns(
        pl.when(pl.col("scoring_timestamp").dt.year().is_between(2019, 2024))
        .then(pl.lit("train"))
        .when(pl.col("scoring_timestamp").dt.year() == 2025)
        .then(pl.lit("validation"))
        .when(pl.col("scoring_timestamp").dt.year() == 2026)
        .then(pl.lit("test"))
        .otherwise(pl.lit(None, dtype=pl.String))
        .alias("_split")
    )
    crossing = (
        prepared.filter(
            pl.col("episode_group_id").is_not_null() & pl.col("_split").is_not_null()
        )
        .group_by("episode_group_id")
        .agg(pl.col("_split").n_unique().alias("_split_count"))
        .filter(pl.col("_split_count") > 1)
        .select("episode_group_id")
    )
    eligible = (
        prepared.join(crossing, on="episode_group_id", how="anti")
        .filter(pl.col(available) & pl.col(target).is_not_null())
        .sort(["scoring_timestamp", "object_id"])
    )

    def part(name: str) -> pl.LazyFrame:
        return eligible.filter(pl.col("_split") == name).drop("_split")

    return SplitFrames(
        train=part("train"),
        validation=part("validation"),
        test=part("test"),
        features=feature_columns(schema),
    )


def sample_training(
    frame: pl.DataFrame | pl.LazyFrame,
    target: str,
    max_rows: int,
    seed: int,
) -> pl.DataFrame:
    """Select a deterministic balanced subset without depending on input order."""
    if max_rows <= 0:
        raise ValueError("max_rows must be positive")
    if isinstance(frame, pl.LazyFrame):
        names = frame.collect_schema().names()
        hash_columns = [
            name for name in ("object_id", "scoring_timestamp", target) if name in names
        ]
        counts = dict(
            frame.filter(pl.col(target).is_not_null())
            .group_by(target)
            .len()
            .collect()
            .iter_rows()
        )
        positive_quota = min(int(counts.get(True, 0)), max_rows // 2)
        negative_quota = min(
            int(counts.get(False, 0)), max_rows - positive_quota
        )
        positive_quota = min(
            int(counts.get(True, 0)), max_rows - negative_quota
        )

        def bounded(label: bool, quota: int) -> pl.DataFrame:
            count = int(counts.get(label, 0))
            selected = frame.filter(pl.col(target) == label)
            if 0 < quota < count:
                fraction = min(1.0, (quota / count) * 1.25)
                threshold = int(((2**64) - 1) * fraction)
                selected = selected.filter(
                    pl.struct(hash_columns).hash(seed=seed)
                    <= pl.lit(threshold, dtype=pl.UInt64)
                )
            return selected.head(quota).collect()

        sampled = pl.concat(
            [bounded(True, positive_quota), bounded(False, negative_quota)],
            how="vertical",
        )
        return sampled.sort(["scoring_timestamp", "object_id"])

    data = frame
    data = data.filter(pl.col(target).is_not_null())
    hash_columns = [
        name
        for name in ("object_id", "scoring_timestamp", target)
        if name in data.columns
    ]
    ranked = data.with_columns(
        pl.struct(hash_columns).hash(seed=seed).alias("_sample_hash")
    ).sort(["_sample_hash", *hash_columns])
    positive = ranked.filter(pl.col(target)).head(max_rows // 2)
    negative = ranked.filter(~pl.col(target)).head(max_rows - positive.height)
    remaining = max_rows - positive.height - negative.height
    if remaining:
        positive = ranked.filter(pl.col(target)).head(positive.height + remaining)
    return (
        pl.concat([positive, negative], how="vertical")
        .sort(["_sample_hash", *hash_columns])
        .drop("_sample_hash")
    )
