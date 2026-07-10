"""
feedback_serialize.py
======================
Serialization for the feedback endpoint — mirrors the existing
route_serialize.py / evaluation_serialize.py / params_serialize.py /
proposal_serialize.py split: all dict-shaping and validation lives here,
none of it in the repository or blueprint.

Public interface:
  validate_feedback_body(body)      → list[str]  (structural check of POST /api/feedback)
  feedback_response_to_dict(record) → dict        (response body for POST /api/feedback)
  build_categories_payload(loader)  → dict        (response body for GET /api/feedback/categories)

Category / sub-category are free text at the API boundary (there could
always be a new kind of feedback), not a closed enum — see
build_categories_payload()'s docstring. GET /api/feedback/categories
exists to give the frontend a populated dropdown.

Taxonomy (2026-07-10, David): nine categories split by what a submitter
is actually reacting to, each with a sub_categories list sourced from
wherever that concept's own definition already lives, so none of these
lists is a hand-maintained copy that can drift:

  Infrastructure                  — TrackInfrastructures + StopInfrastructures
                                     fields (models/params.py)
  Compositions                    — composition/operator/coach fields
                                     (models/params.py, via CompositionCollection)
  Evaluation — calculation method — the cost/revenue/margin components the
                                     evaluation model computes
                                     (models/evaluation/views.py:Breakdown)
  Evaluation — results / view     — the output views the evaluation endpoint
                                     produces (models/evaluation/views.py:VIEW_META)
  Route or timetable               — static list (no single schema object
                                     maps cleanly onto "route concepts")
  General functionality            — static list
  Bug report / Feature request / Other — free text, no sub-category list

"Infrastructure"/"value or source" feedback (a rate looks wrong) is
deliberately distinct from "Evaluation — calculation method" feedback
(the rate is applied wrong, e.g. to the wrong distance) — same rationale
that split the old single "Update of input parameter" category into
Infrastructure/Compositions here.
"""

from __future__ import annotations

import dataclasses
import re
import typing

from models.evaluation.views import VIEW_META, Breakdown
from models.params import TRACK_INFRA_FIELD_NAMES

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_SUBJECT_MAX_LEN = 200

_CATEGORY_INFRASTRUCTURE = "Infrastructure"
_CATEGORY_COMPOSITIONS = "Compositions"
_CATEGORY_CALC_METHOD = "Evaluation — calculation method"
_CATEGORY_EVAL_VIEW = "Evaluation — results / view"
_CATEGORY_ROUTE_TIMETABLE = "Route or timetable"
_CATEGORY_GENERAL = "General functionality"
_CATEGORY_BUG = "Bug report"
_CATEGORY_FEATURE = "Feature request"
_CATEGORY_OTHER = "Other"

_STATIC_CATEGORIES = (
    _CATEGORY_INFRASTRUCTURE,
    _CATEGORY_COMPOSITIONS,
    _CATEGORY_CALC_METHOD,
    _CATEGORY_EVAL_VIEW,
    _CATEGORY_ROUTE_TIMETABLE,
    _CATEGORY_GENERAL,
    _CATEGORY_BUG,
    _CATEGORY_FEATURE,
    _CATEGORY_OTHER,
)

# No single schema object maps cleanly onto "route/timetable concepts" the
# way input parameters or the evaluation Breakdown tree do — route.py's own
# JSON shape mixes routing/scheduling/composition concerns per trip pair
# rather than exposing them as a flat, describable field list. Hand-picked
# and short by design; update here if the route-plan pipeline gains a
# section worth calling out separately.
_ROUTE_TIMETABLE_SUB_CATEGORIES = (
    "Stops / stations",
    "Schedule / timetable / frequency",
    "Routing / track geometry",
    "Composition / rolling stock assignment",
    "Country crossing / infrastructure assumptions",
    "Parking / shunting",
)

# Same reasoning as _ROUTE_TIMETABLE_SUB_CATEGORIES — general-tool feedback
# has no backing schema to derive from.
_GENERAL_SUB_CATEGORIES = (
    "Usability / UX",
    "Performance",
    "Data export",
    "Documentation",
    "Other",
)


