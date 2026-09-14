"""Unit tests for the gate page — standard library only, no stack required.

Every other test in this directory talks to a live API. This one deliberately does
not: `api.gate_page.page_html` is pure string assembly, and the defects worth
guarding against here are the ones that survive a human read-through.

The countdown page arrived as an AI-drafted mockup on 2026-09-08. It shipped a red
rule struck through its own slogan, a Google Fonts hotlink, "about 150 night train
routes" where the repository says 100, and "1,500+ European stations" where the 1,500
figure is *carriages* and the stop catalogue holds 1,050. Each of those is cheap to
assert and expensive to notice by eye, which is what these tests are for.
"""

from __future__ import annotations

import re
from datetime import timedelta

from api.gate_page import LAUNCH, page_html

BEFORE = LAUNCH - timedelta(seconds=1)
AFTER = LAUNCH + timedelta(seconds=1)


def test_launch_moment_is_ten_hundred_cest_on_the_twenty_second():
    """David's ask, and the one date the page cannot get wrong.

    22 September 2026 falls inside CEST — European DST ends on the last Sunday of
    October — so the offset is +02:00, not +01:00.
    """
    assert LAUNCH.isoformat() == "2026-09-22T10:00:00+02:00"
    assert LAUNCH.utcoffset() == timedelta(hours=2)


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


def test_public_figures_match_the_repository():
    html = page_html(now=BEFORE)
    assert "about 100 night train lines in 2025" in html
    assert "300 by 2035" in html
    # The mockup's two wrong numbers. 1,500 is carriages (proposal.funFacts
    # .rollingStock), and the seeded stop catalogue is 1,050 stops.
    assert "150 night train" not in html
    assert "1,500" not in html
    assert "1500" not in html


def test_the_claims_carry_their_source():
    """LandingIntro.vue pins the same figures to the position paper. So does this."""
    html = page_html(now=BEFORE)
    assert "back-on-track.eu/back-on-track-europes-general-position-paper/" in html


def test_reduced_motion_is_respected():
    assert "prefers-reduced-motion" in page_html(now=BEFORE)


def test_the_countdown_is_not_a_live_region():
    """A per-second aria-live region makes a screen reader unusable."""
    assert 'aria-live="off"' in page_html(now=BEFORE)
