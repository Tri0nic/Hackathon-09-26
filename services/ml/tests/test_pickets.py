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
