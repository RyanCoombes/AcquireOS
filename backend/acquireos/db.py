from contextlib import contextmanager
from importlib import resources

import psycopg
from psycopg.rows import dict_row

from . import config



def connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(url or config.DATABASE_URL, row_factory=dict_row)


_POOL = None


def pool():
    """A shared pool for web requests: opening a fresh connection for every
    request costs 15-30 ms on a Pi over Docker. None if psycopg_pool is not
    installed (then every call opens its own connection, as before)."""
    global _POOL
    if _POOL is None:
        try:
            from psycopg_pool import ConnectionPool
        except ImportError:
            return None
        _POOL = ConnectionPool(config.DATABASE_URL, min_size=2, max_size=8, open=True, timeout=30,
                               kwargs={"row_factory": dict_row}, check=ConnectionPool.check_connection)
    return _POOL


def close_pool():
    global _POOL
    if _POOL is not None:
        _POOL.close()
        _POOL = None


@contextmanager
def conn(url: str | None = None, dedicated: bool = False):
    """A connection, committed on success and rolled back on error.

    Web requests share the pool. Long jobs (data loads, scoring) must pass
    dedicated=True: they change session settings and leave temp tables
    behind, which must not come back to a request through the pool."""
    p = None if (url or dedicated) else pool()
    if p is not None:
        with p.connection() as c:
            yield c
        return
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
