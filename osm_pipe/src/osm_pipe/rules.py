"""Turn a target plus a catalogue into the rule list the transform applies.

One function, and it is the seam between "what we believe about the world" and
"what happens to the .pbf". Keeping it in its own module means `osm-pipe
projects` can show exactly what a date selects without touching an OSM file.
"""

from __future__ import annotations

from .catalogue import Catalogue, Selection, load_catalogue
from .changes import expand
from .config import CATALOGUE_DIR, Rule, Target


def load_target_catalogue(target: Target) -> Catalogue:
    return load_catalogue(CATALOGUE_DIR / f"{target.catalogue_name}.yml")


def select(target: Target, catalogue: Catalogue | None = None) -> Selection:
    catalogue = catalogue or load_target_catalogue(target)
    return catalogue.select(
        as_of=target.as_of,
        date_basis=target.date_basis,
        force_in={o.id: o.reason for o in target.force_in},
        force_out={o.id: o.reason for o in target.force_out},
        all_projects=target.all_projects,
    )


def rules_for(
    target: Target, catalogue: Catalogue | None = None
) -> tuple[Selection, tuple[Rule, ...]]:
    """The selected projects, and the rules they expand to.

    Project order follows the catalogue, and within a project the change order
    is fixed by `changes.PHASES`. Rules chain — each one matches against the
    output of the ones before it — so both orders are load-bearing. Projects
    are independent of each other because every non-promote rule matches on
    `ntn:project`, which only that project's own promotions set.
    """
    catalogue = catalogue or load_target_catalogue(target)
    selection = select(target, catalogue)

    rules: list[Rule] = []
    for project in selection.included:
        rules.extend(
            expand(
                project_id=project.id,
                specs=project.changes,
                scope=project.scope,
                opening=project.opening_on(target.date_basis),
            )
        )

    # The escape hatch, applied last so a what-if can key off the markers the
    # catalogue's own rules left behind.
    rules.extend(target.extra_rules)
    return selection, tuple(rules)
