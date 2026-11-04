from contextlib import contextmanager
from importlib import resources

import psycopg
from psycopg.rows import dict_row

from . import config



def connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(url or config.DATABASE_URL, row_factory=dict_row)


@contextmanager
def conn(url: str | None = None):
    c = connect(url)
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def migrate(url: str | None = None) -> list[str]:
    """Apply any migrations that have not run yet. Returns names applied."""
    applied = []
    with conn(url) as c:
        c.execute(
            "create table if not exists schema_migration ("
            "name text primary key, applied_at timestamptz not null default now())"
        )
        done = {r["name"] for r in c.execute("select name from schema_migration")}
        files = sorted(
            p for p in resources.files("acquireos.migrations").iterdir() if p.name.endswith(".sql")
        )
        for f in files:
            if f.name in done:
                continue
            sql = f.read_text()
            # 001 creates schema_migration itself; drop our bootstrap copy first.
            if f.name.startswith("001"):
                c.execute("drop table if exists schema_migration")
            c.execute(sql)
            c.execute("insert into schema_migration (name) values (%s)", (f.name,))
            applied.append(f.name)
    return applied
