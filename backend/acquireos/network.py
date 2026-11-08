"""One network of companies and people, opened one node at a time.

Nodes: companies ("c:<number>"), owners from the register ("p:<person id>")
and directors from Companies House ("o:<officer key>"). A director who is also
an owner (same surname, first name and month and year of birth) is shown once,
as the owner, with their directorships too.
"""
from __future__ import annotations

import re

_TITLES = re.compile(r"^(MR|MRS|MS|MISS|DR|SIR|DAME|PROF|LORD|LADY|REV)\.?\s+")


def _parts(name: str) -> tuple[str, str]:
    """(SURNAME, FIRST) from 'SMITH, John Paul' or 'Mr John Paul Smith'."""
    n = " ".join((name or "").upper().split())
    if "," in n:
        sur, fore = n.split(",", 1)
        fore = _TITLES.sub("", fore.strip())
        return sur.strip(), (fore.split() or [""])[0]
    n = _TITLES.sub("", n)
    bits = n.split()
    return (bits[-1], bits[0]) if len(bits) > 1 else (n, "")


def _same(a_name, a_y, a_m, b_name, b_y, b_m) -> bool:
    if not a_y or a_y != b_y or (a_m or 0) != (b_m or 0):
        return False
    return _parts(a_name) == _parts(b_name)


def _geo(c, nums: list[str]) -> dict:
    if not nums:
        return {}
    return {r["company_number"]: r for r in c.execute(
        """select c.company_number, g.lat, g.lon from company c join postcode_geo g on g.postcode = c.postcode
           where c.company_number = any(%s)""", (nums,))}


def _company_nodes(c, nums: list[str], uid: int) -> dict:
    if not nums:
        return {}
    rows = c.execute(
        """select c.company_number, c.name, c.status, c.region, c.postcode, cb.score,
                  coalesce(uc.status, 'new') as my_status
           from company c left join company_best cb on cb.company_number = c.company_number
           left join user_company uc on uc.company_number = c.company_number and uc.user_id = %s
           where c.company_number = any(%s)""", (uid, nums)).fetchall()
    geo = _geo(c, nums)
    return {r["company_number"]: {"id": f"c:{r['company_number']}", "type": "company", "name": r["name"],
                                  "number": r["company_number"], "status": r["status"], "region": r["region"],
                                  "score": float(r["score"]) if r["score"] is not None else None, "my_status": r["my_status"],
                                  "in_list": True, "lat": (geo.get(r["company_number"]) or {}).get("lat"),
                                  "lon": (geo.get(r["company_number"]) or {}).get("lon")} for r in rows}


def _officer_for_person(c, p) -> list[str]:
    """Officer keys that are this owner (same name and month/year of birth)."""
    if p["kind"] != "individual" or not p["birth_year"]:
        return []
    sur, _ = _parts(p["name"])
    rows = c.execute("""select distinct officer_key, name, birth_year, birth_month from officer
                        where birth_year = %s and coalesce(birth_month, 0) = %s and upper(name) like %s""",
                     (p["birth_year"], p["birth_month"] or 0, sur + ",%")).fetchall()
    return [r["officer_key"] for r in rows if _same(p["name"], p["birth_year"], p["birth_month"],
                                                   r["name"], r["birth_year"], r["birth_month"])]


def _person_for_officer(c, o) -> dict | None:
    if not o or not o.get("birth_year"):
        return None
    sur, first = _parts(o["name"])
    for r in c.execute("""select id, name, kind, birth_year, birth_month from person
                          where kind = 'individual' and birth_year = %s and coalesce(birth_month, 0) = %s
                            and upper(name) like %s limit 50""",
                       (o["birth_year"], o.get("birth_month") or 0, "%" + sur + "%")).fetchall():
        if _same(r["name"], r["birth_year"], r["birth_month"], o["name"], o["birth_year"], o.get("birth_month")):
            return r
    return None


