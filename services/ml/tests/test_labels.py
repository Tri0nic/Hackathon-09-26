"""Replaceable incident label providers."""

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from fire_risk.contracts import (
    IncidentDecision,
    IncidentEpisode,
    IncidentLabel,
    LabelSource,
)
from fire_risk.data.episodes import build_episodes
from fire_risk.data.labels import (
    DecisionJournalLabelProvider,
    LabelImportError,
    LabelProvider,
    ProxyLabelConfig,
    ProxyLabelProvider,
)

START = datetime(2026, 8, 1, 3, 0, tzinfo=UTC)
OBSERVED_UNTIL = datetime(2026, 12, 31, tzinfo=UTC)


def test_providers_expose_explicit_observation_boundary_without_incidents() -> None:
    boundary = datetime(2026, 12, 31, tzinfo=UTC)
    providers: list[LabelProvider] = [
        ProxyLabelProvider(ProxyLabelConfig(episodes=[], observed_until=boundary)),
        DecisionJournalLabelProvider([], observed_until=boundary),
    ]
    for provider in providers:
        assert provider.get_incidents(START, boundary, {"42"}) == []
        assert provider.observed_until == boundary
        assert provider.get_incidents(START, boundary + timedelta(days=1), {"42"}) == []
        assert provider.observed_until == boundary


@pytest.mark.parametrize("provider_kind", ["proxy", "journal"])
def test_providers_reject_naive_observation_boundary(provider_kind: str) -> None:
    naive = OBSERVED_UNTIL.replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        if provider_kind == "proxy":
            ProxyLabelProvider(ProxyLabelConfig(episodes=[], observed_until=naive))
        else:
            DecisionJournalLabelProvider([], observed_until=naive)


def _episode(
    *,
    episode_id: str = "episode-42",
    object_id: str = "42",
    started_at: datetime = START,
    channel_ids: list[str] | None = None,
    sensor_types: list[str] | None = None,
    quality_flags: list[str] | None = None,
) -> IncidentEpisode:
    channels = channel_ids if channel_ids is not None else ["smoke-1", "heat-1"]
    types = sensor_types if sensor_types is not None else ["smoke", "heat"]
    return IncidentEpisode(
        episode_id=episode_id,
        object_id=object_id,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=5),
        severity="alarm",
        channel_ids=channels,
        sensor_types=types,
        alarming_channel_ids=channels,
        alarming_sensor_types=types,
        quality_flags=quality_flags if quality_flags is not None else [],
    )


def test_proxy_and_decision_providers_return_same_contract() -> None:
    proxy_provider: LabelProvider = ProxyLabelProvider(
        ProxyLabelConfig(episodes=[_episode()], observed_until=OBSERVED_UNTIL)
    )
    decision_provider: LabelProvider = DecisionJournalLabelProvider(
        [{"object_id": "42", "started_at": START, "decision": "confirmed_fire"}],
        observed_until=OBSERVED_UNTIL,
    )

    proxy = proxy_provider.get_incidents(START, START + timedelta(hours=1), {"42"})
    real = decision_provider.get_incidents(START, START + timedelta(hours=1), {"42"})

    assert type(proxy[0]) is IncidentLabel
    assert type(real[0]) is IncidentLabel
    assert proxy[0].source is LabelSource.PROXY
    assert real[0].source is LabelSource.DISPATCHER
    assert proxy[0].decision is IncidentDecision.UNKNOWN
    assert real[0].decision is IncidentDecision.CONFIRMED_FIRE


@pytest.mark.parametrize("missing_field", ["object_id", "started_at"])
def test_decision_requires_identity_and_start_with_row_number(
    missing_field: str,
) -> None:
    rows = [
        {"object_id": "42", "started_at": START, "decision": "confirmed_fire"},
        {"object_id": "43", "started_at": START, "decision": "false_alarm"},
    ]
    del rows[1][missing_field]

    with pytest.raises(LabelImportError, match=rf"row 2.*{missing_field}"):
        DecisionJournalLabelProvider(rows, observed_until=OBSERVED_UNTIL)


def test_unknown_journal_outcome_is_kept_as_unknown() -> None:
    provider = DecisionJournalLabelProvider(
        [
            {
                "object_id": "42",
                "started_at": START.isoformat(),
                "decision": "investigating",
            }
        ],
        observed_until=OBSERVED_UNTIL,
    )

    labels = provider.get_incidents(START, START + timedelta(minutes=1), {"42"})

    assert len(labels) == 1
    assert labels[0].decision is IncidentDecision.UNKNOWN
    assert labels[0].object_id == "42"


@pytest.mark.parametrize("outcome", [decision.value for decision in IncidentDecision])
def test_journal_accepts_each_exact_decision(outcome: str) -> None:
    provider = DecisionJournalLabelProvider(
        [{"object_id": "42", "started_at": START, "decision": outcome}],
        observed_until=OBSERVED_UNTIL,
    )

    labels = provider.get_incidents(START, START + timedelta(minutes=1), {"42"})

    assert labels[0].decision is IncidentDecision(outcome)


