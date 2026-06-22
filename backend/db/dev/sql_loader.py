"""Loads .sql files from the sql/ folder next to this module, cached so
repeated calls (e.g. inside save_proposal()) don't re-read from disk."""

from functools import lru_cache
from pathlib import Path

SQL_DIR = Path(__file__).parent / "sql"


@lru_cache
def load_sql(filename: str) -> str:
    return (SQL_DIR / filename).read_text()