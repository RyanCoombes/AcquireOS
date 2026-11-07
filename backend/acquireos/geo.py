"""Postcode to latitude and longitude, for the map.

Uses postcodes.io (free, open data from the ONS Postcode Directory, no key):
    POST https://api.postcodes.io/postcodes      up to 100 postcodes a call
    GET  https://api.postcodes.io/outcodes/{out} district centroid
Results are cached in postcode_geo, so each postcode is looked up once.
Set POSTCODES_IO_URL to use a self-hosted copy of postcodes.io.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

API = os.environ.get("POSTCODES_IO_URL", "https://api.postcodes.io").rstrip("/")
UA = "AcquireOS/0.3 (self-hosted research tool)"


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _get(path: str) -> dict | None:
    req = urllib.request.Request(API + path, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def missing_postcodes(conn, limit: int | None = None) -> list[str]:
    # Only companies that matter: in the buy box, in the pipeline, or linked
    # to one. The whole register has around 1.7 million postcodes.
    scored = conn.execute("select 1 from score limit 1").fetchone() is not None
    scope = """and (exists (select 1 from company_best s where s.company_number = c.company_number)
                    or exists (select 1 from user_company u where u.company_number = c.company_number and u.status <> 'new')
                    or exists (select 1 from company_link l where l.b = c.company_number))""" if scored else ""
    rows = conn.execute(
        f"""select distinct pc from (
               select postcode as pc from company c where postcode is not null {scope}
               union select postcode from person where postcode is not null and kind <> 'individual'
               union select l->>'postcode' from enrichment e, jsonb_array_elements(e.locations) l
                     where l->>'postcode' is not null) x
           left join postcode_geo g on g.postcode = x.pc
           where g.postcode is null or (g.precision = 'none' and g.looked_up_at < now() - interval '90 days')
              -- border areas looked up before the country was kept: once more for it
              or (g.country is null and g.precision = 'postcode'
                  and substring(g.postcode from '^([A-Z]{1,2})[0-9]') in ('CH', 'SY', 'HR', 'GL'))
           order by 1""" + (f" limit {int(limit)}" if limit else "")
    ).fetchall()
    return [r["pc"] for r in rows]


def geocode(conn, limit: int | None = None, post=None, get=None) -> dict:
    """Look up postcodes not yet in the cache. post/get can be replaced in tests."""
    post, get = post or _post, get or _get
    todo = missing_postcodes(conn, limit)
    exact = outcode = none = 0
    outcode_cache: dict[str, tuple | None] = {}
    for i in range(0, len(todo), 100):
        batch = todo[i:i + 100]
        try:
            res = post("/postcodes", {"postcodes": batch}).get("result") or []
        except Exception as e:
            return {"error": str(e), "exact": exact, "outcode": outcode, "not_found": none, "remaining": len(todo) - i}
        for item in res:
            pc, r = item.get("query"), item.get("result")
            if r and r.get("latitude") is not None:
                _store(conn, pc, r["latitude"], r["longitude"], "postcode", r.get("country"))
                exact += 1
                continue
            out = pc.split(" ")[0] if pc else None
            if out and out not in outcode_cache:
                try:
                    o = get(f"/outcodes/{out}")
                    rr = (o or {}).get("result")
                    outcode_cache[out] = (rr["latitude"], rr["longitude"]) if rr and rr.get("latitude") is not None else None
                except Exception:
                    outcode_cache[out] = None
            if out and outcode_cache.get(out):
                _store(conn, pc, *outcode_cache[out], "outcode")
                outcode += 1
            else:
                _store(conn, pc, None, None, "none")
                none += 1
        conn.commit()
        time.sleep(0.2)  # be polite to a free service
    return {"exact": exact, "outcode": outcode, "not_found": none, "remaining": 0, "regions_fixed": apply_countries(conn)}


def _store(conn, pc, lat, lon, precision, country=None):
    conn.execute(
        """insert into postcode_geo (postcode, lat, lon, precision, country) values (%s, %s, %s, %s, %s)
           on conflict (postcode) do update set lat = excluded.lat, lon = excluded.lon,
             precision = excluded.precision, country = coalesce(excluded.country, postcode_geo.country),
             looked_up_at = now()""",
        (pc, lat, lon, precision, country),
    )


def apply_countries(conn) -> int:
    """Postcodes that straddle the Wales-England border (CH, SY, HR, GL areas):
    set each company's region from the exact country the lookup returned."""
    return conn.execute(
        """update company c set region = g.country
           from postcode_geo g
           where g.postcode = c.postcode and g.country in ('Wales', 'England')
             and substring(g.postcode from '^([A-Z]{1,2})[0-9]') in ('CH', 'SY', 'HR', 'GL', 'LD', 'NP', 'LL')
             and c.region is distinct from g.country""").rowcount
