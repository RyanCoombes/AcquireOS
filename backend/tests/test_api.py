import io

from fastapi.testclient import TestClient

from acquireos import db

from .conftest import FIX


def test_api_flow(c):
    from acquireos.api import app

    with TestClient(app) as cl:
        assert cl.get("/api/health").json()["ok"]
        for kind, fname in [("companies", "ranked_sample.csv"), ("notes", "notes_sample.csv")]:
            pv = cl.post("/api/import/preview", data={"kind": kind},
                         files={"file": (fname, (FIX / fname).read_bytes(), "text/csv")})
            assert pv.status_code == 200, pv.text
            p = pv.json()
            r = cl.post("/api/import/commit", json={"kind": kind, "token": p["token"], "suffix": p["suffix"],
                                                    "filename": fname, "mapping": p["mapping"]})
            assert r.status_code == 200, r.text
        lst = cl.get("/api/companies").json()
        assert lst["total"] >= 3
        sc = [float(r["score"]) for r in lst["rows"] if r["score"] is not None]
        assert sc == sorted(sc, reverse=True)  # scored first, best first; unscored after
        d = cl.get("/api/companies/01000001").json()
        assert d["score"]["reasons"] and len(d["financials"]) == 2
        assert cl.put("/api/companies/01000001/state", json={"status": "contacted"}).json()["status"] == "contacted"
        assert cl.post("/api/companies/01000001/notes", json={"body": "Called owner"}).status_code == 200
        assert cl.get("/api/companies/01000001").json()["notes"][0]["body"] == "Called owner"
        rep = cl.get("/api/reports").json()
        assert rep["staff"] and rep["funnel"]
        g = cl.get("/api/links/01000001").json()
        assert len(g["nodes"]) >= 2
        bb = cl.get("/api/buybox").json()
        bb["criteria"]["regions"] = ["Wales"]
        assert cl.put("/api/buybox", json={"criteria": bb["criteria"]}).json()["rescored"] == 6  # the 70100 holding company is outside the universe and skipped
        assert cl.get("/api/export.csv").status_code == 200
        # export follows the filters you are looking at
        all_rows = cl.get("/api/export.csv").text.lstrip("\ufeff").strip().splitlines()
        wales = cl.get("/api/export.csv?region=Wales&sort=name&dir=asc").text.lstrip("\ufeff").strip().splitlines()
        assert all_rows[0].startswith("Company number,Name") and 1 < len(wales) < len(all_rows)
        assert all(",Wales," in line for line in wales[1:])
        assert cl.get("/api/pipeline").json()["rows"]
        d = cl.get("/api/dashboard")
        assert d.status_code == 200, d.text
        assert d.json()["head"]["companies"] == 7 and len(d.json()["score_hist"]) == 10
        assert "staff_trend" in cl.get("/api/companies").json()["rows"][0]
        assert cl.get("/api/refresh").json()["running"] is False


def test_deal_stages(c):
    from acquireos.api import app

    with TestClient(app) as cl:
        f = FIX / "ranked_sample.csv"
        p = cl.post("/api/import/preview", data={"kind": "companies"}, files={"file": (f.name, f.read_bytes(), "text/csv")}).json()
        cl.post("/api/import/commit", json={"kind": "companies", "token": p["token"], "suffix": p["suffix"],
                                            "filename": f.name, "mapping": p["mapping"]})
        meta = cl.get("/api/meta").json()
        assert [s["value"] for s in meta["stages"]][:5] == ["new", "watching", "researching", "approach", "contacted"]
        assert "heads" in [s["value"] for s in meta["stages"]]
        for st in ("researching", "contacted", "heads"):
            assert cl.put("/api/companies/01000001/state", json={"status": st, "stage_note": f"to {st}"}).status_code == 200
        d = cl.get("/api/companies/01000001").json()["deal"]
        assert [h["to_status"] for h in d["history"]] == ["researching", "contacted", "heads"]
        assert d["history"][2]["from_status"] == "contacted" and d["history"][2]["note"] == "to heads"
        assert d["stage_entered_at"]
        assert len(d["tasks"]["heads"]) == 4 and not any(t["done"] for t in d["tasks"]["heads"])
        first = d["tasks"]["heads"][0]
        r = cl.post("/api/companies/01000001/tasks", json={"stage": "heads", "label": first["label"], "done": True}).json()
        assert r["tasks"]["heads"][0]["done"] and r["tasks"]["heads"][0]["done_at"]
        r = cl.post("/api/companies/01000001/tasks", json={"stage": "heads", "label": "Call the DBW manager", "done": False}).json()
        assert r["tasks"]["heads"][-1]["custom"]
        pl = cl.get("/api/pipeline").json()
        row = next(x for x in pl["rows"] if x["company_number"] == "01000001")
        assert row["status"] == "heads" and row["tasks_done"] == 1 and row["tasks_total"] == 4 and row["stage_entered_at"]
        # same status again is not logged twice
        cl.put("/api/companies/01000001/state", json={"status": "heads"})
        assert len(cl.get("/api/companies/01000001").json()["deal"]["history"]) == 3


