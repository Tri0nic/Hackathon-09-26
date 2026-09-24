"""Extract source picket labels for relative channel ordering."""

import re
from dataclasses import dataclass

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

    base = int(match.group("base"))
    suffix = match.group("suffix")
    # Suffixes order labels within a base picket; they are not distances.
    sort_key = float(base)
    if suffix is not None:
        value = int(suffix)
        sort_key += (value + 1) / (value + 2)
    return ParsedPicket(raw=match.group(), sort_key=sort_key, location_group="picket")
