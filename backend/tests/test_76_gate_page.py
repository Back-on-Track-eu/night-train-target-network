"""Unit tests for the gate page — standard library only, no stack required.

Every other test in this directory talks to a live API. This one deliberately does
not: `api.gate_page.page_html` is pure string assembly, and the defects worth
guarding against here are the ones that survive a human read-through.

The countdown page arrived as an AI-drafted mockup on 2026-09-08. It shipped a red
rule struck through its own slogan, a Google Fonts hotlink, and "1,500+ European
stations" where the 1,500 figure is *carriages* and the stop catalogue holds about
1,200. Since 2026-09-16 the page carries the launch press text and a media gallery,
which adds two more things worth pinning: every date on the page comes from
`LAUNCH`, and a slide is rendered only when its file is on disk (the media is
not in git — scripts/fetch_gate_media.py puts it there — so the page must
degrade to text, never to broken pictures). Each of those is
cheap to assert and expensive to notice by eye, which is what these tests are for.
"""

from __future__ import annotations

import re
from datetime import timedelta

import pytest

from api.gate_page import (
    GALLERY,
    LAUNCH,
    MEDIA_DIR,
    MEDIA_URL,
    SLIDE_SECONDS,
    VIDEO,
    launch_day,
    launch_when,
    media_files,
    page_html,
)
from scripts.fetch_gate_media import unpack

BEFORE = LAUNCH - timedelta(seconds=1)
AFTER = LAUNCH + timedelta(seconds=1)


def test_launch_moment_is_ten_hundred_cest_on_the_twenty_second():
    """David's ask, and the one date the page cannot get wrong.

    22 September 2026 falls inside CEST — European DST ends on the last Sunday of
    October — so the offset is +02:00, not +01:00.
    """
    assert LAUNCH.isoformat() == "2026-09-22T10:00:00+02:00"
    assert LAUNCH.utcoffset() == timedelta(hours=2)
    assert launch_day() == "22 September"
    assert launch_when() == "22 September 2026, 10:00 CEST"


def test_every_date_on_the_page_comes_from_launch():
    """The press text names the launch day three times, the hero once, the <title>
    once. All of them are derived, so moving LAUNCH moves the whole page — and no
    other September day may be typed anywhere in it."""
    html = page_html(now=BEFORE)
    assert f"<title>Target Network — opens {launch_day()}</title>" in html
    assert f"{launch_when()} — live from" in _hero(html)
    assert html.count(launch_day()) >= 5
    assert not re.search(r"\b(?!22\b)\d{1,2} September\b", html)


def _flat(html: str) -> str:
    """The document with source line wraps collapsed, so prose can be asserted on."""
    return re.sub(r"\s+", " ", html)


def _hero(html: str) -> str:
    """Just the hero section.

    Asserting on the whole document is wrong here: the swap-at-zero handler carries
    the launched markup as a JavaScript string, so "Open the Target Network" is
    legitimately present in the source of the counting-down page. What matters is
    what is *rendered*.
    """
    start = html.index('<section class="hero">')
    return html[start : html.index("</section>", start)]


def test_before_launch_counts_down():
    html = page_html(now=BEFORE)
    assert 'id="clock"' in html
    assert f'data-target="{LAUNCH.isoformat()}"' in html
    assert "Target Network opens in" in _hero(html)
    assert "Open the Target Network" not in _hero(html)


def test_after_launch_offers_the_way_in_without_javascript():
    """The switch is decided server-side, so a stopped clock or no JS still works."""
    html = page_html(now=AFTER)
    assert "The Target Network is open" in html
    assert 'href="/">Open the Target Network' in _hero(html)
    assert 'id="clock"' not in _hero(html)


def test_the_form_still_posts_to_the_redeem_endpoint():
    """The mockup's Enter button had no handler and no form. This is the gate."""
    html = page_html(now=BEFORE)
    assert '<form method="POST" action="/api/gate/redeem">' in html
    assert 'name="code"' in html