def test_buyboxes_manual_and_review(c):
    from acquireos.api import app

    with TestClient(app) as cl:
        f = FIX / "ranked_sample.csv"
        p = cl.post("/api/import/preview", data={"kind": "companies"}, files={"file": (f.name, f.read_bytes(), "text/csv")}).json()
        cl.post("/api/import/commit", json={"kind": "companies", "token": p["token"], "suffix": p["suffix"],
                                            "filename": f.name, "mapping": p["mapping"]})
        boxes = cl.get("/api/buyboxes").json()
        assert len(boxes) == 1 and boxes[0]["is_active"]
        first = boxes[0]["id"]
        tpls = {t["key"] for t in cl.get("/api/buybox-templates").json()}
        assert {"msp", "saas", "fmcg"} <= tpls
        new = cl.post("/api/buyboxes", json={"name": "SaaS", "source": "template", "template": "saas"}).json()
        assert new["is_active"] and not new["background"]
        boxes = {b["name"]: b for b in cl.get("/api/buyboxes").json()}
        assert boxes["SaaS"]["is_active"] and not boxes["My buy box"]["is_active"] and boxes["SaaS"]["scored_at"]
        copy = cl.post("/api/buyboxes", json={"name": "Copy", "source": "copy", "copy_id": first}).json()
        assert cl.get("/api/meta").json()["buy_box"]["name"] == "Copy"
        # saved searches are global; one that filters by a buy box remembers it
        s = cl.post("/api/searches", json={"name": "Wales", "params": {"region": "Wales"}}).json()
        assert s["buy_box_id"] is None
        s = cl.post("/api/searches", json={"name": "Wales", "params": {"region": "Wales", "bb": str(copy["id"])}}).json()
        assert s["buy_box_id"] == copy["id"]
        assert [x["name"] for x in cl.get("/api/searches").json()].count("Wales") == 1
        # renaming a box keeps the best-score labels in step
        cl.patch(f"/api/buyboxes/{copy['id']}", json={"name": "Copy box"})
        assert all("Copy" not in (b or []) for b in [r.get("boxes") for r in cl.get("/api/companies").json()["rows"]])
        # your own scores: affect the score, shared across boxes
        before = cl.get("/api/companies/01000001").json()["score"]["score"]
        r = cl.put("/api/companies/01000001/manual", json={"key": "owner_openness", "value": 5}).json()
        assert r["values"]["owner_openness"]["value"] == 5 and float(r["score"]["score"]) >= float(before)
        r = cl.put("/api/companies/01000001/manual", json={"key": "recurring_quality", "value": 0}).json()
        d = cl.get("/api/companies/01000001").json()
        assert {c["key"] for c in d["manual"]["criteria"]} >= {"owner_openness", "recurring_quality"}
        assert d["manual"]["values"]["recurring_quality"]["value"] == 0
        man = [x for x in d["score"]["reasons"] if x.get("manual")]
        assert any(x["status"] == "miss" for x in man) and any(x["status"] == "good" for x in man)
        cl.post(f"/api/buyboxes/{first}/activate")
        d1 = cl.get("/api/companies/01000001").json()
        assert d1["manual"]["values"]["owner_openness"]["value"] == 5  # same score in another buy box
        # review queue and Home overview
        q = cl.get("/api/review").json()
        assert q["rows"] and all(r["score"] is not None for r in q["rows"])
        allv = cl.get("/api/dashboard?bb=all").json()
        assert allv["buy_box"] == "All buy boxes" and len(allv["boxes"]) == 3
        assert allv["head"]["in_scope"] >= cl.get("/api/dashboard").json()["head"]["in_scope"]
        # cannot delete the last box; can delete others
        assert cl.delete(f"/api/buyboxes/{copy['id']}").status_code == 200
        assert cl.delete(f"/api/buyboxes/{new['id']}").status_code == 200
        assert cl.delete(f"/api/buyboxes/{first}").status_code == 400


def test_buy_boxes_are_filters_over_all_companies(c):
    from acquireos.api import app

    with TestClient(app) as cl:
        f = FIX / "ranked_sample.csv"
        p = cl.post("/api/import/preview", data={"kind": "companies"}, files={"file": (f.name, f.read_bytes(), "text/csv")}).json()
        cl.post("/api/import/commit", json={"kind": "companies", "token": p["token"], "suffix": p["suffix"],
                                            "filename": f.name, "mapping": p["mapping"]})
        saas = cl.post("/api/buyboxes", json={"name": "SaaS", "source": "template", "template": "saas"}).json()
        # every company is listed, scored or not, with the best score and its box
        allc = cl.get("/api/companies?limit=50").json()
        assert allc["total"] == 7
        scored = [r for r in allc["rows"] if r["score"] is not None]
        assert scored and all(r["box_name"] in ("My buy box", "SaaS") for r in scored)
        assert any(r["score"] is None for r in allc["rows"])  # e.g. the holding company outside every universe
        # filter to one buy box, or to companies in any box
        one = cl.get(f"/api/companies?bb={saas['id']}&in_box=true").json()
        anyb = cl.get("/api/companies?in_box=true").json()
        assert one["total"] <= anyb["total"] <= 7
        # a company page has its score in every buy box
        d = cl.get("/api/companies/01000001").json()
        assert {s["buy_box"] for s in d["scores"]} == {"My buy box", "SaaS"}
        d2 = cl.get(f"/api/companies/01000001?bb={saas['id']}").json()
        assert d2["buy_box"]["name"] == "SaaS"
        # Home overview by default
        assert cl.get("/api/dashboard").json()["scope"] == "all"


def test_directory_sort_status_groups_and_coverage(c):
    from acquireos.api import app

    with TestClient(app) as cl:
        f = FIX / "ranked_sample.csv"
        p = cl.post("/api/import/preview", data={"kind": "companies"}, files={"file": (f.name, f.read_bytes(), "text/csv")}).json()
        cl.post("/api/import/commit", json={"kind": "companies", "token": p["token"], "suffix": p["suffix"],
                                            "filename": f.name, "mapping": p["mapping"]})
        c.execute("update company set status = 'liquidation' where company_number = '01000004'")
        c.execute("update company set status = 'removed from register' where company_number = '01000005'")
        c.execute("update company set status = 'active - proposal to strike off' where company_number = '01000006'")
        c.commit()
        az = cl.get("/api/companies?sort=name&dir=asc&limit=50").json()
        names = [r["name"] for r in az["rows"]]
        assert names == sorted(names) and az["total"] == 7 and az["capped"] is False
        groups = {g["value"] for g in cl.get("/api/meta").json()["status_groups"]}
        assert {"active", "strike_off", "insolvency", "dissolved"} <= groups

        def nums(g):
            return {r["company_number"] for r in cl.get(f"/api/companies?company_status={g}&limit=50").json()["rows"]}
        assert nums("insolvency") == {"01000004"}
        assert nums("dissolved") == {"01000005"}
        assert nums("strike_off") == {"01000006"}
        assert not nums("active") & {"01000004", "01000005", "01000006"}
        assert nums("active") | nums("insolvency") | nums("dissolved") | nums("strike_off") | nums("other") == {r["company_number"] for r in az["rows"]}
        cov = cl.get("/api/coverage").json()
        assert cov["active"] >= 1 and "with_accounts" in cov and "accounts_files" in cov


