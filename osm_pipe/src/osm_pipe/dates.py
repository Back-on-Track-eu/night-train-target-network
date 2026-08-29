"""Opening dates, and what it means for a project to be open at a date.

The catalogue holds every project we know about, at any horizon. Which of them
are in a given network is decided here, by comparing an opening date against
`as_of`. That comparison is the whole selection mechanism, so the parsing has
to be strict: a date that silently fails to parse would silently drop a
corridor from the network.

Accepted forms, as a string or as whatever YAML already turned it into:

    2032            -> 2032-12-31    end of the stated period
    2032-06         -> 2032-06-30
    2032-06-14      -> 2032-06-14

**Periods resolve to their last day.** A project opening "2032" is open at
`as_of: 2032-12-31`, which is what anyone writing that pair means. Resolving to
the first day instead would make a 2032 target quietly include everything
opening during 2032, which is a stronger claim than the file makes.

Deliberately not accepted: "2033+", "mid-2030s", "end 2026". They read as dates
and are not. A catalogue entry is a modelling input — picking which year to
model is a decision that belongs to whoever writes the entry, with a source
next to it, not to a parser guessing at a suffix.
"""

from __future__ import annotations

import calendar
import datetime as dt
import re

_YEAR = re.compile(r"^(\d{4})$")
_YEAR_MONTH = re.compile(r"^(\d{4})-(\d{1,2})$")
_YEAR_MONTH_DAY = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")

_ACCEPTED = "YYYY, YYYY-MM or YYYY-MM-DD"


def parse_date(raw: object, *, context: str = "") -> dt.date:
    """Resolve an opening date to the last day of the period it names."""
    where = f" ({context})" if context else ""

    # YAML resolves an unquoted 2032-06-14 to a date and 2032 to an int before
    # we ever see it, so both arrive already typed.
    if isinstance(raw, dt.datetime):
        return raw.date()
    if isinstance(raw, dt.date):
        return raw
    if isinstance(raw, int):
        return _end_of_year(raw)

    text = str(raw).strip()
    if not text:
        raise ValueError(f"missing opening date{where} — expected {_ACCEPTED}")

    if m := _YEAR.match(text):
        return _end_of_year(int(m.group(1)))
    if m := _YEAR_MONTH.match(text):
        return _end_of_month(int(m.group(1)), int(m.group(2)))
    if m := _YEAR_MONTH_DAY.match(text):
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    raise ValueError(
        f"cannot read {text!r} as a date{where}. Expected {_ACCEPTED}.\n"
        "Approximate forms like '2033+' or 'mid-2030s' are refused on purpose: "
        "which year to model is a decision for the catalogue entry, with a "
        "source beside it, not for this parser to guess. Pick the year you "
        "want modelled and record the uncertainty in `opening.note`."
    )


def _end_of_year(year: int) -> dt.date:
    return dt.date(year, 12, 31)


def _end_of_month(year: int, month: int) -> dt.date:
    if not 1 <= month <= 12:
        raise ValueError(f"month out of range: {month}")
    return dt.date(year, month, calendar.monthrange(year, month)[1])


def parse_as_of(raw: object) -> dt.date:
    """The horizon a target is built for. Same grammar as an opening date."""
    return parse_date(raw, context="as_of")


def today() -> dt.date:
    return dt.date.today()