def test_an_error_opens_the_code_box_and_is_escaped():
    html = page_html(error="Nope <script>alert(1)</script>", now=BEFORE)
    assert 'class="codebox open"' in html
    assert 'aria-expanded="true"' in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_no_error_leaves_the_code_box_collapsed():
    html = page_html(now=BEFORE)
    assert 'class="codebox"' in html
    assert 'aria-expanded="false"' in html


def test_every_placeholder_is_substituted():
    """A missed placeholder renders as literal `__LOGO__` on a public page."""
    for kwargs in ({"now": BEFORE}, {"now": AFTER}, {"now": BEFORE, "error": "x"}):
        html = page_html(**kwargs)
        assert not re.findall(r"__[A-Z]+__", html)


def test_no_third_party_asset_is_fetched():
    """The most public URL Back-on-Track has must not leak visitor IPs.

    Back-on-Track is its own data controller; hotlinking a font CDN would send every
    visitor's address to a third party before they have agreed to anything. The badge
    travels as a data URI and the type is a system stack for the same reason.
    """
    html = page_html(now=BEFORE)
    for host in ("googleapis.com", "gstatic.com", "cdn.", "unpkg", "jsdelivr"):
        assert host not in html
    assert "data:image/png;base64," in html


def test_public_figures_match_the_press_text():
    """The figures are the launch press release's (2026-09-16), verbatim."""
    html = _flat(page_html(now=BEFORE))
    assert "from about 150 today to 300" in html
    assert "triple the number of night train passengers by 2032" in html
    assert "between 500 and 3,000&nbsp;km" in html
    assert "0.3% of the total greenhouse gas emissions" in html
    assert "70% of Europeans" in html
    assert "twelve different train compositions" in html
    # The mockup's wrong number. 1,500 is carriages (proposal.funFacts
    # .rollingStock), not stations.
    assert "1,500" not in html
    assert "1500" not in html


def test_the_two_quotes_are_attributed():
    html = page_html(now=BEFORE)
    assert "Juri Maier, Chairperson Back-on-Track Europe" in html
    assert "David Wedekind, Project Lead Target Network" in html
    assert html.count("<blockquote>") == 2


def test_the_claims_carry_their_source():
    """LandingIntro.vue pins the same figures to the position paper. So does this."""
    html = page_html(now=BEFORE)
    assert "back-on-track.eu/back-on-track-europes-general-position-paper/" in html


def test_reduced_motion_is_respected():
    assert "prefers-reduced-motion" in page_html(now=BEFORE)


def test_the_countdown_is_not_a_live_region():
    """A per-second aria-live region makes a screen reader unusable."""
    assert 'aria-live="off"' in page_html(now=BEFORE)


# =============================================================================
# The slideshow
# =============================================================================


def _stage(html: str) -> str:
    start = html.index('<div class="stage">')
    return html[start : html.index("</div>", start)]


@pytest.fixture
def full_media(tmp_path):
    """A media directory holding every file the page lists (empty files: the
    page checks presence, not content)."""
    for name in media_files():
        (tmp_path / name).write_bytes(b"")
    return tmp_path


def test_media_on_disk_is_exactly_what_the_page_lists():
    """If the fetch ran, it must have produced the whole set and nothing else.

    Skipped rather than failed on a checkout without the media: the directory is
    gitignored and filled by scripts/fetch_gate_media.py (at image build, or by
    hand). A partial directory IS a failure — one broken slide among nine.
    """
    if not MEDIA_DIR.is_dir() or not any(MEDIA_DIR.iterdir()):
        pytest.skip("no gate media on disk — run scripts/fetch_gate_media.py")
    on_disk = sorted(p.name for p in MEDIA_DIR.iterdir())
    assert on_disk == sorted(media_files())