def test_search_by_name_number_and_postcode(c):
    from acquireos.api import app

    with TestClient(app) as cl:
        f = FIX / "ranked_sample.csv"
        p = cl.post("/api/import/preview", data={"kind": "companies"}, files={"file": (f.name, f.read_bytes(), "text/csv")}).json()
        cl.post("/api/import/commit", json={"kind": "companies", "token": p["token"], "suffix": p["suffix"],
                                            "filename": f.name, "mapping": p["mapping"]})

        def names(q, **kw):
            r = cl.get("/api/companies", params={"q": q, "sort": "relevance", **kw}).json()
            return [x["company_number"] for x in r["rows"]]
        assert names("example systems")[0] == "01000001"      # any case, words in order
        assert names("systems example") == names("example systems")  # each word, any order
        assert names("1000001") == ["01000001"]              # number without the leading zero
        assert names("SC123456") == ["SC123456"]
        assert "01000001" in names("SA1")                     # outward postcode
        assert "01000001" in names("sa1 1aa")                 # full postcode, any case
        assert names("zzzz") == []
        assert names("100%") == [] and names("_") == []       # LIKE wildcards are taken literally
        # filters still apply on top of a search
        assert names("example", company_status="dissolved") == []


def test_bulk_state(c):
    from acquireos.api import app

    with TestClient(app) as cl:
        f = FIX / "ranked_sample.csv"
        p = cl.post("/api/import/preview", data={"kind": "companies"}, files={"file": (f.name, f.read_bytes(), "text/csv")}).json()
        cl.post("/api/import/commit", json={"kind": "companies", "token": p["token"], "suffix": p["suffix"],
                                            "filename": f.name, "mapping": p["mapping"]})
        r = cl.put("/api/companies/state", json={"numbers": ["01000004", "01000005"], "status": "passed", "stage_note": "Bulk"})
        assert r.status_code == 200 and r.json()["updated"] == 2
        for n_ in ("01000004", "01000005"):
            assert cl.get(f"/api/companies/{n_}").json()["state"]["status"] == "passed"
        assert cl.put("/api/companies/state", json={"numbers": [], "status": "passed"}).status_code == 400


def test_owner_search_and_page(loaded):
    from acquireos.api import app

    loaded.commit()
    with TestClient(app) as cl:
        r = cl.get("/api/owners", params={"q": "example alex"}).json()["rows"]
        assert r and r[0]["name"] == "Mr Alex Example" and r[0]["companies"] >= 1
        pid = r[0]["id"]
        o = cl.get(f"/api/owners/{pid}").json()
        assert o["owner"]["name"] == "Mr Alex Example"
        nums = {x["company_number"] for x in o["companies"]}
        assert "01000001" in nums
        assert cl.get("/api/owners", params={"q": "zz"}).json()["rows"] == []
        assert cl.get("/api/owners/999999").status_code == 404


def test_search_finds_companies_by_owner(loaded):
    from acquireos.api import app

    loaded.commit()
    with TestClient(app) as cl:
        rows = cl.get("/api/companies", params={"q": "alex example", "sort": "relevance"}).json()["rows"]
        nums = {r["company_number"]: r for r in rows}
        assert "01000001" in nums and nums["01000001"]["matched_owner"] == "Mr Alex Example"


def test_funding_assumptions_are_kept_per_company(loaded):
    from acquireos.api import app

    loaded.commit()
    with TestClient(app) as cl:
        r = cl.put("/api/companies/01000001/state", json={"funding": {"price": 2500000, "investor_equity": 500000, "investor_stake": 30, "bogus": 1}})
        assert r.status_code == 200 and r.json()["funding"] == {"price": 2500000.0, "investor_equity": 500000.0, "investor_stake": 30.0}
        assert cl.get("/api/companies/01000001").json()["state"]["funding"]["investor_stake"] == 30


def test_show_filter_hides_decided_companies(loaded):
    from acquireos.api import app

    loaded.commit()
    with TestClient(app) as cl:
        cl.put("/api/companies/01000005/state", json={"status": "rejected"})
        cl.put("/api/companies/01000004/state", json={"status": "watching"})
        allc = {r["company_number"] for r in cl.get("/api/companies?limit=50").json()["rows"]}
        hidden = {r["company_number"] for r in cl.get("/api/companies?limit=50&mine=hide_closed").json()["rows"]}
        pipe = {r["company_number"] for r in cl.get("/api/companies?limit=50&mine=pipeline").json()["rows"]}
        fresh = {r["company_number"] for r in cl.get("/api/companies?limit=50&mine=untouched").json()["rows"]}
        assert "01000005" in allc and "01000005" not in hidden
        assert "01000004" in pipe and "01000005" not in pipe
        assert "01000004" not in fresh and "01000005" not in fresh


