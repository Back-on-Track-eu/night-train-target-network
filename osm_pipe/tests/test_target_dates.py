"""`--as-of` naming.

Every two-date command — `diff`, `verify` — shifts the target's date and then
shifts that result again to get its baseline. The names have to stay sane
through both, or a stage looks for a file nothing ever wrote.
"""

from __future__ import annotations

import datetime as dt

from osm_pipe.config import load_target

Y2031 = dt.date(2031, 12, 31)
Y2029 = dt.date(2029, 12, 31)


def test_as_of_suffixes_the_name():
    target = load_target("2032").with_as_of(Y2031)
    assert target.name == "2032@2031-12-31"
    assert target.as_of == Y2031


def test_shifting_twice_does_not_compound():
    # The bug this guards: `osm-survey diff --as-of 2031 --baseline-as-of
    # 2029` produced `2032@2031-12-31@2029-12-31`, and the stage then looked
    # for an extract by that name and failed.
    target = load_target("2032").with_as_of(Y2031)
    baseline = target.with_as_of(Y2029)
    assert baseline.name == "2032@2029-12-31"
    assert baseline.as_of == Y2029


def test_shifting_to_the_same_date_is_a_no_op():
    # Otherwise the identical graph cache gets built twice under two slugs,
    # and a diff of a target against itself reports no change — which reads
    # exactly like a target that did nothing.
    target = load_target("2032")
    assert target.with_as_of(target.as_of) is target


def test_slugs_differ_so_caches_cannot_collide():
    a = load_target("2032").with_as_of(Y2031)
    b = load_target("2032").with_as_of(Y2029)
    assert a.slug != b.slug
    assert a.graph_cache != b.graph_cache
    assert a.pbf != b.pbf


def test_command_hint_names_a_loadable_target():
    # `name` gains an @date suffix, but there is no targets/2032@2031-12-31.yml
    # — so any "run this" hint has to use the file stem.
    target = load_target("2032").with_as_of(Y2031)
    assert target.command.startswith("2032 -d ")
    assert "--as-of 2031-12-31" in target.command
