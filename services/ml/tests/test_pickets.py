from itertools import pairwise

import pytest

from fire_risk.data.pickets import parse_picket


@pytest.mark.parametrize(
    ("name", "raw"),
    [
        ("Дым Д1 ПК3", "ПК3"),
        ("ТД ПК 87", "ПК 87"),
        ("Дым ПК145+3", "ПК145+3"),
        ("ГРО ПК86-85", "ПК86-85"),
        ("УИР-Р ПК29–231", "ПК29–231"),
    ],
)
def test_parse_picket_preserves_raw(name: str, raw: str) -> None:
    assert parse_picket(name).raw == raw


def test_name_without_picket_is_unlocated() -> None:
    result = parse_picket("Датчик в венткамере")
    assert result.raw is None
    assert result.sort_key is None
    assert result.location_group == "unlocated"


@pytest.mark.parametrize("name", ["PK3", "ПК  87", "ПК29—231", "ХПК3", "ПК3x"])
def test_unagreed_forms_are_unlocated(name: str) -> None:
    assert parse_picket(name).location_group == "unlocated"


def test_sort_key_orders_by_picket_without_claiming_distance() -> None:
    names = ["ПК3", "ПК 87", "ПК145+3", "ПК86-85", "ПК29–231"]
    keys = [parse_picket(name).sort_key for name in names]
    assert keys[0] is not None
    assert keys[4] is not None
    assert keys[3] is not None
    assert keys[1] is not None
    assert keys[2] is not None
    assert keys[0] < keys[4] < keys[3] < keys[1] < keys[2]


def test_suffix_sort_keys_are_distinct_monotonic_and_within_base_picket() -> None:
    suffixes = [0, 1, 2, 10, 999, 1000, 999_998, 999_999]
    keys = [parse_picket(f"ПК3+{suffix}").sort_key for suffix in suffixes]

    assert all(key is not None and 3 < key < 4 for key in keys)
    assert all(left < right for left, right in pairwise(keys))


@pytest.mark.parametrize("separator", ["+", "-", "–"])
def test_oversized_suffix_keeps_raw_but_is_unlocated(separator: str) -> None:
    raw = f"ПК3{separator}1000000"
    result = parse_picket(f"Датчик {raw}")

    assert result.raw == raw
    assert result.sort_key is None
    assert result.location_group == "unlocated"


def test_very_long_suffix_keeps_raw_without_integer_conversion() -> None:
    raw = "ПК3+" + "9" * 5000
    result = parse_picket(raw)

    assert result.raw == raw
    assert result.sort_key is None
    assert result.location_group == "unlocated"