def test_profile_financials_brief_website_and_charges(loaded, monkeypatch):
    from acquireos import chapi, website
    from acquireos.api import app

    loaded.commit()
    with TestClient(app) as cl:
        d = cl.get("/api/companies/01000001").json()
        assert d["fin_summary"]["period_end"] and any(r["key"] == "net_assets" for r in d["fin_summary"]["rows"])
        assert d["ch"]["enabled"] is False and d["ch"]["charges"] == []
        b = cl.get("/api/companies/01000002/research-brief").json()
        assert b["name"] and b["search_queries"] and "how_to_confirm" in b
        assert any("DEMO HOLDINGS" in p for p in b["parent_companies"])
        # website check: a page showing the company number is confirmed and saved
        monkeypatch.setattr(website, "_fetch", lambda url, limit=600_000: (url, "<footer>Registered in England 01000001</footer>"))
        r = cl.post("/api/companies/01000001/find-website", json={"url": "examplesystems.co.uk"}).json()
        assert r["saved"] and r["results"][0]["confidence"] == "high"
        assert cl.get("/api/companies/01000001").json()["enrichment"]["website"] == "https://examplesystems.co.uk"
        # Companies House details need a key
        assert cl.post("/api/companies/01000001/fetch-details").status_code == 400
        monkeypatch.setattr(chapi.config, "CH_API_KEY", "x")
        def fake(path):
            if path.endswith("/charges?items_per_page=100"):
                return {"items": [{"charge_code": "c1", "status": "outstanding", "created_on": "2023-01-02",
                                   "classification": {"description": "A registered charge"},
                                   "persons_entitled": [{"name": "Development Bank of Wales PLC"}]}]}
            if "/filing-history" in path:
                return {"items": [
                    {"transaction_id": "t1", "date": "2023-01-03", "type": "SH01", "category": "capital",
                     "description": "capital-allotment-shares", "description_values": {"capital": [{"currency": "GBP", "figure": "1,000"}]}},
                    {"transaction_id": "t2", "date": "2024-02-01", "type": "CS01", "category": "confirmation-statement",
                     "description": "confirmation-statement", "links": {"document_metadata": "/document/abc"}},
                    {"transaction_id": "t3", "date": "2025-03-15", "type": "AA", "category": "accounts",
                     "description": "accounts-with-accounts-type-small", "description_values": {"made_up_date": "2024-03-31"}}]}
            if path.startswith("/company/01000001/officers"):
                return {"items": [{"name": "SMITH, Alex", "officer_role": "director", "appointed_on": "1994-03-01",
                                   "date_of_birth": {"year": 1961, "month": 4}, "occupation": "Director",
                                   "links": {"officer": {"appointments": "/officers/OFF1/appointments"}}}]}
            if path.startswith("/officers/OFF1/appointments"):
                return {"items": [{"officer_role": "director", "appointed_on": "2010-01-01",
                                   "appointed_to": {"company_number": "09999999", "company_name": "OTHER CO LTD", "company_status": "active"}}]}
            if path.endswith("/persons-with-significant-control-statements"):
                return {"items": []}
            if path == "/company/01000001":
                return {"has_charges": True, "has_insolvency_history": False}
            return None
        monkeypatch.setattr(chapi, "_document", lambda url: b"pdf")
        monkeypatch.setattr(chapi, "_pdf_text", lambda b: "Shareholding 1: 70 ORDINARY shares held as at the date of this confirmation statement\nName: ALEX SMITH\nShareholding 2: 30 ORDINARY shares held as at the date of this confirmation statement\nName: DBW INVESTMENTS (10) LIMITED\n")
        monkeypatch.setattr(chapi, "_get", fake)
        r = cl.post("/api/companies/01000001/fetch-details").json()
        assert r["fetched_charges"] == 1 and r["fetched_filings"] == 3 and len(r["charges"]) == 1
        kinds = [s["kind"] for s in r["signals"]]
        assert "charge" in kinds and "allotment" in kinds and "shareholder" in kinds
        assert r["officers"][0]["name"] == "SMITH, Alex" and r["officers"][0]["other_current"] == 1
        assert r["other_appointments"][0]["company_name"] == "OTHER CO LTD"
        assert [x["pct"] for x in r["shareholders"]] == [70.0, 30.0]
        assert r["late_filings"] and r["late_filings"][0]["days_late"] > 0


def test_mcp_tools_cover_owners_financials_research_and_pipeline(loaded):
    import json as _j

    from acquireos import mcp_server as m

    loaded.commit()
    from acquireos.api import app
    with TestClient(app):
        t = _j.loads(m.list_targets(limit=10))
        assert t["companies"] and all(c["score"] is not None for c in t["companies"])
        o = _j.loads(m.search_owners("alex example"))["rows"]
        assert o and _j.loads(m.get_owner(o[0]["id"]))["companies"]
        f = _j.loads(m.get_financials("01000001"))
        assert f["summary"]["rows"]
        b = _j.loads(m.research_brief("01000002"))
        assert b["search_queries"]
        ch = _j.loads(m.get_charges_and_investment("01000001", refresh=True))
        assert ch["enabled"] is False and "API key" in (ch["note"] or "")
        assert "rows" in _j.loads(m.list_pipeline())
        cmp = _j.loads(m.compare_companies(["01000001", "01000002", "XX999999"]))
        assert cmp[0]["name"] and "error" in cmp[2]
        r = _j.loads(m.log_outreach("01000001", "Sent intro letter", channel="letter", follow_up_on="2026-12-01"))
        assert r["company_number"] == "01000001"
        assert _j.loads(m.get_company("01000001"))["state"]["next_action_on"] == "2026-12-01"


