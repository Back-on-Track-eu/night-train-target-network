"""Date parsing decides which projects are in a network, so it is strict."""

from __future__ import annotations

import datetime as dt

import pytest

from osm_pipe.dates import parse_date


def test_year_resolves_to_end_of_year():
    # The reason this is the last day and not the first: a target with
    # `as_of: 2032-12-31` must include a project opening "2032".
    assert parse_date("2032") == dt.date(2032, 12, 31)


def test_year_month_resolves_to_end_of_month():
    assert parse_date("2029-06") == dt.date(2029, 6, 30)
    assert parse_date("2032-02") == dt.date(2032, 2, 29)  # leap year


def test_full_date_is_itself():
    assert parse_date("2025-12-14") == dt.date(2025, 12, 14)


def test_yaml_native_types():
    # YAML resolves an unquoted 2032-06-14 to a date and 2032 to an int before
    # this ever sees a string.
    assert parse_date(dt.date(2032, 6, 14)) == dt.date(2032, 6, 14)
    assert parse_date(2032) == dt.date(2032, 12, 31)


@pytest.mark.parametrize("bad", ["2033+", "mid-2030s", "end 2026", "", "soon"])
def test_approximate_forms_are_refused(bad):
    # Guessing at a suffix would silently change which network gets built.
    with pytest.raises(ValueError):
        parse_date(bad, context="a-project")


def test_error_names_the_project():
    with pytest.raises(ValueError, match="brenner"):
        parse_date("2033+", context="brenner opening.official")
