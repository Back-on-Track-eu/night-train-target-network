"""Container names have to survive `--as-of`.

Docker allows only [a-zA-Z0-9][a-zA-Z0-9_.-]. A target slug carries an
`@<date>` under --as-of, which is fine in a path and in our own output but
makes `docker run` fail with exit 125 — so `serve` worked for a plain target
and died for its own baseline, which is the pair every comparison needs.
"""

from __future__ import annotations

import datetime as dt
import re

from osm_pipe.config import load_target
from osm_pipe.ghimport import container_name

DOCKER_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


def test_plain_target_name_is_valid():
    assert DOCKER_NAME.match(container_name(load_target("2032")))


def test_as_of_target_name_is_valid():
    target = load_target("2032").with_as_of(dt.date(2026, 8, 29))
    name = container_name(target)
    assert "@" not in name
    assert DOCKER_NAME.match(name), name


def test_names_stay_distinct_across_dates():
    # They address different graph caches, so a collision would silently make
    # `verify` compare a network against itself.
    a = container_name(load_target("2032").with_as_of(dt.date(2026, 8, 29)))
    b = container_name(load_target("2032").with_as_of(dt.date(2040, 12, 31)))
    c = container_name(load_target("2032"))
    assert len({a, b, c}) == 3


def test_the_targets_own_date_is_not_a_separate_container():
    # `--as-of 2032-12-31` on the 2032 target is the target itself, so it must
    # not spawn a second container serving an identical graph on another port.
    target = load_target("2032")
    assert container_name(target.with_as_of(target.as_of)) == container_name(target)


def test_dataset_is_part_of_the_name():
    # A country cache answering /health for a europe query is the worst
    # failure available here: plausible wrong routes rather than an error.
    europe = container_name(load_target("2032", "europe"))
    fehmarn = container_name(load_target("2032", "fehmarn"))
    assert europe != fehmarn