def test_ch_sync_check_records_changes_and_queue(loaded, monkeypatch):
    from acquireos import chapi, chsync
    from acquireos.api import app

    loaded.commit()
    monkeypatch.setattr(chapi.config, "CH_API_KEY", "x")
    state = {"filings": [{"transaction_id": "f1", "date": "2024-01-01", "type": "CS01", "category": "confirmation-statement",
                          "description": "confirmation-statement"}],
             "officers": [{"name": "SMITH, Alex", "officer_role": "director", "appointed_on": "2000-01-01",
                           "links": {"officer": {"appointments": "/officers/OFF1/appointments"}}}],
             "charges": [], "etag": "e1"}
    calls = []

    def fake(path):
        calls.append(path)
        if path == "/company/01000003":
            return {"etag": state["etag"], "has_insolvency_history": False}
        if "/filing-history" in path:
            return {"items": state["filings"]}
        if "/officers?" in path:
            return {"items": state["officers"]}
        if "/charges" in path:
            return {"items": state["charges"]}
        return {"items": []}
    monkeypatch.setattr(chapi, "_get", fake)
    monkeypatch.setattr(chapi, "_document", lambda url: None)
    with TestClient(app) as cl:
        r = cl.post("/api/companies/01000003/ch-check").json()  # never fetched: full fetch, no changes recorded
        assert r["changed"] and r["changes"] == 0 and r["officers"]
        calls.clear()
        r = cl.post("/api/companies/01000003/ch-check").json()  # nothing new: two requests only
        assert not r["changed"] and len(calls) == 2
        state["filings"].insert(0, {"transaction_id": "f2", "date": "2025-02-01", "type": "SH01", "category": "capital",
                                    "description": "capital-allotment-shares"})
        state["officers"][0]["resigned_on"] = "2025-01-31"
        state["officers"].append({"name": "JONES, Sam", "officer_role": "director", "appointed_on": "2025-02-01",
                                  "links": {"officer": {"appointments": "/officers/OFF2/appointments"}}})
        state["charges"] = [{"charge_code": "c9", "status": "outstanding", "persons_entitled": [{"name": "HSBC UK Bank PLC"}]}]
        r = cl.post("/api/companies/01000003/ch-check").json()
        assert r["changed"] and r["changes"] == 4
        ch = cl.get("/api/changes", params={"days": 7, "scope": "all"}).json()["rows"]
        api_rows = [(x["kind"], x["field"]) for x in ch if x["source"] == "api"]
        assert ("filing", "SH01") in api_rows and ("director", "Resigned") in api_rows
        assert ("director", "Appointed") in api_rows and ("charge", "New charge") in api_rows
        # alerts: pipeline changes since last seen
        cl.put("/api/companies/01000003/state", json={"status": "researching"})
        assert cl.get("/api/meta").json()["counts"]["pipeline_new"] == 4  # unread changes, not companies
        rows = cl.get("/api/changes", params={"days": 7, "tracked": "true", "unread": "true"}).json()
        assert rows["unread"] == 4 and all(r["unread"] for r in rows["rows"])
        cl.post("/api/changes/read", json={"ids": [rows["rows"][0]["id"]]})
        assert cl.get("/api/meta").json()["counts"]["pipeline_new"] == 3
        cl.post("/api/changes/seen")  # mark all as read
        assert cl.get("/api/meta").json()["counts"]["pipeline_new"] == 0
        assert cl.get("/api/changes", params={"days": 7, "tracked": "true", "unread": "true"}).json()["rows"] == []
        # sync queue: the pipeline company is current, so the next work is targets never fetched
        with db.conn() as c:
            batch = chsync.next_batch(c, 5)
            assert batch and all(m == "full" for _, m in batch) and "01000003" not in [n for n, _ in batch]
            st = chsync.status(c)
            assert st["pipeline"]["fetched"] == 1 and st["targets"]["total"] >= 1
        assert cl.put("/api/ch-sync", json={"paused": True}).json()["paused"] is True


def test_ch_rate_schedule_is_shared(loaded):
    from acquireos import chapi

    loaded.commit()
    a, b = chapi._reserve(0.2), chapi._reserve(0.2)
    assert a is not None and b is not None and b >= a + 0.15  # the second request is booked after the first


def test_ch_sync_loop_fetches_targets(loaded, monkeypatch):
    import pytest

    from acquireos import chapi, chsync

    loaded.commit()
    monkeypatch.setattr(chapi.config, "CH_API_KEY", "x")
    monkeypatch.setattr(chapi, "_get", lambda path: {"items": []} if "?" in path or path.endswith("statements") else {"etag": "e"})
    monkeypatch.setattr(chapi, "_document", lambda url: None)

    class Stop(BaseException):
        pass
    sleeps = []

    def fake_sleep(s):
        sleeps.append(s)
        if s >= 120:  # the loop has run out of work (or is waiting): stop the test
            raise Stop
    monkeypatch.setattr(chsync.time, "sleep", fake_sleep)
    with pytest.raises(Stop):
        chsync.run_forever()
    with db.conn() as c:
        st = chsync.status(c)
        assert st["targets"]["fetched"] == st["targets"]["total"] > 0 and st["running"]


def test_ch_stream_updates_status_and_marks_watched(loaded):
    from acquireos import chstream, chsync

    loaded.commit()
    with db.conn() as c:
        c.execute("insert into ch_fetch (company_number, checked_at) values ('01000001', now())")
        target = c.execute("select company_number from company_best where company_number <> '01000001' limit 1").fetchone()
        batch = [
            ("companies", {"resource_uri": "/company/01000002", "event": {"type": "changed", "timepoint": 5},
                           "data": {"company_number": "01000002", "company_status": "active",
                                    "company_status_detail": "active-proposal-to-strike-off"}}),
            ("filings", {"resource_uri": "/company/01000001/filing-history/abc", "event": {"timepoint": 9}, "data": {}}),
            ("officers", {"resource_uri": "/company/01000001/appointments/x", "event": {"timepoint": 10}, "data": {}}),
            ("filings", {"resource_uri": "/company/99999999/filing-history/z", "event": {"timepoint": 11}, "data": {}}),
        ]
        if target:  # a target not yet fetched is left to the normal pass
            batch.append(("filings", {"resource_uri": f"/company/{target['company_number']}/filing-history/q", "data": {}}))
        got = chstream.process(c, batch)
        assert got["status_changes"] == 1
        dirty = {r["company_number"] for r in c.execute("select company_number from ch_dirty")}
        assert "01000001" in dirty and "99999999" not in dirty and (not target or target["company_number"] not in dirty)
        assert c.execute("select status from company where company_number = '01000002'").fetchone()["status"] == \
            "active - proposal to strike off"
        assert c.execute("select kinds from ch_dirty where company_number = '01000001'").fetchone()["kinds"] == \
            ["filings", "officers"]
        assert ("01000001", "full") in chsync.next_batch(c, 5)
        assert chstream.process(c, batch[:1])["status_changes"] == 0  # no change, nothing recorded


