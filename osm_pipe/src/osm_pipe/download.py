"""Stage 1 — fetch the dataset's regions from Geofabrik, merge, clip.

The stage that did not exist before. A dataset used to be one Geofabrik extract
whose name was interpolated into a path, which meant a multi-region test set
had to be assembled by hand with `osmium merge` and left no record of how. The
Fehmarn test data was made that way: three region files merged into a
`fehmarn-latest.osm.pbf` that nothing in the repo could reproduce.

What this writes alongside the extract is as important as the extract. A graph
cache records `datareader.data.date=1970-01-01` — `osmium` strips the header
timestamp — so without a provenance file nothing anywhere says which OSM
snapshot a route was computed on.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

from .config import Dataset

# Geofabrik publishes a sibling .md5 for every extract: "<hash>  <filename>".
MD5_SUFFIX = ".md5"


def require(tool: str) -> str:
    exe = shutil.which(tool)
    if exe is None:
        hint = {
            "osmium": "  macOS:  brew install osmium-tool\n"
            "  Debian: apt install osmium-tool",
            "curl": "  curl ships with macOS and most Linux distributions",
        }.get(tool, "")
        raise RuntimeError(f"the `{tool}` command-line tool is required.\n{hint}")
    return exe


def _run(cmd: list[str], *, quiet: bool = False) -> subprocess.CompletedProcess:
    if not quiet:
        print("[download]", " ".join(cmd))
    return subprocess.run(cmd, check=True)


def _capture(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def fetch_region(dataset: Dataset, region: str, *, overwrite: bool = False) -> Path:
    """Download one Geofabrik region, resuming an interrupted transfer."""
    dst = dataset.region_file(region)
    url = dataset.region_url(region)
    dst.parent.mkdir(parents=True, exist_ok=True)

    expected = _fetch_md5(url)

    if dst.exists() and not overwrite:
        # An existing file might be a complete download or a truncated one. The
        # checksum is the only way to tell, and getting this wrong means every
        # downstream stage silently works on half a continent.
        if expected and _md5(dst) == expected:
            print(f"[download] {dst.name} present, checksum ok — skipping")
            return dst
        if expected:
            print(f"[download] {dst.name} present but checksum differs — resuming")
        else:
            print(f"[download] {dst.name} present, no checksum published — keeping")
            return dst

    print(f"[download] {url} -> {dst}")
    # -C - resumes; on a complete file curl exits 33 or reports nothing to do,
    # which is not an error worth aborting a multi-region fetch for.
    result = subprocess.run(
        [require("curl"), "-L", "-C", "-", "--create-dirs", "-o", str(dst), url]
    )
    if result.returncode not in (0, 33):
        raise RuntimeError(f"curl failed ({result.returncode}) fetching {url}")

    if expected:
        actual = _md5(dst)
        if actual != expected:
            raise RuntimeError(
                f"checksum mismatch for {dst.name}\n"
                f"  expected {expected}\n  got      {actual}\n"
                "Delete the file and re-run; a resumed download over a file "
                "from a different Geofabrik snapshot cannot be repaired."
            )
        print(f"[download] {dst.name} checksum ok")
    return dst


def _fetch_md5(url: str) -> str:
    text = _capture([require("curl"), "-fsSL", url + MD5_SUFFIX])
    return text.split()[0] if text else ""


def _md5(path: Path) -> str:
    import hashlib

    digest = hashlib.md5()
    with path.open("rb") as fh:
        # 8 MiB blocks: the files are up to 35 GB and the default 64 KiB makes
        # this several minutes of syscall overhead on its own.
        for block in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def osm_timestamp(pbf: Path) -> str:
    """The OSM snapshot a .pbf was cut from, straight out of its header."""
    return _capture(
        [
            require("osmium"),
            "fileinfo",
            "-g",
            "header.option.osmosis_replication_timestamp",
            str(pbf),
        ]
    )


def download(dataset: Dataset, *, overwrite: bool = False) -> Path:
    """Fetch every region, merge and clip as needed, record provenance."""
    dst = dataset.raw
    if dst.exists() and not overwrite:
        print(f"[download] {dst} exists — skipping (use --overwrite to rebuild)")
        if not dataset.provenance.exists():
            _write_provenance(dataset, [], note="pre-existing file, origin unrecorded")
        return dst

    files = [fetch_region(dataset, r, overwrite=overwrite) for r in dataset.regions]

    if not dataset.is_composite:
        # Single region, no clip: the downloaded file *is* the dataset. The
        # naming lines up so nothing is copied.
        if files[0] != dst:
            _run([require("osmium"), "cat", "-O", "-o", str(dst), str(files[0])])
    else:
        merged = dst
        if len(files) > 1:
            merged = dst.with_suffix(".merged.osm.pbf") if dataset.clip else dst
            _run(
                [
                    require("osmium"),
                    "merge",
                    "-O",
                    "-o",
                    str(merged),
                    *(str(f) for f in files),
                ]
            )
        elif dataset.clip:
            merged = files[0]

        if dataset.clip:
            box = dataset.clip
            # osmium takes the bbox as left,bottom,right,top — west,south,
            # east,north — which is the opposite ordering to the [s,w,n,e]
            # every bbox in this project uses. Converting here, once, rather
            # than asking anyone to keep two orderings straight.
            _run(
                [
                    require("osmium"),
                    "extract",
                    "-O",
                    "--bbox",
                    f"{box.west},{box.south},{box.east},{box.north}",
                    "-o",
                    str(dst),
                    str(merged),
                ]
            )
            if merged != dst and merged not in files:
                merged.unlink(missing_ok=True)

    size_gb = dst.stat().st_size / 1e9
    print(f"[download] {dst} ready ({size_gb:.2f} GB)")
    _write_provenance(dataset, files)
    return dst


def _write_provenance(dataset: Dataset, files: list[Path], *, note: str = "") -> None:
    record = {
        "dataset": dataset.name,
        "built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "regions": [
            {
                "region": region,
                "url": dataset.region_url(region),
                "file": path.name,
                "bytes": path.stat().st_size if path.exists() else None,
                "osm_timestamp": osm_timestamp(path) if path.exists() else "",
            }
            for region, path in zip(dataset.regions, files)
        ],
        "clip": dataset.clip.as_list() if dataset.clip else None,
        "osm_timestamp": osm_timestamp(dataset.raw) if dataset.raw.exists() else "",
    }
    if note:
        record["note"] = note
    dataset.provenance.write_text(json.dumps(record, indent=2) + "\n")
    print(f"[download] provenance -> {dataset.provenance}")
