"""Background Companies House sync, run by the scheduler while it has a key.

Order of work:
1. Pipeline companies never fetched (full fetch).
2. Pipeline companies not checked for a week (light check: two requests,
   a full fetch only if something changed).
3. Buy-box targets never fetched, best score first (full fetch).
4. Buy-box targets not checked for a month (light check).

Pauses while a bulk data load or scoring runs, or when paused from the
Data page. Shares the request schedule with the web app (chapi.ch_rate), so
the two together stay inside the API's limit. Changes it finds are stored
as company_change rows (source 'api').
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime

from . import chapi, db

PIPELINE_DAYS = int(os.environ.get("CH_SYNC_PIPELINE_DAYS", "7"))
TARGET_DAYS = int(os.environ.get("CH_SYNC_TARGET_DAYS", "30"))
PIPELINE_SQL = """select company_number from user_company where user_id = 1
                  and status not in ('new', 'passed', 'rejected')"""
TARGET_SQL = """select cb.company_number, cb.score from company_best cb
                where not exists (select 1 from user_company uc where uc.company_number = cb.company_number
                                  and uc.user_id = 1 and uc.status in ('passed', 'rejected'))"""


def log(msg: str):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} [ch-sync] {msg}", flush=True)


def get_setting(conn, key: str, default=None):
    r = conn.execute("select value from app_setting where key = %s", (key,)).fetchone()
    return r["value"] if r else default


def set_setting(conn, key: str, value):
    conn.execute(
        """insert into app_setting (key, value, updated_at) values (%s, %s, now())
           on conflict (key) do update set value = excluded.value, updated_at = now()""", (key, json.dumps(value)))


def busy(conn) -> bool:
    """A bulk load or scoring is running: leave the database to it."""
    return bool(conn.execute(
        """select 1 from job where status = 'running' and kind not in ('ch-details', 'website-check')
           and updated_at > now() - interval '5 minutes' limit 1""").fetchone())


def next_batch(conn, n: int = 40) -> list[tuple[str, str]]:
    """Up to n (company_number, 'full' | 'check'), most urgent first. Companies
    the stream says have changed (ch_dirty) come first; with the stream live,
    targets are re-checked on a timer far less often."""
    from . import chstream

    target_days = TARGET_DAYS * 4 if chstream.live(conn) else TARGET_DAYS
    out = [(r["company_number"], "full") for r in conn.execute(
        f"""select d.company_number from ch_dirty d join ({PIPELINE_SQL}) p using (company_number)
            order by d.first_at limit %s""", (n,))]
    out += [(r["company_number"], "full") for r in conn.execute(
        f"""select p.company_number from ({PIPELINE_SQL}) p
            where not exists (select 1 from ch_fetch f where f.company_number = p.company_number) limit %s""", (n,))]
    if len(out) < n:
        out += [(r["company_number"], "full") for r in conn.execute(
            "select company_number from ch_dirty order by first_at limit %s", (n - len(out),))]
    if len(out) < n:
        out += [(r["company_number"], "check") for r in conn.execute(
            f"""select f.company_number from ({PIPELINE_SQL}) p join ch_fetch f using (company_number)
                where f.checked_at < now() - make_interval(days => %s) order by f.checked_at limit %s""",
            (PIPELINE_DAYS, n - len(out)))]
    if len(out) < n:
        out += [(r["company_number"], "full") for r in conn.execute(
            f"""select t.company_number from ({TARGET_SQL}) t
                where not exists (select 1 from ch_fetch f where f.company_number = t.company_number)
                order by t.score desc nulls last limit %s""", (n - len(out),))]
    if len(out) < n:
        out += [(r["company_number"], "check") for r in conn.execute(
            f"""select f.company_number from ({TARGET_SQL}) t join ch_fetch f using (company_number)
                where f.checked_at < now() - make_interval(days => %s) order by f.checked_at limit %s""",
            (target_days, n - len(out)))]
    seen, uniq = set(), []
    for num, mode in out:
        if num not in seen:
            seen.add(num)
            uniq.append((num, mode))
    return uniq


def status(conn) -> dict:
    """Coverage and activity for the Data page."""
    from . import chstream

    pipe = conn.execute(
        f"""select count(*) as total, count(f.company_number) as fetched,
                   count(*) filter (where f.checked_at >= now() - make_interval(days => %s)) as current
            from ({PIPELINE_SQL}) p left join ch_fetch f using (company_number)""", (PIPELINE_DAYS,)).fetchone()
    tgt = conn.execute(
        f"""select count(*) as total, count(f.company_number) as fetched,
                   count(*) filter (where f.checked_at >= now() - make_interval(days => %s)) as current
            from ({TARGET_SQL}) t left join ch_fetch f using (company_number)""", (TARGET_DAYS,)).fetchone()
    day = conn.execute(
        """select count(*) filter (where fetched_at > now() - interval '24 hours') as fetched,
                  count(*) filter (where checked_at > now() - interval '24 hours') as checked
           from ch_fetch where checked_at > now() - interval '24 hours'""").fetchone()
    found = conn.execute(
        """select count(*) as n from company_change where source = 'api'
           and detected_at > now() - interval '7 days'""").fetchone()["n"]
    beat = conn.execute("select value, updated_at from app_setting where key = 'ch_sync_beat'").fetchone()
    alive = bool(beat and (datetime.now(beat["updated_at"].tzinfo) - beat["updated_at"]).total_seconds() < 20 * 60)
    remaining = (tgt["total"] - tgt["fetched"]) + (pipe["total"] - pipe["fetched"])
    # Rate over the time actually spent fetching in the last 6 hours (not
    # "per 24 hours", which reads far too low when the sync has just started).
    rate = conn.execute(
        """select count(*) as n, extract(epoch from now() - min(fetched_at)) as secs
           from ch_fetch where fetched_at > now() - interval '6 hours'""").fetchone()
    per_hour = (rate["n"] / max(float(rate["secs"] or 0), 900) * 3600) if rate["n"] and rate["n"] >= 10 else None
    return {
        "enabled": chapi.enabled(), "paused": bool(get_setting(conn, "ch_sync_paused", False)),
        "running": alive, "state": (beat["value"] or {}).get("state") if beat else None,
        "last_beat": beat["updated_at"] if beat else None,
        "pipeline": dict(pipe), "targets": dict(tgt), "last_24h": dict(day), "changes_7d": found,
        "pipeline_days": PIPELINE_DAYS, "target_days": TARGET_DAYS * 4 if chstream.live(conn) else TARGET_DAYS,
        "stream": chstream.status(conn),
        "per_hour": round(per_hour) if per_hour else None,
        "days_to_cover": round(remaining / (per_hour * 24), 1) if remaining and per_hour else None,
    }


def _beat(conn, state: str, **extra):
    set_setting(conn, "ch_sync_beat", {"state": state, **extra})
    conn.commit()


def run_forever():
    """The sync loop. Never raises: problems are logged and retried later."""
    log(f"started (API key {'set' if chapi.enabled() else 'NOT set'})")
    # The app applies database updates when it starts; wait for them rather than error.
    waited = False
    while True:
        try:
            with db.conn(dedicated=True) as c:
                if c.execute("select to_regclass('app_setting') as t").fetchone()["t"]:
                    break
        except Exception:
            pass
        if not waited:
            log("waiting for the app to update the database")
            waited = True
        time.sleep(20)
    while True:
        try:
            if not chapi.enabled():
                with db.conn(dedicated=True) as c:
                    _beat(c, "no API key")  # so the Data page can say why nothing is happening
                time.sleep(600)
                continue
            with db.conn(dedicated=True) as c:
                if get_setting(c, "ch_sync_paused", False):
                    _beat(c, "paused")
                    time.sleep(120)
                    continue
                if busy(c):
                    _beat(c, "waiting for a data load")
                    time.sleep(300)
                    continue
                batch = next_batch(c)
                if not batch:
                    _beat(c, "up to date")
                    time.sleep(900)
                    continue
                full = checks = changes = 0
                for num, mode in batch:
                    if get_setting(c, "ch_sync_paused", False) or busy(c):
                        break
                    try:
                        t0 = c.execute("select now() as t").fetchone()["t"]
                        r = chapi.fetch(c, num) if mode == "full" else chapi.check(c, num)
                        c.execute("delete from ch_dirty where company_number = %s and last_at <= %s", (num, t0))
                        c.commit()
                    except chapi.NoKey as e:
                        c.rollback()
                        log(str(e))
                        _beat(c, "API key rejected")
                        time.sleep(3600)
                        break
                    except Exception as e:  # one company's trouble must not stop the rest
                        c.rollback()
                        log(f"{num}: {e}")
                        c.execute(
                            """insert into ch_fetch (company_number, fetched_at, checked_at, error) values (%s, now(), now(), %s)
                               on conflict (company_number) do update set checked_at = now(), error = excluded.error""",
                            (num, str(e)[:200]))
                        c.commit()
                        time.sleep(30)
                        continue
                    full += 1 if (mode == "full" or r.get("full")) else 0
                    checks += 1 if mode == "check" else 0
                    changes += r.get("changes") or 0
                    _beat(c, "working", company=num)
                    time.sleep(0.5)  # leave room for requests from the web app
                log(f"batch: {full} fetched, {checks} checked, {changes} changes")
        except Exception as e:
            log(f"error: {e}")
            time.sleep(120)