# =============================================================================
# VALIDATE
# =============================================================================


def validate_feedback_body(body: dict) -> list[str]:
    """Structural validation of a POST /api/feedback payload. At least one
    of user_id/email must identify the author — user_id is checked against
    admin.users by the caller (api/feedback.py), not here, since that
    needs a DB round-trip."""
    errors = []

    user_id = body.get("user_id")
    email = body.get("email")

    if user_id is None and not email:
        errors.append("Either 'user_id' or 'email' must be provided.")
    if user_id is not None and not isinstance(user_id, int):
        errors.append("'user_id' must be an integer if provided.")
    if email is not None:
        if not isinstance(email, str) or not _EMAIL_PATTERN.match(email.strip()):
            errors.append("'email' must be a valid email address if provided.")

    for field_name in ("subject", "category", "sub_category", "message"):
        value = body.get(field_name)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"'{field_name}' is required and must be a non-empty string.")

    subject = body.get("subject")
    if isinstance(subject, str) and len(subject) > _SUBJECT_MAX_LEN:
        errors.append(f"'subject' must be at most {_SUBJECT_MAX_LEN} characters.")

    return errors


# =============================================================================
# SERIALIZE — response
# =============================================================================


def feedback_response_to_dict(record: dict, email_sent: bool) -> dict:
    """Response body for POST /api/feedback — a mail-sent confirmation
    plus enough identity to reference the stored row (see module
    docstring: the endpoint's purpose is the mail, not the record)."""
    return {
        "feedback_id": record["feedback_id"],
        "created_at": record["created_at"].isoformat(),
        "email_sent": email_sent,
    }


# =============================================================================
# SERIALIZE — categories — Infrastructure / Compositions
# (input-parameter fields, via models/params.py's own collections)
# =============================================================================


def _flatten_descriptions(node: object, path: list[str], out: list[dict]) -> None:
    """Recursively walk a params_serialize-style descriptions dict (nested
    per response section, e.g. CompositionCollection.descriptions) and
    collect one entry per leaf field. Leaves are {field_name: description}
    pairs; branches are further sections to recurse into — the same shape
    distinction params_serialize.py's response sections already use, just
    walked instead of hand-flattened."""
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if isinstance(value, dict):
            _flatten_descriptions(value, path + [key], out)
        else:
            out.append(
                {
                    "parameter": ".".join(path + [key]),
                    "description": value,
                }
            )


def _infrastructure_sub_categories(loader, scenario_id: int | None) -> list[dict]:
    """Every TrackInfrastructures + StopInfrastructures field — the same
    two collections GET /api/params/TrackInfrastructures and
    GET /api/params/StopInfrastructures serve, not a separately
    hand-maintained list."""
    track_infra = loader.build_all_tracks(scenario_id)
    stop_infra = loader.build_all_stops(scenario_id)

    entries: list[dict] = [
        {
            "parameter": field_name,
            "description": track_infra.descriptions.fields.get(field_name),
            "group": "TrackInfrastructures",
        }
        for field_name in TRACK_INFRA_FIELD_NAMES
    ]
    entries += [
        {
            "parameter": field_name,
            "description": description,
            "group": "StopInfrastructures",
        }
        for field_name, description in stop_infra.descriptions.fields.items()
    ]
    entries.sort(key=lambda e: (e["group"], e["parameter"]))
    return entries


def _composition_sub_categories(loader, scenario_id: int | None) -> list[dict]:
    """Every composition/operator/coach field — the same
    CompositionCollection GET /api/params/compositions serves."""
    compositions = loader.build_all_compositions(scenario_id)

    leaves: list[dict] = []
    _flatten_descriptions(compositions.descriptions, [], leaves)
    entries = [{**leaf, "group": "Compositions"} for leaf in leaves]
    entries.sort(key=lambda e: e["parameter"])
    return entries


# =============================================================================
# SERIALIZE — categories — Evaluation calculation method
# (models/evaluation/views.py's own Breakdown dataclass tree)
# =============================================================================


