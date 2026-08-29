"""A cached audit must not answer for an extract it no longer describes.

Re-auditing costs a location-index pass over the whole extract, so the result
is cached. But a stale cache here produces the one wrong answer that looks
exactly like a correct one: `diff` reports that nothing moved, which is
indistinguishable from a target that genuinely did nothing.
"""

from __future__ import annotations

import json

import pytest

from osm_survey import network


def _write(tmp_path, pbf, record):
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    (out / "summary.json").write_text(json.dumps(record))
    return out


def test_reads_back_a_matching_audit(tmp_path):
    pbf = tmp_path / "x.osm.pbf"
    pbf.write_bytes(b"hello")
    out = _write(
        tmp_path, pbf, {"total_km": 1.0, "source": network.source_fingerprint(pbf)}
    )
    assert network.read(out, pbf)["total_km"] == 1.0


def test_refuses_an_audit_whose_extract_changed(tmp_path):
    pbf = tmp_path / "x.osm.pbf"
    pbf.write_bytes(b"hello")
    out = _write(
        tmp_path, pbf, {"total_km": 1.0, "source": network.source_fingerprint(pbf)}
    )

    pbf.write_bytes(b"a different extract entirely")
    with pytest.raises(FileNotFoundError, match="stale"):
        network.read(out, pbf)


def test_refuses_an_audit_with_no_fingerprint_at_all(tmp_path):
    # Written by an older version, before the fingerprint existed. Treating it
    # as valid would silently reintroduce the bug.
    pbf = tmp_path / "x.osm.pbf"
    pbf.write_bytes(b"hello")
    out = _write(tmp_path, pbf, {"total_km": 1.0})
    with pytest.raises(FileNotFoundError, match="stale"):
        network.read(out, pbf)


def test_missing_audit_says_what_to_run(tmp_path):
    with pytest.raises(FileNotFoundError, match="osm-survey audit"):
        network.read(tmp_path, None)
