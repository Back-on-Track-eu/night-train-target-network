"""
models.py
=========
Read-only model registry.

  GET /api/models — version, description and formula registry for every
                    model in the pipeline

Static: the body depends on nothing but the running code, so it is
identical for every request until a model version bump changes it. That
is why it is an endpoint at all — it used to be inlined under
"evaluation.models" in every compute response, ~26 KB repeated per
member of a proposal family. The client fetches it once per session and
keys formulas by the same names the evaluation views use
(api/helpers/evaluation_serialize.py: models_to_dict(),
EVALUATION_OUTPUT_FIELDS).

Response building lives in api/helpers/evaluation_serialize.py, not here
— see that module's docstring.
"""

import logging

from flask import Blueprint, jsonify

from api.config import MODELS_CACHE_MAX_AGE_S
from api.helpers.evaluation_serialize import models_to_dict

logger = logging.getLogger(__name__)
bp = Blueprint("models", __name__)


@bp.get("/models")
def get_models():
    """
    Return {models: {...}} — one entry per model (route builder, energy,
    evaluation, emissions) with its version, description and formula
    registry (LaTeX, summary, description, input/output legend).

    Cache-Control is set here rather than left to the client: the body
    changes only with a deployed version bump, and a stale copy would
    show formulas that no longer match the numbers beside them — so the
    max-age is short enough that a deploy corrects it within one session
    (api/config.py).
    """
    response = jsonify({"models": models_to_dict()})
    response.headers["Cache-Control"] = f"public, max-age={MODELS_CACHE_MAX_AGE_S}"
    return response, 200
