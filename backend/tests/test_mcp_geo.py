import json

import pytest
from fastapi.testclient import TestClient

from acquireos import config, enrich, geo

H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def rpc(cl, method, params=None, id=1, headers=None):
    r = cl.post("/mcp", headers={**H, **(headers or {})},
                json={"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}})
    return r


def init(cl, headers=None):
    return rpc(cl, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                  "clientInfo": {"name": "test", "version": "1"}}, headers=headers)


def call(cl, tool, args, headers=None):
    r = rpc(cl, "tools/call", {"name": tool, "arguments": args}, id=2, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "result" in body, body
    return body["result"]


def test_mcp_tools(loaded, monkeypatch):
    loaded.commit()  # the server uses its own connections
    monkeypatch.setattr(config, "API_TOKEN", "secret-token")
    from acquireos.api import app

    with TestClient(app) as cl:
        assert init(cl).status_code == 401
        auth = {"Authorization": "Bearer secret-token"}
        assert init(cl, auth).status_code == 200
        tools = {t["name"] for t in rpc(cl, "tools/list", headers=auth).json()["result"]["tools"]}
        assert {"search_companies", "get_company", "audit_queue", "save_enrichment", "query_database",
                "flag_data_issue", "dataset_overview"} <= tools
        res = call(cl, "search_companies", {"limit": 3}, auth)
        data = json.loads(res["content"][0]["text"])
        assert data["total"] >= 3 and len(data["companies"]) == 3
        q = json.loads(call(cl, "audit_queue", {"check": "missing_website", "limit": 5}, auth)["content"][0]["text"])
        assert q and all("No website recorded" in x["needs"] for x in q)
        saved = call(cl, "save_enrichment", {"company_number": "01000001", "website": "example-systems.test",
                                             "business_type": "msp", "field_service": "no",
                                             "source_url": "https://example-systems.test/about"}, auth)
        assert not saved.get("isError"), saved
        got = json.loads(call(cl, "get_company", {"company_number": "01000001"}, auth)["content"][0]["text"])
        assert got["enrichment"]["website"] == "https://example-systems.test"
        assert any(r["source_url"] == "https://example-systems.test/about" for r in got["research"])
        # rejected without a source
        bad = call(cl, "save_enrichment", {"company_number": "01000001", "summary": "x", "source_url": ""}, auth)
        assert bad.get("isError")
        sql = json.loads(call(cl, "query_database", {"sql": "select count(*) as n from company"}, auth)["content"][0]["text"])
        assert sql["rows"][0]["n"] == 7
        assert call(cl, "query_database", {"sql": "delete from company"}, auth).get("isError")
        # REST also accepts the token when a password is set
        monkeypatch.setattr(config, "APP_PASSWORD", "pw")
        assert cl.get("/api/meta").status_code == 401
        assert cl.get("/api/meta", headers=auth).status_code == 200


def test_field_service_enrichment_excludes(loaded):
    c = loaded
    enrich.save_enrichment(c, "01000002", source_url="https://x.test", field_service="yes", by="test")
    s = c.execute("select excluded, exclusion from score where company_number='01000002'").fetchone()
    assert s["excluded"] and "field-service" in s["exclusion"]


def test_readonly_query_blocks_writes(loaded):
    loaded.commit()
    for bad in ["update company set name='x'", "select 1; delete from company", "with x as (delete from company returning 1) select * from x"]:
        with pytest.raises(enrich.EnrichError):
            enrich.readonly_query(loaded, bad)
    assert enrich.readonly_query(loaded, "select name from company where name like '%LTD'")["rows"]


def test_geocode_and_map(loaded):
    c = loaded

    def fake_post(path, body):
        known = {"SA1 1AA": (51.62, -3.94), "CF10 1AA": (51.48, -3.18)}
        return {"result": [{"query": p, "result": ({"latitude": known[p][0], "longitude": known[p][1]} if p in known else None)}
                           for p in body["postcodes"]]}

    def fake_get(path):
        return {"result": {"latitude": 51.5, "longitude": -3.0}} if path.endswith("NP20") else None

    r = geo.geocode(c, post=fake_post, get=fake_get)
    assert r["exact"] == 2 and r["outcode"] >= 1 and r["not_found"] >= 1
    assert geo.missing_postcodes(c) == []
    c.commit()
    from acquireos.api import app

    with TestClient(app) as cl:
        m = cl.get("/api/companies?format=map&include_excluded=true").json()
        assert m["located"] >= 3 and all(p["lat"] for p in m["points"])
        d = cl.get("/api/companies/01000001").json()
        assert d["geo"]["lat"] == 51.62
        assert d["sics"][0]["description"] == "Information technology consultancy activities"
        assert cl.get("/api/sic").json()[0]["description"]
        assert cl.get("/api/geocode").json()["counts"]["located"] >= 3
