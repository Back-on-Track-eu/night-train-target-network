"""The date is the selector, so these are the tests that matter most.

They run against the real catalogue rather than a fixture: the point of the
design is that one file produces every horizon, and a fixture would not catch
a catalogue entry whose dates contradict its prose.
"""

from __future__ import annotations

import datetime as dt

import pytest

from osm_pipe.catalogue import load_catalogue
from osm_pipe.config import CATALOGUE_DIR
from osm_pipe.rules import rules_for, select
from osm_pipe.config import load_target


@pytest.fixture(scope="module")
def catalogue():
    return load_catalogue(CATALOGUE_DIR / "europe.yml")


def test_catalogue_loads(catalogue):
    assert len(catalogue.projects) > 20
    # Every project needs a source: an undated, uncited entry is an opinion.
    for project in catalogue.projects:
        assert project.sources, f"{project.id} has no source"


def test_later_horizon_is_a_superset(catalogue):
    at_2032 = set(catalogue.select(as_of=dt.date(2032, 12, 31)).ids)
    at_2040 = set(catalogue.select(as_of=dt.date(2040, 12, 31)).ids)
    assert at_2032 < at_2040, "a later date must never drop a project"


def test_today_selects_only_what_has_opened(catalogue):
    selection = catalogue.select(as_of=dt.date(2026, 8, 29))
    # Koralm opened 2025-12-14. It is the control case: it must be in every
    # network including the baseline, at every date after it opened.
    assert "koralmbahn" in selection.ids
    assert "fehmarn-belt" not in selection.ids


def test_semmering_is_the_date_test(catalogue):
    # Both its dates agree on 2030, which makes it the one project whose
    # in/out flips cleanly on the horizon alone — no date_basis argument, no
    # override. The austria dataset exists to exercise exactly this.
    assert (
        "semmering-base-tunnel" not in catalogue.select(as_of=dt.date(2029, 12, 31)).ids
    )
    assert "semmering-base-tunnel" in catalogue.select(as_of=dt.date(2031, 12, 31)).ids


def test_koralm_is_in_at_every_horizon(catalogue):
    for year in (2026, 2032, 2040):
        selection = catalogue.select(as_of=dt.date(year, 12, 31))
        assert "koralmbahn" in selection.ids, f"control case missing at {year}"


def test_date_basis_changes_the_answer(catalogue):
    # Brenner: official 2032, latest 2034. The choice of basis is the whole
    # difference between an optimistic and a pessimistic 2032 network.
    as_of = dt.date(2032, 12, 31)
    optimistic = catalogue.select(as_of=as_of, date_basis="official").ids
    pessimistic = catalogue.select(as_of=as_of, date_basis="latest").ids
    assert "brenner-base-tunnel" in optimistic
    assert "brenner-base-tunnel" not in pessimistic


def test_force_in_believes_the_official_date(catalogue):
    as_of = dt.date(2032, 12, 31)
    forced = catalogue.select(
        as_of=as_of,
        date_basis="latest",
        force_in={"brenner-base-tunnel": "official target is 2032"},
    )
    assert "brenner-base-tunnel" in forced.ids


def test_force_in_never_overrides_both_dates(catalogue):
    # The failure this guards against: an unconditional force_in would drop a
    # 2032 tunnel into the baseline the moment anyone ran --as-of today, and
    # the baseline is what every other date is measured against.
    selection = catalogue.select(
        as_of=dt.date(2026, 8, 29),
        force_in={"brenner-base-tunnel": "official target is 2032"},
    )
    assert "brenner-base-tunnel" not in selection.ids
    reasons = {p.id: reason for p, reason in selection.excluded}
    assert "force_in ignored" in reasons["brenner-base-tunnel"]


def test_force_out_is_unconditional(catalogue):
    selection = catalogue.select(
        as_of=dt.date(2040, 12, 31),
        force_out={"rail-baltica": "single-track phase 1"},
    )
    assert "rail-baltica" not in selection.ids


def test_unknown_override_id_is_an_error(catalogue):
    with pytest.raises(KeyError, match="typo-project"):
        catalogue.select(as_of=dt.date(2032, 12, 31), force_in={"typo-project": "x"})


# -- the shipped targets ---------------------------------------------------


def test_target_2032_includes_the_arguable_two():
    target = load_target("2032")
    selection = select(target)
    # Both are past their pessimistic date and in only because 2032.yml says
    # so with a reason. If either drops out, that file needs re-reading.
    assert "brenner-base-tunnel" in selection.ids
    assert "rail-baltica" in selection.ids


def test_baseline_is_todays_date_and_changes_almost_nothing():
    target = load_target("2032").with_as_of(dt.date(2026, 8, 29))
    selection, rules = rules_for(target)
    assert selection.ids == ("koralmbahn",)
    # Koralm is already railway=rail, so its promotion should be close to a
    # no-op — but it still generates rules, which is why the baseline is not
    # guaranteed to be a pure identity transform.
    assert all(r.project == "koralmbahn" for r in rules)


def test_all_planned_selects_no_projects_and_uses_extra_rules():
    target = load_target("all-planned")
    selection, rules = rules_for(target)
    assert selection.ids == ()
    assert rules, "all-planned must still produce rules, from extra_rules"
    assert all(r.project == "" for r in rules)
    # Global by design — that is what makes it an upper bound rather than a
    # network anyone should publish from.
    assert all(not r.ways and not r.within for r in rules)
