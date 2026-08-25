"""proposal_share.py — link-preview stub for a shared proposal.

    GET /api/proposal/<id>/share

The one HTML-returning route in the api package besides api/gate.py, and
it exists for a single reason: **WhatsApp, Signal, Telegram and mail
clients build their preview card by fetching the shared URL and reading
its Open Graph tags, and none of them run JavaScript.** The SPA's
index.html can therefore never say which proposal a link points at — a
crawler sees the empty shell. So the frontend shares *this* URL, which
answers 200 with the real tags and bounces a human browser on to
/proposal/<id>.

Deliberately mounted under /api even though it is a page, not an API:
Caddy routes /api/* to this container and everything else to the
frontend image, so /api is the only prefix that reaches Flask without a
new vhost block.

Three things this route must keep doing:

* **Escape the name.** It is user-supplied and lands in an HTML title and
  in meta content attributes. html.escape(quote=True) on every
  interpolation is the whole defence.
* **Answer 200, not 302.** A redirect would hand the crawler the SPA
  shell and lose the tags. The human bounce is a meta refresh (no JS, so
  it survives a strict CSP) which crawlers do not follow — which is
  exactly the split we want.
* **Return its own 404 body.** main.py's global 404 handler emits JSON;
  an unknown id here should still be a page.

No rate limit, following api/gate.py's reasoning: Flask-Limiter keys on
get_remote_address, which behind Caddy is the proxy hop, so a limit here
would be one bucket shared by every visitor. The route costs a single
indexed primary-key lookup, and the neighbouring public reads
(GET /api/proposal/<id>, /engagements) are unlimited for the same reason.

Known deployment constraint: an environment fronted by the testing gate
or basic-auth cannot produce preview cards at all — the crawler gets
Caddy's 302 to /gate. This path needs the same forward_auth exemption
/gate and /api/gate/* have.
"""

from __future__ import annotations

import html
import logging

from flask import Blueprint, Response, make_response, request

from api.helpers.dependencies import get_proposal_repository

log = logging.getLogger(__name__)
bp = Blueprint("proposal_share", __name__)

# Served by the frontend image out of frontend/public/, so it is same-origin
# with this route on any deployed environment (one Caddy vhost fronts both).
# 1200x630 is what yields the large card rather than a thumbnail; the
# dimension tags below let a client size the card before fetching the file.
OG_IMAGE_PATH = "/og/share-card.jpg"
OG_IMAGE_WIDTH = "1200"
OG_IMAGE_HEIGHT = "630"

OG_SITE_NAME = "Back-on-Track Target Network"

# One unchanging line for every proposal. The route figures (distance,
# stops, countries) are deliberately NOT here: the sharer's own message
# carries them, composed in the frontend where the locale is known — this
# backend has no i18n, so anything written here is English for everyone.
# Never put co2_savings_t_per_year or the demand KPIs in a shared card:
# proposal_summaries.demand_kpis_placeholder is TRUE, those numbers are
# deterministic fakes, and a forwarded message is precisely where a
# placeholder gets read as fact.
OG_DESCRIPTION = (
    "A night train route modelled on the Back-on-Track Target Network — "
    "see the itinerary, the timetable, and what it would take to run it."
)

_NOT_FOUND_TITLE = "Proposal not found"
_NOT_FOUND_DESCRIPTION = (
    "This night train proposal no longer exists. Browse the Target Network "
    "to see what else has been proposed."
)

# No <style> block on purpose: the page is on screen for one frame before
# the refresh fires, and braces would fight the f-string in _render().
_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<meta name="robots" content="noindex">
<link rel="canonical" href="{target}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{site_name}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:url" content="{share_url}">
<meta property="og:image" content="{image_url}">
<meta property="og:image:width" content="{image_width}">
<meta property="og:image:height" content="{image_height}">
<meta name="twitter:card" content="summary_large_image">
<meta http-equiv="refresh" content="0; url={target}">
</head><body>
<p><a href="{target}">{title}</a></p>
</body></html>
"""


def _public_origin() -> str:
    """scheme://host as the outside world sees it.

    og:image and og:url must be absolute, and an http:// image on an
    https:// page is dropped by some clients. Caddy terminates TLS and
    preserves the Host header, so request.scheme is "http" on every
    deployed environment and only X-Forwarded-Proto knows better. No
    ProxyFix is installed (see the note in
    db/dev/sql/migrations/2026-08-17_testing_gate_access_codes.sql), so
    the headers are read here rather than trusting request.host_url.
    Either header may be a comma-list through several hops; the
    client-most value is the first.
    """
    proto = (request.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip()
    host = (request.headers.get("X-Forwarded-Host") or "").split(",")[0].strip()
    return f"{proto or request.scheme}://{host or request.host}"


def _render(
    *, title: str, description: str, target: str, share_url: str, status: int
) -> Response:
    origin = _public_origin()
    page = _PAGE.format(
        title=html.escape(title, quote=True),
        description=html.escape(description, quote=True),
        site_name=html.escape(OG_SITE_NAME, quote=True),
        target=html.escape(target, quote=True),
        share_url=html.escape(share_url, quote=True),
        image_url=html.escape(f"{origin}{OG_IMAGE_PATH}", quote=True),
        image_width=OG_IMAGE_WIDTH,
        image_height=OG_IMAGE_HEIGHT,
    )
    resp = make_response(page, status)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    # A proposal's name and identity change rarely; a crawl storm on a
    # popular link should not be one query per fetch. Short enough that a
    # rename shows up in a new share the same day.
    resp.headers["Cache-Control"] = (
        "public, max-age=300" if status == 200 else "no-store"
    )
    return resp


@bp.get("/proposal/<int:proposal_id>/share")
def share_page(proposal_id: int) -> Response:
    """Open Graph stub for one proposal — 200 HTML for a crawler, an
    instant meta-refresh to /proposal/<id> for a human."""
    name = get_proposal_repository().share_name(proposal_id)
    origin = _public_origin()
    if name is None:
        return _render(
            title=_NOT_FOUND_TITLE,
            description=_NOT_FOUND_DESCRIPTION,
            target="/gallery",
            share_url=f"{origin}/api/proposal/{proposal_id}/share",
            status=404,
        )
    return _render(
        title=name,
        description=OG_DESCRIPTION,
        target=f"/proposal/{proposal_id}",
        share_url=f"{origin}/api/proposal/{proposal_id}/share",
        status=200,
    )