def neighbours(c, node_id: str, uid: int = 1, former: bool = False) -> dict:
    """The node itself and everything one step away: {node, nodes, edges}."""
    kind, _, key = node_id.partition(":")
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    companies: set[str] = set()

    def edge(a, b, kind, label=None, current=True):
        edges.append({"source": a, "target": b, "kind": kind, "label": label, "current": current})

    if kind == "c":
        num = key.upper()
        companies.add(num)
        # owners on the register
        for r in c.execute(
                """select p.id, p.name, p.kind, p.birth_year, p.birth_month, p.registration_number, cp.natures, cp.ceased_on
                   from company_person cp join person p on p.id = cp.person_id
                   where cp.company_number = %s and cp.role = 'psc' """ + ("" if former else "and cp.ceased_on is null"),
                (num,)).fetchall():
            share = _share(r["natures"])
            if r["kind"] != "individual" and r["registration_number"]:
                other = r["registration_number"].upper()
                companies.add(other)
                nodes.setdefault(f"c:{other}", {"id": f"c:{other}", "type": "company", "name": r["name"], "number": other, "in_list": False})
                edge(f"c:{other}", f"c:{num}", "owns", share, r["ceased_on"] is None)
            else:
                nodes.setdefault(f"p:{r['id']}", {"id": f"p:{r['id']}", "type": "person", "name": r["name"], "kind": r["kind"],
                                                   "birth_year": r["birth_year"], "owner": True})
                edge(f"p:{r['id']}", f"c:{num}", "owns", share, r["ceased_on"] is None)
        # directors (fetched from Companies House)
        for o in c.execute("""select officer_key, name, role, birth_year, birth_month, resigned_on, occupation from officer
                              where company_number = %s """ + ("" if former else "and resigned_on is null"),
                           (num,)).fetchall():
            if "secretary" in (o["role"] or ""):
                continue
            p = _person_for_officer(c, o)
            nid = f"p:{p['id']}" if p else f"o:{o['officer_key']}"
            nodes.setdefault(nid, {"id": nid, "type": "person", "name": p["name"] if p else o["name"], "kind": "individual",
                                   "birth_year": o["birth_year"], "officer_key": o["officer_key"]})
            nodes[nid]["director"] = True
            edge(nid, f"c:{num}", "director", o["occupation"], o["resigned_on"] is None)
        # linked companies (group, same owner, same address)
        from .api import _links_for
        for l in _links_for(c, num):
            other = l["other"]
            companies.add(other)
            nodes.setdefault(f"c:{other}", {"id": f"c:{other}", "type": "company", "name": l["other_name"] or other,
                                            "number": other, "in_list": l["in_list"]})
            a, b = (f"c:{num}", f"c:{other}") if l["direction"] != "subsidiary" else (f"c:{other}", f"c:{num}")
            k = {"owned_by": "group", "same_owner": "same_owner"}.get(l["kind"], "same_address")
            edge(a, b, k, l["evidence"])
        node_id = f"c:{num}"

    elif kind in ("p", "o"):
        p = o = None
        okeys: list[str] = []
        if kind == "p":
            p = c.execute("select id, name, kind, birth_year, birth_month from person where id = %s", (int(key),)).fetchone()
            if p:
                okeys = _officer_for_person(c, p)
        else:
            o = c.execute("select officer_key, name, birth_year, birth_month from officer where officer_key = %s limit 1", (key,)).fetchone()
            okeys = [key]
            p = _person_for_officer(c, o) if o else None
            if p:
                node_id = f"p:{p['id']}"
        if p:
            node_id = f"p:{p['id']}"
            nodes[node_id] = {"id": node_id, "type": "person", "name": p["name"], "kind": p["kind"], "birth_year": p["birth_year"],
                              "owner": True, "officer_key": okeys[0] if okeys else None, "director": bool(okeys)}
            for r in c.execute("""select cp.company_number, cp.natures, cp.ceased_on from company_person cp
                                  where cp.person_id = %s and cp.role = 'psc' """ + ("" if former else "and cp.ceased_on is null"),
                               (p["id"],)).fetchall():
                companies.add(r["company_number"])
                edge(node_id, f"c:{r['company_number']}", "owns", _share(r["natures"]), r["ceased_on"] is None)
        elif o:
            node_id = f"o:{key}"
            nodes[node_id] = {"id": node_id, "type": "person", "name": o["name"], "kind": "individual",
                              "birth_year": o["birth_year"], "officer_key": key, "director": True}
        else:
            return {"node": None, "nodes": [], "edges": []}
        for a in c.execute("""select company_number, company_name, role, resigned_on from officer_appointment
                              where officer_key = any(%s) """ + ("" if former else "and resigned_on is null"),
                           (okeys,)).fetchall():
            if "secretary" in (a["role"] or ""):
                continue
            num = a["company_number"].upper()
            companies.add(num)
            nodes.setdefault(f"c:{num}", {"id": f"c:{num}", "type": "company", "name": a["company_name"] or num,
                                          "number": num, "in_list": False})
            edge(node_id, f"c:{num}", "director", (a["role"] or "").replace("-", " "), a["resigned_on"] is None)
    else:
        return {"node": None, "nodes": [], "edges": []}

    known = _company_nodes(c, sorted(companies), uid)
    for num, n in known.items():
        nodes[f"c:{num}"] = {**nodes.get(f"c:{num}", {}), **n}
    # one edge per pair and kind
    seen, uniq = set(), []
    for e in edges:
        k = (e["source"], e["target"], e["kind"])
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return {"node": nodes.get(node_id), "nodes": list(nodes.values()), "edges": uniq}


def _share(natures) -> str | None:
    for n in natures or []:
        m = re.search(r"(\d+)-to-(\d+)-percent", n)
        if m:
            return f"{m.group(1)}–{m.group(2)}%"
        if "75-to-100" in n or "more-than-75" in n:
            return "75–100%"
    return None