def test_provider_filters_by_instant_half_open_boundary_and_object() -> None:
    from datetime import timezone

    plus_three = timezone(timedelta(hours=3))
    same_instant = START.astimezone(plus_three)
    at_end = START + timedelta(hours=1)
    episodes = [
        _episode(episode_id="included", started_at=same_instant),
        _episode(episode_id="at-end", started_at=at_end),
        _episode(episode_id="other-object", object_id="43"),
    ]
    rows = [
        {
            "incident_id": "included",
            "object_id": "42",
            "started_at": same_instant,
            "decision": "confirmed_fire",
        },
        {
            "incident_id": "at-end",
            "object_id": "42",
            "started_at": at_end,
            "decision": "confirmed_fire",
        },
        {
            "incident_id": "other-object",
            "object_id": "43",
            "started_at": START,
            "decision": "confirmed_fire",
        },
    ]
    providers: list[LabelProvider] = [
        ProxyLabelProvider(
            ProxyLabelConfig(episodes=episodes, observed_until=OBSERVED_UNTIL)
        ),
        DecisionJournalLabelProvider(rows, observed_until=OBSERVED_UNTIL),
    ]

    for provider in providers:
        labels = provider.get_incidents(START, at_end, {"42"})
        assert [label.incident_id for label in labels] == ["included"]
        assert provider.get_incidents(START, at_end, set()) == []


def test_proxy_requires_fire_pattern_and_ignores_historical_artifact() -> None:
    episodes = [
        _episode(episode_id="heat"),
        _episode(episode_id="manual", sensor_types=["smoke", "manual_call_point"]),
        _episode(episode_id="uir", sensor_types=["smoke", "uir-r"]),
        _episode(episode_id="single", sensor_types=["smoke"]),
        _episode(episode_id="artifact", quality_flags=["historical_artifact"]),
    ]
    provider = ProxyLabelProvider(
        ProxyLabelConfig(
            episodes=episodes,
            observed_until=OBSERVED_UNTIL,
            rule_version="smvu-v7",
            confidence=0.65,
        )
    )

    labels = provider.get_incidents(START, START + timedelta(hours=1), {"42"})

    assert [label.incident_id for label in labels] == ["heat", "manual", "uir"]
    assert all(label.incident_type == "SMVU fire pattern" for label in labels)
    assert all(label.decision is IncidentDecision.UNKNOWN for label in labels)
    assert all(label.rule_version == "smvu-v7" for label in labels)
    assert all(label.confidence == 0.65 for label in labels)


def test_proxy_uses_gas_pump_and_mass_alarm_composition() -> None:
    gas_and_pump = _episode(
        episode_id="gas-pump", sensor_types=["smoke", "gas", "pump"]
    )
    mass_alarm = _episode(
        episode_id="mass",
        channel_ids=["smoke-1", "smoke-2", "gas-1"],
        sensor_types=["smoke", "gas"],
    )
    weak = _episode(episode_id="weak", sensor_types=["smoke", "gas"])
    no_smoke = _episode(episode_id="no-smoke", sensor_types=["gas", "pump"])
    provider = ProxyLabelProvider(
        ProxyLabelConfig(
            episodes=[gas_and_pump, mass_alarm, weak, no_smoke],
            observed_until=OBSERVED_UNTIL,
        )
    )

    labels = provider.get_incidents(START, START + timedelta(hours=1), {"42"})

    assert [label.incident_id for label in labels] == ["gas-pump", "mass"]


def test_proxy_requires_alarm_severity() -> None:
    episode = _episode()
    episode.severity = "unknown"
    provider = ProxyLabelProvider(
        ProxyLabelConfig(episodes=[episode], observed_until=OBSERVED_UNTIL)
    )

    assert provider.get_incidents(START, START + timedelta(hours=1), {"42"}) == []


def test_proxy_recognizes_source_sensor_type_names() -> None:
    episodes = [
        _episode(
            episode_id="smoke-temperature",
            sensor_types=["Датчик дыма", "Датчик температуры"],
        ),
        _episode(
            episode_id="smoke-gas-pump",
            sensor_types=["Датчик дыма", "Газовый датчик", "Насос"],
        ),
        _episode(
            episode_id="smoke-uir",
            sensor_types=["Датчик дыма", "УИР-Р"],
        ),
    ]
    provider = ProxyLabelProvider(
        ProxyLabelConfig(episodes=episodes, observed_until=OBSERVED_UNTIL)
    )

    labels = provider.get_incidents(START, START + timedelta(hours=1), {"42"})

    assert [label.incident_id for label in labels] == [
        "smoke-temperature",
        "smoke-gas-pump",
        "smoke-uir",
    ]