def test_ch_stream_reads_lines(monkeypatch):
    from acquireos import chstream

    monkeypatch.setattr(chstream.config, "CH_STREAM_KEY", "k")
    lines = [b"\n", b'{"resource_uri": "/company/01000001", "event": {"timepoint": 3}, "data": {}}\n', b"not json\n"]

    class Resp:
        def __enter__(self):
            return iter(lines)

        def __exit__(self, *a):
            return False

    class Stop(BaseException):
        pass
    monkeypatch.setattr(chstream.urllib.request, "urlopen", lambda req, timeout: Resp())
    monkeypatch.setattr(chstream.time, "sleep", lambda s: (_ for _ in ()).throw(Stop()))
    s = chstream.Streamer()
    import pytest
    with pytest.raises(Stop):
        s.read("filings")
    assert s.q.get_nowait()[1]["event"]["timepoint"] == 3 and s.q.empty()
    assert s.state["filings"]["error"] == "stream closed"


def test_enrichment_locations_facts_and_sources(loaded):
    from acquireos.api import app

    loaded.commit()
    with TestClient(app) as cl:
        r = cl.post("/api/companies/01000001/enrichment", json={
            "source_url": "https://example.com/about", "summary": "Sells IT support.\n\n- Microsoft partner\n- 40 staff",
            "locations": [{"name": "Head office", "address": "1 High St, London EC2A 4NJ", "kind": "head office"},
                          {"address": "Churchill House, Cardiff CF10 2HH", "kind": "office"}],
            "facts": [{"label": "Delisted from AIM", "value": "11 Apr 2024", "source_url": "https://example.com/rns"},
                      {"label": "Founded", "value": "2003"}],
            "linkedin": "linkedin.com/company/example", "sources": [{"url": "https://example.com/news", "label": "News"}]})
        assert r.status_code == 200, r.text
        e = cl.get("/api/companies/01000001").json()
        en, research = e["enrichment"], e["research"]
        assert [l["postcode"] for l in en["locations"]] == ["EC2A 4NJ", "CF10 2HH"]
        assert en["facts"][1]["source_url"] == "https://example.com/about"  # falls back to the main source
        assert en["linkedin"] == "https://linkedin.com/company/example"
        kinds = {x["kind"] for x in research}
        assert {"location", "fact", "source", "summary", "contact"} <= kinds
        bad = cl.post("/api/companies/01000001/enrichment", json={"source_url": "manual", "locations": [{"kind": "castle", "address": "x"}]})
        assert bad.status_code == 400


def test_api_owners_register_and_deeper_shareholder_search(loaded, monkeypatch):
    from acquireos import chapi

    loaded.commit()
    monkeypatch.setattr(chapi.config, "CH_API_KEY", "x")
    owners = [{"name": "Mrs Margaret Ann Vyse", "kind": "individual-person-with-significant-control",
               "natures_of_control": ["ownership-of-shares-25-to-50-percent"], "notified_on": "2016-04-06"}]
    docs = []

    def fake(path):
        if "persons-with-significant-control?" in path:
            return {"items": owners}
        if "/filing-history" in path:
            return {"items": [
                {"transaction_id": "a", "date": "2025-01-01", "type": "CS01", "description": "confirmation-statement-with-no-updates",
                 "links": {"document_metadata": "/document/new"}},
                {"transaction_id": "b", "date": "2015-03-01", "type": "AR01", "description": "annual-return-company-with-made-up-date-full-list-shareholders",
                 "description_values": {"made_up_date": "2015-02-28"}, "links": {"document_metadata": "/document/ar"}}]}
        if path == "/company/01000005":
            return {"etag": "e"}
        return {"items": []}
    monkeypatch.setattr(chapi, "_get", fake)
    monkeypatch.setattr(chapi, "_document", lambda url: docs.append(url) or b"x")
    monkeypatch.setattr(chapi, "_pdf_text", lambda b: "Shareholding 1: 50 ORDINARY shares held as at the date of this return\nName: MARGARET VYSE\n")
    with db.conn() as c:
        chapi.fetch(c, "01000005")
        f = c.execute("select psc, shareholders_from from ch_fetch where company_number = '01000005'").fetchone()
        assert f["psc"][0]["kind"] == "individual" and f["psc"][0]["natures"] == ["ownership-of-shares-25-to-50-percent"]
        assert docs == ["/document/ar"]  # the "no updates" statement is skipped
        assert f["shareholders_from"] == "AR01 made up to 2015-02-28"
        owners[0]["ceased_on"] = "2025-06-01"
        r = chapi.fetch(c, "01000005")
        assert r["changes"] >= 1
        assert c.execute("select 1 from company_change where company_number = '01000005' and kind = 'owner' and field = 'Owner left'").fetchone()