def _explicit_docstring(dc_type: type) -> str | None:
    """dc_type.__doc__, or None — filters out the constructor-signature
    string @dataclass auto-generates for a class with no docstring of its
    own (e.g. "RevenueBreakdown(ticket_revenue_eur: 'float' = 0.0)"),
    which would otherwise be indistinguishable from a real description."""
    doc = (dc_type.__doc__ or "").strip()
    if not doc or doc.startswith(f"{dc_type.__name__}("):
        return None
    return doc


def _breakdown_leaf_fields() -> list[dict]:
    """Every leaf field of the evaluation model's Breakdown dataclass tree
    (cost.operator.variable.driver_eur, cost.infrastructure.tac_eur,
    revenue.ticket_revenue_eur, margin.ebit_margin_eur, ...) — read via
    dataclass introspection rather than hand-copied, so a cost/revenue
    component added to the model shows up here automatically. group is the
    top-level branch (cost/revenue/margin); description is the immediate
    containing dataclass's own docstring, where one exists."""
    entries: list[dict] = []

    def walk(dc_type: type, path: list[str]) -> None:
        hints = typing.get_type_hints(dc_type)
        for f in dataclasses.fields(dc_type):
            field_type = hints[f.name]
            full_path = path + [f.name]
            if dataclasses.is_dataclass(field_type):
                walk(field_type, full_path)
            else:
                entries.append(
                    {
                        "parameter": ".".join(full_path),
                        "description": _explicit_docstring(dc_type),
                        "group": path[0] if path else full_path[0],
                    }
                )

    walk(Breakdown, [])
    entries.sort(key=lambda e: (e["group"], e["parameter"]))
    return entries


# =============================================================================
# SERIALIZE — categories — Evaluation results / view
# (models/evaluation/views.py's own VIEW_META)
# =============================================================================


def _evaluation_view_sub_categories() -> list[dict]:
    """The output views POST /api/evaluation/calc actually produces — the
    same VIEW_META api/helpers/evaluation_serialize.py builds each view's
    response section from, not a separately hand-maintained list."""
    return [
        {
            "parameter": view,
            "description": meta["description"],
            "group": None,
        }
        for view, meta in sorted(VIEW_META.items())
    ]


# =============================================================================
# SERIALIZE — categories — static lists
# =============================================================================


def _static_sub_categories(values: tuple[str, ...]) -> list[dict]:
    return [{"parameter": v, "description": None, "group": None} for v in values]


# =============================================================================
# SERIALIZE — categories — top-level assembly
# =============================================================================


def build_categories_payload(loader, scenario_id: int | None = None) -> dict:
    """
    Response body for GET /api/feedback/categories — suggested values for
    the feedback form's category/sub_category fields. Category is never
    restricted to this list at submission time (see module docstring);
    this is guidance for a dropdown, not a validation source.

    Query params (passed through by api/feedback.py):
      scenario_id : int (optional) — pins the parameter versions the
                    Infrastructure/Compositions sub-category lists are
                    built from; omit for the live is_current_base scenario.
                    Has no effect on the other categories.
    """
    return {
        "categories": [
            {
                "category": _CATEGORY_INFRASTRUCTURE,
                "sub_categories": _infrastructure_sub_categories(loader, scenario_id),
            },
            {
                "category": _CATEGORY_COMPOSITIONS,
                "sub_categories": _composition_sub_categories(loader, scenario_id),
            },
            {
                "category": _CATEGORY_CALC_METHOD,
                "sub_categories": _breakdown_leaf_fields(),
            },
            {
                "category": _CATEGORY_EVAL_VIEW,
                "sub_categories": _evaluation_view_sub_categories(),
            },
            {
                "category": _CATEGORY_ROUTE_TIMETABLE,
                "sub_categories": _static_sub_categories(
                    _ROUTE_TIMETABLE_SUB_CATEGORIES
                ),
            },
            {
                "category": _CATEGORY_GENERAL,
                "sub_categories": _static_sub_categories(_GENERAL_SUB_CATEGORIES),
            },
            {"category": _CATEGORY_BUG, "sub_categories": []},
            {"category": _CATEGORY_FEATURE, "sub_categories": []},
            {"category": _CATEGORY_OTHER, "sub_categories": []},
        ]
    }
