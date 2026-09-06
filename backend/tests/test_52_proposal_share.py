"""
test_52_proposal_share.py
==========================
GET /api/proposal/<id>/share — the Open Graph link-preview stub
(api/proposal_share.py).

Covers:
  - 200 text/html (not JSON) carrying the proposal's real name as
    <title> and og:title
  - the human bounce (meta refresh) and the canonical/noindex pair that
    keep this URL out of search results in favour of /proposal/<id>
  - absolute og:image/og:url derived from X-Forwarded-Proto/-Host, since
    Caddy terminates TLS and no ProxyFix is installed — an http:// image
    URL on an https:// page is dropped by some chat clients
  - HTML-escaping of the name, which is user-supplied and lands in both
    element text and quoted attribute values
  - unknown proposal_id → 404 as a *page*, not main.py's global JSON 404

Targets: the read tests use the permanent seed proposal
(_SEED_PROPOSAL_ID, see test_50_proposals_api.py); only the escaping test
needs a publish of its own, because it needs a name no seed would have.
"""

import pytest
import requests

from tests.helpers import PROPOSAL_URL, compute, publish, purge_saved_proposals

# The permanent proposal seeded at DB init time (db/dev/seed.py).
_SEED_PROPOSAL_ID = 1
_UNKNOWN_PROPOSAL_ID = 987654321

_STOPS = ["osm:n3856100103", "osm:w423692233"]
_COMPOSITION = "NEW-BAL-7"

# Every metacharacter that matters in an HTML attribute value, plus
# non-ASCII to prove the charset declaration holds.
_NASTY_NAME = 'Berlin & "Paris" <b>Zürich</b>'


def share_url(proposal_id: int) -> str:
    return f"{PROPOSAL_URL}/{proposal_id}/share"


@pytest.fixture(scope="module")
def seed_name(api_base):
    """The seed proposal's name, read from the API rather than hard-coded
    — the assertions are about the name reaching the card, not about
    which name the seed happens to carry."""
    resp = requests.get(f"{api_base}{PROPOSAL_URL}/{_SEED_PROPOSAL_ID}", timeout=15)
    assert resp.status_code == 200, f"seed load failed: {resp.text[:200]}"
    return resp.json()["name"]


@pytest.fixture(scope="module")
def nasty_proposal(api_base, script_headers, db_conn):
    """A published proposal whose name needs escaping. Purged after —
    this module's only write."""
    body = publish(
        api_base,
        compute(api_base, _STOPS, _COMPOSITION)["request"],
        name=_NASTY_NAME,
        headers=script_headers,
    )
    yield body
    purge_saved_proposals(db_conn)


class TestSharePage:
    def test_returns_an_html_page_not_json(self, api_base, seed_name):
        resp = requests.get(f"{api_base}{share_url(_SEED_PROPOSAL_ID)}", timeout=15)
        assert resp.status_code == 200
        assert resp.headers["Content-Type"].startswith("text/html")
        assert f"<title>{seed_name}</title>" in resp.text
        assert f'property="og:title" content="{seed_name}"' in resp.text

    def test_bounces_humans_and_defers_to_the_app_url(self, api_base):
        """A crawler must see the tags, a browser must land on the SPA
        route — hence a 200 with a meta refresh rather than a redirect,
        and a canonical + noindex so this URL never outranks the real
        one."""
        resp = requests.get(f"{api_base}{share_url(_SEED_PROPOSAL_ID)}", timeout=15)
        target = f"/proposal/{_SEED_PROPOSAL_ID}"
        assert f'content="0; url={target}"' in resp.text
        assert f'<link rel="canonical" href="{target}">' in resp.text
        assert 'name="robots" content="noindex"' in resp.text

    def test_carries_the_card_metadata_a_client_needs(self, api_base):
        resp = requests.get(f"{api_base}{share_url(_SEED_PROPOSAL_ID)}", timeout=15)
        for fragment in (
            'property="og:type" content="website"',
            'property="og:description"',
            'property="og:image:width" content="1200"',
            'property="og:image:height" content="630"',
            'name="twitter:card" content="summary_large_image"',
        ):
            assert fragment in resp.text, f"missing {fragment}"

    def test_absolute_urls_follow_the_forwarded_scheme_and_host(self, api_base):
        """Caddy terminates TLS and preserves Host, so request.scheme is
        http on every deployed environment; only these headers know the
        public origin."""
        resp = requests.get(
            f"{api_base}{share_url(_SEED_PROPOSAL_ID)}",
            headers={
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "targetnetwork.example",
            },
            timeout=15,
        )
        assert resp.status_code == 200
        assert 'content="https://targetnetwork.example/og/share-card.jpg"' in resp.text
        assert (
            'property="og:url" content="https://targetnetwork.example'
            f'/api/proposal/{_SEED_PROPOSAL_ID}/share"' in resp.text
        )

    def test_escapes_the_proposal_name(self, api_base, nasty_proposal):
        """The name is user-supplied and lands in element text and in
        quoted attribute values — an unescaped quote would break out of
        the content attribute."""
        proposal_id = nasty_proposal["proposal_id"]
        resp = requests.get(f"{api_base}{share_url(proposal_id)}", timeout=15)
        assert resp.status_code == 200
        assert "<b>Zürich</b>" not in resp.text
        assert "&lt;b&gt;Z" in resp.text
        assert "&amp;" in resp.text
        assert "&quot;Paris&quot;" in resp.text

    def test_unknown_id_is_an_html_404_not_the_global_json_handler(self, api_base):
        resp = requests.get(f"{api_base}{share_url(_UNKNOWN_PROPOSAL_ID)}", timeout=15)
        assert resp.status_code == 404
        assert resp.headers["Content-Type"].startswith("text/html")
        assert '"error"' not in resp.text
        assert 'content="0; url=/gallery"' in resp.text
