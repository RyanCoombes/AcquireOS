import os
from pathlib import Path

import pytest

TEST_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres@localhost:5433/acquireos_test?host=/var/tmp/pgtest")
os.environ["DATABASE_URL"] = TEST_URL
FIX = Path(__file__).parent / "fixtures"


@pytest.fixture()
def c():
    from acquireos import db

    with db.conn(TEST_URL) as conn:
        conn.execute("drop schema public cascade; create schema public;")
    db.migrate(TEST_URL)
    with db.conn(TEST_URL) as conn:
        yield conn


@pytest.fixture()
def loaded(c):
    from acquireos import scoring
    from acquireos.importers import companies, notes, psc

    companies.run(c, FIX / "ranked_sample.csv")
    psc.run(c, [FIX / "psc_sample.jsonl"])
    notes.run(c, FIX / "notes_sample.csv")
    scoring.rescore(c)
    return c
