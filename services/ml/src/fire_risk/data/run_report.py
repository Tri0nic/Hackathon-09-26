"""Deterministic label statistics; feature names describe overlap, never labels."""

from collections import Counter
from collections.abc import Iterable, Sequence

import polars as pl

from fire_risk.contracts import IncidentLabel, LabelSource
from fire_risk.data.labels import PROXY_RULE_VERSION

_FEATURE_FAMILY_TOKENS = {
    "gas": {"gas", "methane"},
    "heat": {"heat", "temperature"},
    "manual": {"manual"},
    "pump": {"pump"},
    "smoke": {"smoke"},
    "uir": {"uir"},
}


def _counts(values: Iterable[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def build_label_report(
    labels: Sequence[IncidentLabel],
    targets: pl.DataFrame | pl.LazyFrame,
    feature_columns: Sequence[str],
) -> dict[str, object]:
    """Summarize proxy incidents and available target classes for all horizons.

    Target column names match attach_horizon_targets (target_now/6h/12h/24h).
    Censored rows never enter class balance. No feature values are accepted or
    consulted, and all insertion orders are deterministic for JSON serialization.
    """
    proxy = [label for label in labels if label.source == LabelSource.PROXY]
    versions = sorted({label.rule_version or "unspecified" for label in proxy})
    frame = targets.lazy() if isinstance(targets, pl.DataFrame) else targets
    statistics = (
        frame.select(
            pl.len().alias("total"),
            *[
                expression.alias(f"{horizon}_{name}")
                for horizon in ("12h", "24h", "6h", "now")
                for name, expression in {
                    "available": pl.col(f"target_{horizon}_available").sum(),
                    "positive": (
                        pl.col(f"target_{horizon}_available")
                        & pl.col(f"target_{horizon}")
                    ).sum(),
                    "negative": (
                        pl.col(f"target_{horizon}_available")
                        & ~pl.col(f"target_{horizon}")
                    ).sum(),
                }.items()
            ],
        )
        .collect()
        .row(0, named=True)
    )
    counts: dict[str, object] = {}
    balance: dict[str, object] = {}
    for horizon in ("12h", "24h", "6h", "now"):
        available = statistics[f"{horizon}_available"]
        positive = statistics[f"{horizon}_positive"]
        negative = statistics[f"{horizon}_negative"]
        counts[horizon] = {
            "available": available,
            "censored": statistics["total"] - available,
            "negative": negative,
            "positive": positive,
        }
        balance[horizon] = {
            "negative": negative,
            "positive": positive,
            "positive_share": positive / available if available else None,
        }
    combinations = Counter(
        tuple(sorted(set(label.sensor_combination))) for label in proxy
    )
    shared_columns = {
        family: sorted(
            {
                column
                for column in feature_columns
                if tokens.intersection(column.casefold().replace("-", "_").split("_"))
            }
        )
        for family, tokens in _FEATURE_FAMILY_TOKENS.items()
    }
    return {
        "class_balance": balance,
        "feature_rule_overlap": {
            "feature_columns_by_family": shared_columns,
            "proxy_signal_families": sorted(_FEATURE_FAMILY_TOKENS),
            "shared_signal_families": [
                family for family, columns in shared_columns.items() if columns
            ],
        },
        "proxy_incidents": {
            "by_object": _counts(label.object_id for label in proxy),
            "by_rule": _counts(label.rule_id or "unspecified" for label in proxy),
            "by_sensor_combination": [
                {"count": count, "sensor_combination": list(combination)}
                for combination, count in sorted(combinations.items())
            ],
            "by_year": _counts(str(label.started_at.year) for label in proxy),
            "total": len(proxy),
        },
        "proxy_rule_version": versions[0]
        if len(versions) == 1
        else ("mixed" if versions else PROXY_RULE_VERSION),
        "proxy_rule_versions": versions,
        "targets": counts,
        "warning": (
            "WARNING: proxy metrics measure reproduction of reconstructed labels, "
            "not detection quality for confirmed real fires. Feature/rule signal "
            "overlap can inflate agreement with proxy labels."
        ),
    }
