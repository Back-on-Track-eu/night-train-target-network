"""Stage 2 — cut the rail subset out of the dataset extract.

The single most valuable stage in the pipeline, and the reason the whole loop
is workable. Full-Europe `.osm.pbf` is ~35 GB; everything downstream cares only
about railway objects, so filtering once leaves ~0.26 GB.

The saving is not just disk. The app's own import (see docs/current_pipe.md)
hands the entire 35 GB to GraphHopper, which indexes half a billion nodes
before OpenRailRouting's access parser discards everything that is not railway
— which is where its 24 GB heap and 20–40 minutes go. Having already done that
discarding, the same import runs in ~6 GB and ~3 minutes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .download import require

# Objects kept by the rail extract. `tags-filter` also emits every object the
# matches reference — the nodes of a matched way, the members of a matched
# relation — unless `--omit-referenced` is passed, which is why geometries stay
# complete without an extra flag.
#
# The lifecycle prefixes matter as much as `w/railway` itself: a corridor
# closed for rebuilding is tagged `disused:railway=rail`, and a target that
# reopens one needs those ways present to rewrite them. They are matched on
# ways only — a lifecycle-tagged node is kept when a kept way references it.
FILTER_EXPRESSIONS = [
    "w/railway",
    "n/railway",
    "w/proposed:railway",
    "w/construction:railway",
    "w/disused:railway",
    "w/abandoned:railway",
    "w/razed:railway",
    "r/railway",
    "r/route=train,railway,tracks",
]


def extract_rail(src: Path, dst: Path, *, overwrite: bool = False) -> Path:
    """Filter `src` down to railway objects and write `dst`."""
    if dst.exists() and not overwrite:
        print(f"[extract] {dst} exists — skipping (use --overwrite to rebuild)")
        return dst
    if not src.exists():
        dataset = src.name.removesuffix("-latest.osm.pbf")
        raise FileNotFoundError(
            f"dataset extract not found: {src}\n"
            f"Fetch it first:  osm-pipe download {dataset}"
        )

    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        require("osmium"),
        "tags-filter",
        "--verbose",
        "--overwrite",
        "--output",
        str(dst),
        str(src),
        *FILTER_EXPRESSIONS,
    ]
    print("[extract]", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
    except BaseException:
        # osmium writes incrementally, and every later stage decides whether to
        # skip itself by checking `exists()`. A truncated file left behind
        # would be silently reused.
        dst.unlink(missing_ok=True)
        raise

    size_gb = dst.stat().st_size / 1e9
    print(f"[extract] wrote {dst} ({size_gb:.2f} GB)")
    return dst
