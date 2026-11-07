"""Watching companies, owners and directors.

A watched company's changes count as alerts, like your pipeline's. A watched
owner (a person on the owners register) or director is checked against the
companies they were involved in last time: a new one, or one they left, is
recorded as a change (kind 'watch') on that company, so it shows on the
Changes page, in the alert badge and in Claude's daily briefing.
"""
from __future__ import annotations

import json

KINDS = ("company", "owner", "director")


def current(conn, kind: str, ref: str) -> dict[str, str]:
    """{company_number: role} for an owner or director now, limited to companies
    on the register (others appear once the register has them)."""
    if kind == "owner":
        rows = conn.execute(
            """select cp.company_number, 'owner' as role from company_person cp
               join company c on c.company_number = cp.company_number
               where cp.person_id = %s and cp.ceased_on is null""", (int(ref),)).fetchall()
    else:
        rows = conn.execute(
            """select a.company_number, coalesce(a.role, 'director') as role from officer_appointment a
               join company c on c.company_number = a.company_number
               where a.officer_key = %s and a.resigned_on is null""", (ref,)).fetchall()
    return {r["company_number"]: r["role"] for r in rows}


def check(conn) -> int:
    """Compare each watched owner and director with last time; record what is
    new or ended. The first check only takes the snapshot. Returns changes."""
    n = 0
    for w in conn.execute("select * from watch where kind in ('owner', 'director')").fetchall():
        now = current(conn, w["kind"], w["ref"])
        before = set(w["snapshot"] or [])
        if w["checked_at"] is not None:
            who = w["label"] or w["ref"]
            for num in sorted(set(now) - before):
                verb = "Became an owner" if w["kind"] == "owner" else f"Appointed ({(now[num] or 'director').replace('-', ' ')})"
                conn.execute(
                    """insert into company_change (company_number, kind, field, new_value, source)
                       values (%s, 'watch', %s, %s, 'watch')""", (num, f"Watched {w['kind']}: {who}", verb))
                n += 1
            for num in sorted(before - set(now)):
                if conn.execute("select 1 from company where company_number = %s", (num,)).fetchone():
                    conn.execute(
                        """insert into company_change (company_number, kind, field, new_value, source)
                           values (%s, 'watch', %s, %s, 'watch')""",
                        (num, f"Watched {w['kind']}: {w['label'] or w['ref']}",
                         "No longer an owner" if w["kind"] == "owner" else "Resigned"))
                    n += 1
        conn.execute("update watch set snapshot = %s, checked_at = now() where id = %s",
                     (json.dumps(sorted(now)), w["id"]))
    return n


def add(conn, kind: str, ref: str, label: str | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    ref = ref.strip().upper() if kind == "company" else ref.strip()
    if kind == "company":
        c = conn.execute("select name from company where company_number = %s", (ref,)).fetchone()
        if not c:
            raise ValueError(f"Company {ref} is not in AcquireOS")
        label = label or c["name"]
    elif kind == "owner":
        p = conn.execute("select name from person where id = %s", (int(ref),)).fetchone()
        if not p:
            raise ValueError("Owner not found")
        label = label or p["name"]
    row = conn.execute(
        """insert into watch (kind, ref, label) values (%s, %s, %s)
           on conflict (user_id, kind, ref) do update set label = coalesce(excluded.label, watch.label)
           returning *""", (kind, ref, label)).fetchone()
    if kind != "company":
        check_one(conn, row["id"])
    return row


def check_one(conn, watch_id: int):
    """Take (or refresh) one watch's snapshot straight away."""
    w = conn.execute("select * from watch where id = %s", (watch_id,)).fetchone()
    if w and w["kind"] != "company" and w["checked_at"] is None:
        conn.execute("update watch set snapshot = %s, checked_at = now() where id = %s",
                     (json.dumps(sorted(current(conn, w["kind"], w["ref"]))), w["id"]))


def listing(conn) -> list[dict]:
    """Everything watched, with what you need at a glance."""
    out = []
    for w in conn.execute("select * from watch where user_id = 1 order by kind, label").fetchall():
        item = {"id": w["id"], "kind": w["kind"], "ref": w["ref"], "label": w["label"], "since": w["created_at"]}
        if w["kind"] == "company":
            c = conn.execute(
                """select c.name, c.status, uc.status as my_status,
                          (select max(detected_at) from company_change ch where ch.company_number = c.company_number) as last_change,
                          (select count(*) from company_change ch where ch.company_number = c.company_number
                             and ch.detected_at > %s) as changes_since
                   from company c left join user_company uc on uc.company_number = c.company_number and uc.user_id = 1
                   where c.company_number = %s""", (w["created_at"], w["ref"])).fetchone() or {}
            item.update(c)
        else:
            now = current(conn, w["kind"], w["ref"])
            item["companies"] = [dict(r) for r in conn.execute(
                "select company_number, name, status from company where company_number = any(%s) order by name",
                (list(now),)).fetchall()]
            item["changes_since"] = conn.execute(
                """select count(*) as n from company_change where kind = 'watch' and field = %s""",
                (f"Watched {w['kind']}: {w['label'] or w['ref']}",)).fetchone()["n"]
            item["checked_at"] = w["checked_at"]
        out.append(item)
    return out