def test_one_slideshow_video_first_then_every_screenshot_once(full_media):
    html = page_html(now=BEFORE, media_dir=full_media)
    stage = _stage(html)
    assert stage.count('<figure class="slide">') == len(GALLERY) + 1
    assert stage.index("<video") < stage.index("<img")
    for item in GALLERY:
        assert stage.count(f'src="{MEDIA_URL}/{item.stem}.jpg"') == 1, item.stem
        # Once as alt text, once as the caption the script copies out.
        assert stage.count(item.caption) == 2, item.stem
    assert f'data-seconds="{SLIDE_SECONDS}"' in html


def test_without_media_the_slideshow_is_left_out_entirely(tmp_path):
    """No files, no section — not an empty box with nine broken pictures."""
    html = page_html(now=BEFORE, media_dir=tmp_path)
    assert 'class="show"' not in html
    assert MEDIA_URL not in html
    assert "Double the connections" in html  # the rest of the page is intact


def test_a_slide_without_its_file_is_skipped(full_media):
    (full_media / f"{GALLERY[0].stem}.jpg").unlink()
    (full_media / f"{VIDEO.stem}.mp4").unlink()  # poster alone is not a video slide
    stage = _stage(page_html(now=BEFORE, media_dir=full_media))
    assert stage.count('<figure class="slide">') == len(GALLERY) - 1
    assert "<video" not in stage
    assert GALLERY[0].stem not in stage


def test_the_walkthrough_is_muted_and_waits_for_its_slide(full_media):
    """Muted so a browser lets the script start it; no autoplay attribute so
    without the script it is a poster with a play button, not nine things
    playing at once. And nothing on the page counts its seconds."""
    html = page_html(now=BEFORE, media_dir=full_media)
    video = html[html.index("<video") : html.index("</video>")]
    assert f'src="{MEDIA_URL}/{VIDEO.stem}.mp4"' in video
    assert f'poster="{MEDIA_URL}/{VIDEO.stem}-poster.jpg"' in video
    for attr in ("muted", "playsinline", "controls"):
        assert f" {attr}" in video, attr
    assert "autoplay" not in video
    assert "loop" not in video
    assert "Twenty-two" not in html
    assert "22 seconds" not in html


def test_the_position_paper_link_sits_under_the_first_section():
    html = page_html(now=BEFORE)
    link = html.index("back-on-track-europes-general-position-paper")
    assert html.index("Double the connections") < link
    assert link < html.index("Network planning as a game")


def test_media_stays_on_this_origin(full_media):
    """Same rule as the font: nothing the page loads leaves back-on-track.eu."""
    html = page_html(now=BEFORE, media_dir=full_media)
    for src in re.findall(r'(?:src|href|poster)="([^"]+)"', html):
        if src.startswith(("http://", "https://", "//")):
            assert "back-on-track.eu" in src, src


# =============================================================================
# The fetch script's unpack step (the download itself is not tested here)
# =============================================================================


def _zip_with(path, members: dict[str, bytes]):
    import zipfile

    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def test_unpack_flattens_the_archive_and_ignores_strays(tmp_path):
    """A zip made from the folder carries a gate_media/ prefix; one made from
    its contents does not. Either way only the listed names land, flat."""
    wanted = media_files()
    members = {f"gate_media/{wanted[0]}": b"a", wanted[1]: b"b"}
    members["__MACOSX/._" + wanted[0]] = b"junk"
    members["gate_media/notes.txt"] = b"stray"
    archive = _zip_with(tmp_path / "in.zip", members)
    target = tmp_path / "out"
    written = unpack(archive, target)
    assert sorted(written) == sorted(wanted[:2])
    assert sorted(p.name for p in target.iterdir()) == sorted(wanted[:2])
    assert (target / wanted[0]).read_bytes() == b"a"


def test_unpack_never_overwrites_a_local_file_unless_forced(tmp_path):
    name = media_files()[0]
    archive = _zip_with(tmp_path / "in.zip", {name: b"drive"})
    target = tmp_path / "out"
    target.mkdir()
    (target / name).write_bytes(b"mine")
    assert unpack(archive, target) == []
    assert (target / name).read_bytes() == b"mine"
    assert unpack(archive, target, force=True) == [name]
    assert (target / name).read_bytes() == b"drive"