def test_trust_rules(loaded):
    """Unknown owners score nothing; research and shareholders beat the register;
    the company's own filed margin beats the default; the head office sets the region."""
    from acquireos import enrich, scoring, valuation
    from acquireos.api import app

    loaded.commit()
    crit = scoring.merged({})
    base = {"company_number": "X", "name": "X LTD", "status": "active", "employees": 30, "revenue_low": 2e6, "revenue_high": 2e6}
    unknown = {r["key"]: r for r in scoring.score_company(base, crit)["reasons"]}
    assert unknown["ownership"]["points"] == 0 and unknown["owner_age"]["points"] == 0
    lenient = {r["key"]: r for r in scoring.score_company(base, {**crit, "unknown_owner_points": 0.5})["reasons"]}
    assert lenient["ownership"]["points"] == crit["ownership"]["weight"] / 2
    # 17 shareholders: investor-backed, and owner age doesn't count
    vc = {**base, "ownership_type": "owner_held", "oldest_birth_year": 1960, "signals": ["many_shareholders"],
          "shareholder_names": [f"P{i}" for i in range(17)]}
    r = {x["key"]: x for x in scoring.score_company(vc, crit)["reasons"]}
    assert "Investor" in r["ownership"]["text"] and r["owner_age"]["points"] == 0
    # research says sold to a group: wins over "owner-held" on the register
    sold = {**base, "ownership_type": "owner_held", "research_ownership": "group_owned", "oldest_birth_year": 1960}
    r = {x["key"]: x for x in scoring.score_company(sold, crit)["reasons"]}
    assert r["ownership"]["points"] == 0 and "research" in r["ownership"]["text"]
    # recently sold signal excludes by default
    assert scoring.score_company({**base, "signals": ["recently_sold"]}, crit)["excluded"]
    # own filed margin (2%) instead of the default 8-15%
    a = valuation.assumptions({})
    v = valuation.value({"revenue_low": 4.1e6, "revenue_high": 4.1e6, "filed_margin": 2.0, "filed_margin_period": "2023-03-31"}, a)
    assert v["basis"] == "filed_margin" and round(v["ebitda_low"]) == 82000 and "2023" in v["steps"][0]
    assert valuation.value({"revenue_low": 4.1e6, "revenue_high": 4.1e6, "filed_margin": 2.0}, a, use_filed_margin=False)["basis"] == "estimated"
    # head office sets the trading region
    with db.conn() as c:
        enrich.save_enrichment(c, "01000001", source_url="https://example.com/contact", ownership="group_owned",
                               ownership_note="Bought by a group in 2024",
                               locations=[{"kind": "head office", "address": "1 Bridge St, Chester CH1 1AA"}])
        en = c.execute("select ownership, trading_postcode, trading_region from enrichment where company_number = '01000001'").fetchone()
        assert en["ownership"] == "group_owned" and en["trading_postcode"] == "CH1 1AA" and en["trading_region"]
        f = scoring.load_facts(c, "01000001")[0]
        assert f["research_ownership"] == "group_owned" and f["trading_region"] == en["trading_region"]
    with TestClient(app) as cl:
        d = cl.get("/api/companies/01000001").json()
        assert "signals" in d and "same_business" in d
        assert cl.post("/api/companies/01000002/merge", json={"into": "01000001"}).json()["merged_into"] == "01000001"
        d = cl.get("/api/companies/01000001").json()
        assert [m["company_number"] for m in d["merged_here"]] == ["01000002"]
        listed = [r["company_number"] for r in cl.get("/api/companies", params={"mine": "hide_closed", "limit": 50}).json()["rows"]]
        assert "01000002" not in listed and "01000001" in listed
        cl.post("/api/companies/01000002/merge", json={"into": None})
        listed = [r["company_number"] for r in cl.get("/api/companies", params={"mine": "hide_closed", "limit": 50}).json()["rows"]]
        assert "01000002" in listed


def test_website_offices():
    from acquireos.website import addresses

    got = addresses("Head Office: Data8 Ltd, Unit 4, Chester Business Park, Chester, CH4 9QZ. Tel 01244 000000 | "
                    "Wrexham office: 12 High St, Wrexham LL11 1AA")
    assert [a["postcode"] for a in got] == ["CH4 9QZ", "LL11 1AA"]
    assert got[0]["address"].startswith("Data8 Ltd, Unit 4")


def test_recently_sold_list_filter(loaded):
    from acquireos.api import app, refresh_stats

    loaded.commit()
    with db.conn() as c:
        # 01000002: its owner left as a company took over, two months ago
        c.execute("insert into person (person_key, kind, name, registration_number) values ('t-buyer', 'corporate', 'BIG GROUP PLC', '07777777')")
        c.execute("update company_person set ceased_on = current_date - 60 where company_number = '01000002'")
        c.execute("""insert into company_person (row_key, company_number, person_id, role, natures, notified_on)
                     select 'r-buy', '01000002', id, 'psc', '{ownership-of-shares-75-to-100-percent}', current_date - 60
                     from person where person_key = 't-buyer'""")
        c.execute("update company_ownership set ownership_type = 'group_owned' where company_number = '01000002'")
        refresh_stats(c)
        row = c.execute("select * from company_signal where company_number = '01000002'").fetchone()
        assert "recently_sold" in row["signals"] and row["sold_to"] == "BIG GROUP PLC"
    with TestClient(app) as cl:
        only = [r["company_number"] for r in cl.get("/api/companies", params={"sold": "only"}).json()["rows"]]
        hide = [r["company_number"] for r in cl.get("/api/companies", params={"sold": "hide", "limit": 100}).json()["rows"]]
        assert only == ["01000002"] and "01000002" not in hide
        d = cl.get("/api/companies/01000002").json()
        assert d["sold"]["sold_to"] == "BIG GROUP PLC"


def test_missing_turnover_years_estimated_from_own_revenue_per_head(loaded):
    from acquireos import fintrends
    from acquireos.importers.companies import refresh_estimates

    rows = [{"period_end": "2021-03-31", "turnover": 3_200_000, "employees": 30},
            {"period_end": "2022-03-31", "turnover": None, "employees": 33},
            {"period_end": "2024-03-31", "turnover": None, "employees": 36}]
    s = fintrends.series(rows)
    assert s[0]["turnover_basis"] == "filed" and "turnover_est" not in s[0]
    assert s[2]["turnover_basis"] == "estimated" and s[2]["turnover_est"] == 3_840_000
    t = next(r for r in fintrends.summary(rows)["rows"] if r["key"] == "turnover")
    assert t["estimated"] and t["value"] == 3_840_000
    loaded.commit()
    with db.conn() as c:
        c.execute("delete from financial_period where company_number = '01000006'")
        c.execute("""insert into financial_period (company_number, period_end, turnover, employees) values
                     ('01000006', current_date - 1100, 3200000, 30), ('01000006', current_date - 30, null, 36)""")
        c.execute("delete from estimate where company_number = '01000006'")
        refresh_estimates(c)
        e = c.execute("select * from estimate where company_number = '01000006'").fetchone()
        assert e["basis"] == "estimated" and "own revenue per head" in e["method"]
        assert round(float(e["revenue_low"])) == round(36 * 3200000 / 30 * 0.9)


