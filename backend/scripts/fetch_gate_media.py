"""
fetch_gate_media.py
===================
Put the gate page's screenshots and walkthrough video in api/gate_media/.

The files are not in git (no media in the repo — .gitignore) and the page
must not depend on Drive at request time, so they are fetched ONCE, at image
build (backend/docker/Dockerfile) rather than at container start: the server
compose files replace the seed-on-start entrypoint with a plain gunicorn
command, so a start-time hook would never run there. Same shape as the
other Drive-hosted inputs (export_country_geoms.py, the graph cache): check
what is there, fetch what is not, carry on.

One zip on Drive, one id (GATE_MEDIA_FILE_ID, code default below). The
archive is flattened on the way in — only the names api/gate_page.py lists
are taken, wherever they sit inside the zip — and a file already present is
never overwritten, so a screenshot placed by hand wins over the download.

Soft-failing by design: the page hides any slide whose file is missing, and
the whole slideshow when none are there, so a build without Drive access
still ships a working API with a text-only gate page. The Dockerfile turns a
non-zero exit into a warning; a host-side run reports it.

Manual runs:

    cd backend
    uv run python scripts/fetch_gate_media.py           # fetch what is missing
    uv run python scripts/fetch_gate_media.py --force   # re-download everything

Refreshing the media: upload the new gate_media.zip as a NEW VERSION of the
same Drive file (Manage versions) so the id survives, then rebuild the image
(`--no-cache` if nothing else in backend/ changed, since the fetch layer sits
behind `COPY . .`).
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

# backend/ on the path so `api.gate_page` resolves from any working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.gate_page import MEDIA_DIR, media_files  # noqa: E402

GATE_MEDIA_FILE_ID = os.environ.get(
    "GATE_MEDIA_FILE_ID", "1h6emMrrtPAqTvZkHK96DRDtybMVdOKxl"
)

# Same endpoint as db/ontd/xlsx_utils.drive_download_url(), repeated here
# because that module imports openpyxl at load and this script has to run on
# the bare image python before the venv is on PATH. confirm=t pre-answers the
# virus-scan interstitial Drive shows for files it cannot scan.
_DOWNLOAD_URL = "https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"


def missing(target: Path = MEDIA_DIR) -> list[str]:
    return [name for name in media_files() if not (target / name).is_file()]


def download(file_id: str, destination: Path) -> None:
    """Fetch the zip; raise on anything that is not one.

    A Drive permission error returns an HTML page, which would otherwise fail
    inside the zip reader with a far less legible message.
    """
    print(f"  downloading gate media from Drive (id={file_id})...")
    urllib.request.urlretrieve(_DOWNLOAD_URL.format(file_id=file_id), destination)
    if not zipfile.is_zipfile(destination):
        raise ValueError(
            f"downloaded content is not a zip ({destination.stat().st_size} bytes) "
            "— wrong file id, or the Drive file is not shared publicly"
        )
    print(f"  downloaded {destination.stat().st_size / 1e6:.1f} MB.")


def unpack(
    archive: Path, target: Path = MEDIA_DIR, *, force: bool = False
) -> list[str]:
    """Copy the page's files out of the zip into `target`, flat. Returns the names written.

    Directory layout inside the zip is irrelevant (a zip made from the folder
    carries a `gate_media/` prefix, one made from its contents does not);
    anything the page does not list — a stray file, `__MACOSX/` — is ignored.
    """
    wanted = set(media_files())
    target.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            name = Path(member.filename).name
            if member.is_dir() or name not in wanted:
                continue
            if (target / name).exists() and not force:
                continue
            (target / name).write_bytes(zf.read(member))
            written.append(name)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--force", action="store_true", help="re-download and overwrite every file"
    )
    args = parser.parse_args(argv)

    gaps = missing()
    if not gaps and not args.force:
        print(f"Gate media complete in {MEDIA_DIR.name}/ ({len(media_files())} files).")
        return 0
    print(f"Gate media: {len(gaps)} of {len(media_files())} file(s) missing.")

    archive = MEDIA_DIR.parent / "gate_media.zip"
    try:
        download(GATE_MEDIA_FILE_ID, archive)
        written = unpack(archive, force=args.force)
    except Exception as e:
        print(f"  fetch failed ({type(e).__name__}: {e}).")
        return 1
    finally:
        archive.unlink(missing_ok=True)

    for name in written:
        print(f"    + {name} ({(MEDIA_DIR / name).stat().st_size / 1e6:.2f} MB)")
    still = missing()
    if still:
        print(f"  WARNING: zip did not contain {still}; those slides stay hidden.")
        return 1
    print(f"Gate media complete in {MEDIA_DIR.name}/ ({len(written)} file(s) added).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
