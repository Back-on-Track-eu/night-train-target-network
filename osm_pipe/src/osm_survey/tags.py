"""Reading OSM's lifecycle-prefix scheme.

OSM has a consistent way of tagging infrastructure that does not yet carry
traffic: a line under construction is `railway=construction` with its real
attributes moved under a `construction:` namespace, a planned one is
`railway=proposed` with `proposed:`. The scheme is good, well-followed, and
completely opaque to GraphHopper.

Three spellings are in use, and any tool that reads only the first will
silently miss corridors:

    railway=construction + construction:railway=rail     prefixed
    railway=construction + construction=rail             short
    railway=construction                                 untyped
    disused:railway=rail                                 prefix-only, no
                                                         railway=* at all

The last one matters more than it looks. The rail extract deliberately keeps
`w/disused:railway`, but a check written as `tags["railway"] in LIFECYCLE`
never sees those ways — so every corridor closed for rebuilding is invisible to
the analysis that is supposed to find it.
"""

from __future__ import annotations

# Ordered: a way carrying two lifecycle prefixes is reported as the earliest
# stage present, since that is the one that blocks routing.
LIFECYCLES = ("construction", "proposed", "disused", "abandoned", "razed")

# What OpenRailRouting's RailAccessParser admits. Anything else is skipped at
# import, so a promotion to one of these is the only one worth proposing.
ROUTABLE_RAILWAY = ("rail", "light_rail", "tram", "subway", "narrow_gauge")

# Attributes worth reporting per corridor, bare or under a lifecycle prefix.
INTERESTING = (
    "name",
    "ref",
    "operator",
    "usage",
    "maxspeed",
    "gauge",
    "electrified",
    "voltage",
    "tracks",
    "highspeed",
    "oneway",
    "service",
    "tunnel",
    "bridge",
    "opening_date",
)


def lifecycle_of(tags) -> str:
    """Which lifecycle stage a way is in, or "" if it is not one.

    Checks `railway=<lifecycle>` first, then the prefix-only spelling.
    """
    value = tags.get("railway")
    if value in LIFECYCLES:
        return value
    if value is None:
        for stage in LIFECYCLES:
            if f"{stage}:railway" in tags:
                return stage
    return ""


def lifecycle_kind(tags, stage: str) -> str:
    """What the way will be once it opens: rail, light_rail, ... or "".

    Reads the prefixed spelling, then the short one. An empty result means the
    mapper recorded that something is planned without recording what — a real
    and common case, and a weaker signal than the other two.
    """
    prefixed = tags.get(f"{stage}:railway")
    if prefixed:
        return prefixed
    short = tags.get(stage)
    if short in ROUTABLE_RAILWAY:
        return short
    return ""


def spelling(tags, stage: str) -> str:
    """Which of the three tagging forms this way uses — reported so a scope
    can be checked against the change that will be applied to it."""
    if tags.get(f"{stage}:railway"):
        return "prefixed"
    if tags.get(stage) in ROUTABLE_RAILWAY:
        return "short"
    return "untyped"


def attributes(tags, stage: str) -> dict[str, str]:
    """The interesting tags, with lifecycle-prefixed ones lifted to bare keys.

    Mirrors what the `promote` change will do, so what this prints is what the
    router would end up seeing.
    """
    out: dict[str, str] = {}
    for key in INTERESTING:
        prefixed = tags.get(f"{stage}:{key}")
        if prefixed:
            out[key] = prefixed
        elif tags.get(key):
            out[key] = tags[key]
    return out
