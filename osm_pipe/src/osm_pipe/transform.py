"""Stage 3 — rewrite OSM tags according to the selected projects' rules.

The rule engine is deliberately small: four primitive ops covering the cases
that matter for a future network. Anything more expressive belongs in code, not
in YAML.

Match semantics for `when` (all entries must hold):
    key: "value"        tag equals value
    key: [a, b]         tag is one of the values
    key: true           tag key is present (any value)
    key: false          tag key is absent

Ops, applied in this order:
    rename: {old: new}  move a value to another key (overwrites the target)
    unset:  [key, ...]  drop keys
    set:    {key: val}  set unconditionally
    default:{key: val}  set only if the key is absent

`default` last is the important one: it makes "real mapped data always wins"
true rather than aspirational.

Rules chain. Each rule matches against the output of the rules before it, which
is what lets `drop_oneway` key off the marker a promotion just wrote.

Scope costs differ by an order of magnitude and the difference is worth
knowing. A `ways` set is a hash lookup on an id the reader already has, so a
way-scoped run is *cheaper* than an unscoped one — fewer rules ever reach their
tag matcher. A `within` box needs the object's coordinates, which forces the
whole pass to carry a node-location index. Only `within` triggers that.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path

import osmium

from .config import Rule
from .geo import BBox

# Objects between heartbeats. Full-Europe rail is ~2 M ways and ~30 M nodes,
# so this is roughly one line every few seconds — enough to see it moving,
# not enough to bury the report that follows.
PROGRESS_EVERY = 2_000_000


def matches(tags: Mapping[str, str], when: Mapping[str, object]) -> bool:
    for key, expected in when.items():
        present = key in tags
        if expected is True:
            if not present:
                return False
        elif expected is False:
            if present:
                return False
        elif isinstance(expected, (list, tuple, set)):
            if not present or tags[key] not in expected:
                return False
        else:
            if not present or tags[key] != str(expected):
                return False
    return True


class WayPoints:
    """A way's node coordinates, materialised only if something asks for them.

    A location-scoped rule is tested only after its `when` matcher has passed,
    so on a Europe-wide extract the overwhelming majority of ways never need
    coordinates. Iterating repeatedly is safe — unlike a generator the result
    is cached, which matters because several rules test the same way.

    Only valid during the osmium callback that created it, which is the only
    place it is used.
    """

    __slots__ = ("_nodes", "_points")

    def __init__(self, nodes):
        self._nodes = nodes
        self._points: list[tuple[float, float]] | None = None

    def __iter__(self):
        if self._points is None:
            self._points = [
                (n.location.lat, n.location.lon)
                for n in self._nodes
                if n.location.valid()
            ]
        return iter(self._points)


def in_boxes(boxes: tuple[BBox, ...], points) -> bool:
    """True if any (lat, lon) falls in any box. Empty `boxes` means global.

    Any single node inside any box puts the whole object in scope. That is
    coarse — a long way clipping a corner is fully rewritten — and it is the
    reason `scope: {ways: [...]}` is preferred wherever the survey can supply
    the ids.
    """
    if not boxes:
        return True
    for lat, lon in points:
        for box in boxes:
            if box.contains(lat, lon):
                return True
    return False


def apply_rules(
    tags: dict[str, str],
    rules: tuple[Rule, ...],
    obj_type: str,
    obj_id: int = 0,
    hits: Counter | None = None,
    points=(),
) -> dict[str, str]:
    """Return the rewritten tag dict. Input is not mutated."""
    out = dict(tags)
    for rule in rules:
        if obj_type not in rule.types:
            continue
        if rule.ways and obj_id not in rule.ways:
            continue
        if not matches(out, rule.when):
            continue
        # Checked last: it is the only test that can need coordinates, and a
        # rule whose tag matcher already failed must not pay for them.
        if rule.within and not in_boxes(rule.within, points):
            continue
        if hits is not None:
            hits[rule.name] += 1
        for old, new in rule.rename.items():
            if old in out:
                out[new] = out.pop(old)
        for key in rule.unset:
            out.pop(key, None)
        # str() on both write paths: YAML turns an unquoted `maxspeed: 160`
        # into an int, and a non-string tag value fails deep inside pyosmium
        # with an error that points nowhere near the catalogue file.
        for key, value in rule.set.items():
            out[key] = str(value)
        for key, value in rule.default.items():
            out.setdefault(key, str(value))
        if rule.stop:
            break
    return out


class _Rewriter(osmium.SimpleHandler):
    def __init__(
        self,
        writer: osmium.SimpleWriter,
        rules: tuple[Rule, ...],
        *,
        need_locations: bool,
        watched_ways: frozenset[int],
    ):
        super().__init__()
        self.writer = writer
        self.rules = rules
        self.need_locations = need_locations
        self.hits: Counter = Counter()
        self.changed = 0
        # Way ids some rule names in its scope. Tracking which of them the
        # extract actually contains is the staleness signal: OSM way ids are
        # not stable, and a mapper splitting a way silently drops it out of
        # every scope that named it.
        self.watched_ways = watched_ways
        self.seen_ways: set[int] = set()
        self.matched_ways: set[int] = set()
        self.n_nodes = 0
        self.n_ways = 0
        self._started = time.monotonic()
        self._next_tick = PROGRESS_EVERY

    def _tick(self) -> None:
        """A heartbeat, because silence and a hang look identical.

        On full Europe this pass carries a node-location index over a 260 MB
        extract and runs for several minutes with nothing to show for it. The
        first thing anyone does with a silent process is kill it.
        """
        done = self.n_nodes + self.n_ways
        if done < self._next_tick:
            return
        self._next_tick += PROGRESS_EVERY
        elapsed = time.monotonic() - self._started
        print(
            f"[transform]   {self.n_nodes:,} nodes, {self.n_ways:,} ways, "
            f"{self.changed:,} rewritten ({elapsed:,.0f}s)",
            flush=True,
        )

    def _rewrite(self, obj, code: str, points=()):
        tags = {t.k: t.v for t in obj.tags}
        new = apply_rules(tags, self.rules, code, obj.id, self.hits, points)
        if new == tags:
            return obj
        self.changed += 1
        return obj.replace(tags=new)

    def node(self, n):
        # Building a tuple for every node in the file is only worth it when a
        # rule can actually test a node's location.
        points = ()
        if self.need_locations and n.location.valid():
            points = ((n.location.lat, n.location.lon),)
        self.writer.add_node(self._rewrite(n, "n", points))
        self.n_nodes += 1
        self._tick()

    def way(self, w):
        if w.id in self.watched_ways:
            self.seen_ways.add(w.id)
        points = WayPoints(w.nodes) if self.need_locations else ()
        before = self.changed
        self.writer.add_way(self._rewrite(w, "w", points))
        if w.id in self.watched_ways and self.changed > before:
            self.matched_ways.add(w.id)
        self.n_ways += 1
        self._tick()

    def relation(self, r):
        # A relation has no geometry of its own here, so a `within` rule can
        # never match one. Way-scoped rules cannot either — `ways` is a way-id
        # set. Both are silent no-ops rather than errors because a target's
        # rules are almost always `types: [w]` anyway.
        self.writer.add_relation(self._rewrite(r, "r"))


def transform_pbf(
    src: Path,
    dst: Path,
    rules: tuple[Rule, ...],
    *,
    overwrite: bool = False,
) -> Path:
    """Apply `rules` to `src`, writing `dst`."""
    if dst.exists() and not overwrite:
        print(f"[transform] {dst} exists — skipping (use --overwrite to rebuild)")
        return dst
    if not src.exists():
        raise FileNotFoundError(f"rail extract not found: {src}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()

    if not rules:
        # No project is open at this date — the identity transform. Link rather
        # than rewrite a gigabyte; this is the common case for an `as_of` in
        # the present, which is how the baseline is produced.
        print(f"[transform] no rules at this date — linking {src.name} -> {dst.name}")
        try:
            dst.hardlink_to(src)
        except OSError:
            # Relative, so the link still resolves inside the routing
            # container where data/ is bind-mounted at /app/data.
            dst.symlink_to(src.name)
        return dst

    need_locations = any(r.scoped_by_location for r in rules)
    watched: frozenset[int] = frozenset().union(*(r.ways for r in rules))
    if need_locations:
        print("[transform] bbox-scoped rules present — carrying a node-location index")

    writer = osmium.SimpleWriter(str(dst))
    handler = _Rewriter(
        writer,
        rules,
        need_locations=need_locations,
        watched_ways=watched,
    )
    try:
        if need_locations:
            handler.apply_file(str(src), locations=True, idx="flex_mem")
        else:
            handler.apply_file(str(src))
    except BaseException:
        # A half-written pbf is worse than none: every later stage checks
        # `exists()` to decide whether it can skip itself, so leaving the
        # partial file behind makes the next run silently reuse a truncated
        # extract.
        writer.close()
        dst.unlink(missing_ok=True)
        raise
    else:
        writer.close()

    _report(handler, rules, dst)
    return dst


def _report(handler: _Rewriter, rules: tuple[Rule, ...], dst: Path) -> None:
    print(f"[transform] {handler.changed:,} objects rewritten -> {dst}")

    by_project: dict[str, Counter] = defaultdict(Counter)
    for rule in rules:
        by_project[rule.project or "(extra_rules)"][rule.name] = handler.hits.get(
            rule.name, 0
        )

    silent: list[str] = []
    for project, counts in sorted(by_project.items()):
        total = sum(counts.values())
        if not total:
            silent.append(project)
            continue
        print(f"[transform] {project}: {total:,} ways")
        for name, count in counts.most_common():
            label = name.split("/", 1)[-1]
            if count:
                print(f"[transform]     {label}: {count:,}")
            else:
                # This is the interesting silence: the project *is* in this
                # extract and one of its changes still did nothing. A
                # `drop_oneway` that never fires means the corridor is not
                # mapped the way the entry claims.
                print(f"[transform]     {label}: 0  <-- matched nothing")

    if silent:
        # A whole project matching nothing is expected on a country extract —
        # most of Europe's catalogue is simply not in it — so these are listed
        # flatly rather than flagged. On the europe dataset, though, every one
        # of these is a real finding: a typo in a tag key, a bbox that misses
        # the corridor, or a way-id list gone stale.
        print(
            f"[transform] {len(silent)} project(s) matched nothing "
            "(expected off-region; a finding on -d europe):"
        )
        print(f"[transform]     {', '.join(silent)}")

    if handler.watched_ways:
        missing = sorted(handler.watched_ways - handler.seen_ways)
        inert = sorted(handler.seen_ways - handler.matched_ways)
        print(
            f"[transform] scope way ids: {len(handler.watched_ways):,} listed, "
            f"{len(handler.seen_ways):,} in the extract, "
            f"{len(handler.matched_ways):,} rewritten"
        )
        if missing:
            print(
                "[transform]   NOT IN EXTRACT — either outside this dataset's "
                "region, or the way was split/deleted in OSM since the ids "
                "were surveyed. Re-run `osm-survey corridors`:"
            )
            print(f"[transform]     {_ids(missing)}")
        if inert:
            print(
                "[transform]   present but unchanged — the way is in the "
                "extract and no rule matched it, so its tags are not what the "
                "project expects (already promoted? different lifecycle?):"
            )
            print(f"[transform]     {_ids(inert)}")


def _ids(values: list[int], limit: int = 20) -> str:
    head = ", ".join(str(v) for v in values[:limit])
    return head if len(values) <= limit else f"{head}, … (+{len(values) - limit})"
