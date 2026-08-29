"""What network a graph cache actually contains.

GraphHopper records almost nothing about its input: a built cache's
`properties.txt` carries `datareader.data.date=1970-01-01T00:00:00Z`, because
`osmium` strips the header timestamp, and nothing anywhere names the target,
the catalogue or the connectors that produced it.

That is survivable while the network is a constant. It stops being survivable
the moment the network is an input to the model: a stored proposal computed on
a 2032 graph is indistinguishable from one computed on today's, and
`ROUTE_BUILDER_VERSION` does not know the difference. This file is the missing
identity — written beside every cache we build, and copied along when one is
installed for the app.

It is *not* yet read by the backend. Recording it next to a stored route's
provenance is a backend change and has not been made, so a proposal published
from a scenario cache is still uninterpretable later. `osm-pipe install` says so
out loud for that reason.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

from .catalogue import Selection
from .config import MANIFEST_NAME, Target
from .download import osm_timestamp

SCHEMA = 1


def _sha256(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build(
    target: Target,
    selection: Selection,
    *,
    catalogue_path: Path,
    rule_count: int,
    connector_count: int,
) -> dict[str, Any]:
    provenance: dict[str, Any] = {}
    if target.dataset.provenance.exists():
        try:
            provenance = json.loads(target.dataset.provenance.read_text())
        except json.JSONDecodeError:
            provenance = {}

    # Which OSM snapshot this is. The provenance file is the good source, but
    # it only exists if `download` ran — and a raw extract that arrived some
    # other way (copied between machines, left over from an older tool) is
    # exactly the case where nobody can otherwise say how old the data is. So
    # fall back to the .pbf header, which carries the timestamp regardless of
    # how the file got here.
    stamp = provenance.get("osm_timestamp") or ""
    if not stamp and target.dataset.raw.exists():
        stamp = osm_timestamp(target.dataset.raw)
        provenance["osm_timestamp"] = stamp

    return {
        "schema": SCHEMA,
        "built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "target": target.name,
        "as_of": target.as_of.isoformat(),
        "date_basis": target.date_basis,
        "dataset": {
            "name": target.dataset.name,
            "regions": list(target.dataset.regions),
            "clip": target.dataset.clip.as_list() if target.dataset.clip else None,
            "osm_timestamp": stamp,
        },
        # Hashes rather than paths: the question a reader has is "was this
        # cache built from the files I am looking at now", and a path cannot
        # answer it.
        "inputs": {
            "catalogue": {
                "name": target.catalogue_name,
                "sha256": _sha256(catalogue_path),
            },
            "connectors": {
                "name": target.connectors,
                "sha256": _sha256(target.connector_file),
                "count": connector_count,
            },
        },
        "projects": [
            {
                "id": p.id,
                "name": p.name,
                "opening": p.opening_on(target.date_basis).isoformat(),
                "scope": "ways" if p.scope.ways else ("bbox" if p.scope.bbox else "-"),
            }
            for p in selection.included
        ],
        "excluded": [
            {"id": p.id, "reason": reason} for p, reason in selection.excluded
        ],
        "rule_count": rule_count,
    }


def write(record: dict[str, Any], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / MANIFEST_NAME
    path.write_text(json.dumps(record, indent=2) + "\n")
    return path


def read(directory: Path) -> dict[str, Any] | None:
    path = directory / MANIFEST_NAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def describe(record: dict[str, Any] | None) -> str:
    """One-line summary, for `install` and `status` output."""
    if not record:
        return "unknown network (no manifest — a stock or hand-built cache)"
    projects = record.get("projects") or []
    dataset = (record.get("dataset") or {}).get("name", "?")
    stamp = (record.get("dataset") or {}).get("osm_timestamp") or "unknown OSM date"
    return (
        f"{record.get('target', '?')} @ {record.get('as_of', '?')} "
        f"on {dataset} ({len(projects)} project(s), OSM {stamp})"
    )