@pytest.mark.parametrize("provider_kind", ["proxy", "journal"])
def test_providers_reject_naive_or_reversed_period(provider_kind: str) -> None:
    provider: LabelProvider
    if provider_kind == "proxy":
        provider = ProxyLabelProvider(
            ProxyLabelConfig(episodes=[_episode()], observed_until=OBSERVED_UNTIL)
        )
    else:
        provider = DecisionJournalLabelProvider(
            [{"object_id": "42", "started_at": START, "decision": "confirmed_fire"}],
            observed_until=OBSERVED_UNTIL,
        )

    with pytest.raises(ValueError, match="timezone-aware"):
        provider.get_incidents(START.replace(tzinfo=None), START, {"42"})
    with pytest.raises(ValueError, match="end must not precede start"):
        provider.get_incidents(START + timedelta(hours=1), START, {"42"})


def test_decision_rejects_invalid_start_with_row_number() -> None:
    with pytest.raises(LabelImportError, match="row 1.*started_at"):
        DecisionJournalLabelProvider(
            [{"object_id": "42", "started_at": "yesterday", "decision": "false_alarm"}],
            observed_until=OBSERVED_UNTIL,
        )


def test_journal_keeps_optional_incident_details() -> None:
    ended_at = START + timedelta(minutes=8)
    confirmed_at = START + timedelta(minutes=11)
    provider = DecisionJournalLabelProvider(
        [
            {
                "incident_id": "dispatch-9",
                "object_id": "42",
                "started_at": START,
                "ended_at": ended_at.isoformat(),
                "incident_type": "smoke check",
                "decision": "smoke_without_fire",
                "confirmed_at": confirmed_at.isoformat(),
                "source": "imported",
                "confidence": 0.85,
                "rule_version": "dispatcher-v3",
            }
        ],
        observed_until=OBSERVED_UNTIL,
    )

    label = provider.get_incidents(START, START + timedelta(hours=1), {"42"})[0]

    assert label.incident_id == "dispatch-9"
    assert label.ended_at == ended_at
    assert label.incident_type == "smoke check"
    assert label.confirmed_at == confirmed_at
    assert label.source is LabelSource.IMPORTED
    assert label.confidence == 0.85
    assert label.rule_version == "dispatcher-v3"


def test_journal_query_returns_independent_label_objects() -> None:
    provider = DecisionJournalLabelProvider(
        [
            {
                "incident_id": "dispatch-9",
                "object_id": "42",
                "started_at": START,
                "decision": "confirmed_fire",
                "incident_type": "fire",
            }
        ],
        observed_until=OBSERVED_UNTIL,
    )
    first = provider.get_incidents(START, START + timedelta(hours=1), {"42"})[0]
    first.incident_type = "changed by caller"
    first.confidence = 0.1

    second = provider.get_incidents(START, START + timedelta(hours=1), {"42"})[0]

    assert second is not first
    assert second.incident_type == "fire"
    assert second.confidence == 1.0


def test_proxy_uses_only_alarming_event_composition_from_built_episodes() -> None:
    event_specs = [
        ("1", 0, "smoke-1", "smoke", False),
        ("2", 1, "heat-1", "heat", False),
        ("3", 2, "door-1", "door", True),
        ("4", 40, "smoke-2", "smoke", True),
        ("5", 41, "gas-1", "gas", True),
        ("6", 42, "door-2", "door", False),
        ("7", 80, "smoke-3", "smoke", True),
        ("8", 81, "heat-2", "heat", True),
    ]
    events = pl.DataFrame(
        {
            "event_id": [row[0] for row in event_specs],
            "channel_id": [row[2] for row in event_specs],
            "object_id": ["42"] * len(event_specs),
            "registered_at": [START + timedelta(minutes=row[1]) for row in event_specs],
            "sensor_type": [row[3] for row in event_specs],
            "alarm_flag": [row[4] for row in event_specs],
            "picket_sort_key": [None] * len(event_specs),
            "quality_flags": [[] for _ in event_specs],
        }
    ).lazy()
    episodes_frame, _ = build_episodes(events, timedelta(minutes=30))
    episodes = [
        IncidentEpisode.model_validate(row)
        for row in episodes_frame.collect().to_dicts()
    ]
    provider = ProxyLabelProvider(
        ProxyLabelConfig(episodes=episodes, observed_until=OBSERVED_UNTIL)
    )

    labels = provider.get_incidents(START, START + timedelta(hours=2), {"42"})

    assert [label.started_at for label in labels] == [START + timedelta(minutes=80)]


def test_proxy_ignores_legacy_episode_without_alarm_composition() -> None:
    episode = IncidentEpisode(
        episode_id="legacy",
        object_id="42",
        started_at=START,
        ended_at=START + timedelta(minutes=5),
        severity="alarm",
        channel_ids=["smoke-1", "heat-1"],
        sensor_types=["smoke", "heat"],
    )
    provider = ProxyLabelProvider(
        ProxyLabelConfig(episodes=[episode], observed_until=OBSERVED_UNTIL)
    )

    assert provider.get_incidents(START, START + timedelta(hours=1), {"42"}) == []