def test_confirmation_statement_changes_are_spelled_out():
    from acquireos import chapi

    a = {("ALEX SMITH", "ORDINARY"): 60, ("SAM JONES", "ORDINARY"): 25, ("PAT LEE", "ORDINARY"): 15}
    b = {("ALEX SMITH", "ORDINARY"): 50, ("PAT LEE", "ORDINARY"): 15, ("DBW INVESTMENTS (10) LIMITED", "A"): 35}
    t = chapi._shareholder_diff(a, b)
    assert "Alex Smith 60% → 50%" in t and "new: Dbw Investments (10) Limited 35%" in t and "left: Sam Jones (was 25%)" in t
    assert "Pat Lee" not in t  # unchanged
    assert chapi._shareholder_diff(a, a) is None


def test_bulk_website_check_saves_only_strict_matches(loaded, monkeypatch):
    from acquireos import website

    loaded.commit()
    pages = {"https://examplesystems.co.uk": "<footer>Example Systems Ltd · Registered in England 01000001 · "
                                              "Unit 4, Chester Business Park, Chester, CH4 9QZ</footer>",
             "https://sampledata.co.uk": "<footer>Sample Data · Swansea SA1 1AA</footer>"}
    monkeypatch.setattr(website, "candidates", lambda names, limit=16: [
        "examplesystems.co.uk" if "EXAMPLE" in names[0] else "sampledata.co.uk"])
    monkeypatch.setattr(website, "_resolves", lambda d: True)
    monkeypatch.setattr(website, "_fetch", lambda url, limit=600_000: (url, pages[url]) if url in pages else None)
    with db.conn() as c:
        pc = c.execute("select postcode from company where company_number = '01000002'").fetchone()["postcode"]
        pages["https://sampledata.co.uk"] = f"<footer>Sample Data · {pc}</footer>"  # postcode only: not confirmed
        r = website.bulk_check(c, ["01000001", "01000002"])
        assert r["confirmed"] == 1 and r["possible"] == 1
        e1 = c.execute("select website, locations from enrichment where company_number = '01000001'").fetchone()
        assert e1["website"] == "https://examplesystems.co.uk" and e1["locations"][0]["postcode"] == "CH4 9QZ"
        assert not c.execute("select 1 from enrichment where company_number = '01000002' and website is not null").fetchone()
        assert c.execute("select 1 from research where company_number = '01000002' and content like 'Possible website%%'").fetchone()


def test_new_mcp_tools(loaded):
    import json as _j

    from acquireos import mcp_server as m
    from acquireos.api import app

    loaded.commit()
    with TestClient(app):
        r = _j.loads(m.search_companies(sold="hide", mine="hide_closed", limit=5))
        assert "companies" in r and all("signals" in x for x in r["companies"])
        assert _j.loads(m.combine_companies("01000002", "01000001"))["merged_into"] == "01000001"
        assert _j.loads(m.combine_companies("01000002", None))["merged_into"] is None
        assert "rows" in _j.loads(m.list_changes(days=30, unread_only=True))
        assert _j.loads(m.mark_changes_read(all=True))["ok"]
        b = _j.loads(m.daily_briefing())
        assert {"unread_pipeline_changes", "next_actions_due", "pipeline_sold_or_buying", "sync"} <= set(b)


def test_missing_accounts_years_read_through_the_api(loaded, monkeypatch):
    from acquireos import chapi

    from .conftest import FIX
    loaded.commit()
    monkeypatch.setattr(chapi.config, "CH_API_KEY", "x")
    doc = (FIX / "Prod224_0001_01000001_20270331.html").read_bytes()

    def fake(path):
        if "/filing-history" in path:
            return {"items": [
                {"transaction_id": "aa27", "date": "2027-09-01", "type": "AA", "category": "accounts",
                 "description_values": {"made_up_date": "2027-03-31"}, "links": {"document_metadata": "/document/x27"}},
                {"transaction_id": "aa26", "date": "2026-09-01", "type": "AA", "category": "accounts",
                 "description_values": {"made_up_date": "2026-03-31"}, "links": {"document_metadata": "/document/x26"}}]}
        if path == "/company/01000003":
            return {"etag": "e"}
        return {"items": []}
    monkeypatch.setattr(chapi, "_get", fake)
    monkeypatch.setattr(chapi, "_doc_formats", lambda link: ["application/pdf", "application/xhtml+xml"] if "x27" in link else ["application/pdf"])
    monkeypatch.setattr(chapi, "_document", lambda link, limit=0, accept="": doc if "x27" in link else None)
    with db.conn() as c:
        c.execute("delete from financial_period where company_number = '01000003'")
        r = chapi.fetch(c, "01000003", people=False)
        assert r["accounts_added"] == 1
        assert c.execute("select 1 from financial_period where company_number = '01000003' and period_end = '2027-03-31'").fetchone()
        f = c.execute("select accounts_pdf from ch_fetch where company_number = '01000003'").fetchone()
        assert f["accounts_pdf"] == ["2026-03-31"]  # only a PDF for that year


def test_save_financials_from_pdf(loaded):
    import json as _j

    from acquireos import mcp_server as m
    from acquireos.api import app

    loaded.commit()
    with TestClient(app) as cl:
        r = _j.loads(m.save_financials("01000003", "2025-12-31", "https://find-and-update.company-information.service.gov.uk/company/01000003/filing-history",
                                       turnover=12_500_000, operating_profit=900_000, employees=95, net_assets=2_100_000))
        assert r["saved"] == ["employees", "net_assets", "operating_profit", "turnover"]
        with db.conn() as c:
            fp = c.execute("select source, turnover from financial_period where company_number = '01000003' and period_end = '2025-12-31'").fetchone()
            assert fp["source"] == "pdf:claude" and float(fp["turnover"]) == 12_500_000
        d = cl.get("/api/companies/01000003").json()
        assert d["estimate"]["basis"] == "filed"
