"""Extract source picket labels for relative channel ordering."""

import re
from dataclasses import dataclass
from typing import Final

MAX_PICKET_BASE: Final[int] = 999_999
MAX_SORTABLE_PICKET_SUFFIX: Final[int] = 999_999

_PICKET = re.compile(
    r"(?<!\w)ПК ?(?P<base>[0-9]+)(?:[+\-–](?P<suffix>[0-9]+))?(?![\w+\-–—])"
)


@dataclass(frozen=True)
class ParsedPicket:
    raw: str | None
    sort_key: float | None
    location_group: str


def parse_picket(name: str) -> ParsedPicket:
    """Keep the matched label; the numeric key is only for relative ordering."""
    match = _PICKET.search(name)
    if match is None:
        return ParsedPicket(raw=None, sort_key=None, location_group="unlocated")

    raw = match.group()
    base_digits = match.group("base").lstrip("0") or "0"
    if len(base_digits) > len(str(MAX_PICKET_BASE)):
        return ParsedPicket(raw=raw, sort_key=None, location_group="unlocated")
    base = int(base_digits)
    if base > MAX_PICKET_BASE:
        return ParsedPicket(raw=raw, sort_key=None, location_group="unlocated")

    suffix = match.group("suffix")
    value: int | None = None
    if suffix is not None:
        significant_digits = suffix.lstrip("0") or "0"
        if len(significant_digits) > len(str(MAX_SORTABLE_PICKET_SUFFIX)):
            return ParsedPicket(raw=raw, sort_key=None, location_group="unlocated")
        value = int(significant_digits)
        if value > MAX_SORTABLE_PICKET_SUFFIX:
            return ParsedPicket(raw=raw, sort_key=None, location_group="unlocated")

    # Suffixes order labels within a base picket; they are not distances.
    sort_key = float(base)
    if value is not None:
        sort_key += (value + 1) / (MAX_SORTABLE_PICKET_SUFFIX + 2)
    return ParsedPicket(raw=raw, sort_key=sort_key, location_group="picket")
