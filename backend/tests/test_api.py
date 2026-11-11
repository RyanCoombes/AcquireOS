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
        assert cl.post("/api/companies/01000002/merge", json={"into": "01000001"}).status_code in (404, 405)  # removed

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
    monkeypatch.setattr(website, "candidates", lambda names, limit=16, **k: [
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
        assert not hasattr(m, "combine_companies")
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


def test_dormant_accounts_excluded_by_default():
    from acquireos import scoring

    crit = scoring.merged({})
    base = {"company_number": "X", "name": "X LTD", "status": "active", "employees": 30}
    r = scoring.score_company({**base, "accounts_category": "dormant"}, crit)
    assert r["excluded"] and "dormant" in r["exclusion"]
    assert not scoring.score_company({**base, "accounts_category": "small"}, crit)["excluded"]
    micro = {**crit, "exclude": {**crit["exclude"], "accounts_types": ["micro"]}}
    assert scoring.score_company({**base, "accounts_category": "micro entity"}, micro)["excluded"]


def test_revenue_basis_filter(loaded):
    from acquireos.api import app

    loaded.commit()
    with TestClient(app) as cl:
        def nums(v):
            return {r["company_number"] for r in cl.get("/api/companies", params={"revenue": v, "limit": 100}).json()["rows"]}
        filed, est, none = nums("filed"), nums("estimated"), nums("none")
        assert not (filed & est) and not (filed & none) and not (est & none)
        with db.conn() as c:
            assert filed == {r["company_number"] for r in c.execute("select company_number from estimate where basis = 'filed'")}


def test_targets_count_drops_when_ruled_out(loaded):
    from acquireos.api import app

    loaded.commit()
    with TestClient(app) as cl:
        before = cl.get("/api/meta").json()["counts"]["in_scope"]
        with db.conn() as c:
            num = c.execute("select company_number from company_best limit 1").fetchone()["company_number"]
        cl.put(f"/api/companies/{num}/state", json={"status": "rejected"})
        after = cl.get("/api/meta").json()["counts"]
        assert after["in_scope"] == before - 1 and after["in_boxes"] >= after["in_scope"]


def test_stored_and_live_signals_agree(loaded):
    from acquireos import enrich

    loaded.commit()
    with db.conn() as c:
        enrich.save_enrichment(c, "01000001", source_url="https://example.com/news", ownership="group_owned",
                               ownership_note="Bought by a group")
        c.execute("select ao_refresh_company_signals()")
        bad = c.execute("""select c.company_number from company c left join company_signal sg using (company_number)
                           where coalesce(sg.signals, '{}') is distinct from ao_signals(c.company_number)""").fetchall()
        assert bad == []
        assert "recently_sold" in c.execute("select ao_signals('01000001') as s").fetchone()["s"]


def test_presence_in_wales(loaded):
    from acquireos import enrich
    from acquireos.api import app
    from acquireos.normalise import region_for

    assert region_for("SY23 1AA") == "Wales" and region_for("SY3 8AB") == "England" and region_for("CH7 1AB") == "Wales"
    assert region_for("CH1 1AA") == "England" and region_for("CF10 1AA") == "Wales"
    loaded.commit()
    with db.conn() as c:
        assert c.execute("select ao_region('SY16 1AA') as r").fetchone()["r"] == "Wales"
        # an English-registered company with a researched office in Cardiff
        eng = c.execute("select company_number from company where region = 'England' limit 1").fetchone()["company_number"]
        enrich.save_enrichment(c, eng, source_url="https://example.com/contact",
                               locations=[{"kind": "office", "address": "1 Bute St, Cardiff CF10 5AA"}])
        c.execute("select ao_refresh_company_signals()")
        # and a Welsh-registered one with an office in Edinburgh: works for any nation
        wel = c.execute("select company_number from company where region = 'Wales' limit 1").fetchone()["company_number"]
        enrich.save_enrichment(c, wel, source_url="https://example.com/contact",
                               locations=[{"kind": "office", "address": "1 George St, Edinburgh EH2 2PF"}])
        c.execute("select ao_refresh_company_signals()")
        assert "office:Wales" in c.execute("select ao_signals(%s) as s", (eng,)).fetchone()["s"]
        bad = c.execute("""select c.company_number from company c left join company_signal sg using (company_number)
                           where coalesce(sg.signals, '{}') is distinct from ao_signals(c.company_number)""").fetchall()
        assert bad == []
    with TestClient(app) as cl:
        office = {r["company_number"] for r in cl.get("/api/companies", params={"wales": "office", "limit": 100}).json()["rows"]}
        anyw = {r["company_number"] for r in cl.get("/api/companies", params={"wales": "any", "limit": 100}).json()["rows"]}
        reg = {r["company_number"] for r in cl.get("/api/companies", params={"wales": "registered", "limit": 100}).json()["rows"]}
        assert office == {eng} and eng in anyw and reg <= anyw and eng not in reg  # older "wales=" links still work
        scot = {r["company_number"] for r in cl.get("/api/companies", params={"nation": "Scotland", "presence": "office", "limit": 100}).json()["rows"]}
        anys = {r["company_number"] for r in cl.get("/api/companies", params={"nation": "Scotland", "limit": 100}).json()["rows"]}
        assert scot == {wel} and wel in anys


def test_money_filters(loaded):
    from acquireos.api import app

    loaded.commit()
    with TestClient(app) as cl:
        def rows(**p):
            return cl.get("/api/companies", params={**p, "limit": 200}).json()["rows"]
        for r in rows(min_revenue=2_000_000):
            assert r["revenue_high"] is not None and float(r["revenue_high"]) >= 2_000_000
        for r in rows(max_revenue=1_000_000):
            assert float(r["revenue_low"]) <= 1_000_000
        with db.conn() as c:
            want = {x["company_number"] for x in c.execute("select company_number from company_latest where operating_profit >= 100000")}
            na = {x["company_number"] for x in c.execute("select company_number from company_latest where net_assets >= 500000")}
        assert {r["company_number"] for r in rows(min_profit=100_000)} == want
        assert {r["company_number"] for r in rows(min_net_assets=500_000)} == na


def test_watching_companies_and_owners(loaded):
    from acquireos import watch
    from acquireos.api import app

    loaded.commit()
    with TestClient(app) as cl:
        assert cl.post("/api/watch", json={"kind": "company", "ref": "01000003"}).status_code == 200
        assert cl.get("/api/companies/01000003").json()["watching"] is True
        pid = cl.get("/api/owners", params={"q": "alex example"}).json()["rows"][0]["id"]
        assert cl.post("/api/watch", json={"kind": "owner", "ref": str(pid)}).status_code == 200
        assert cl.get(f"/api/owners/{pid}").json()["watching"] is True
        with db.conn() as c:
            # the watched owner takes control of another company
            other = c.execute("""select company_number from company where company_number not in
                                 (select company_number from company_person where person_id = %s) limit 1""", (pid,)).fetchone()["company_number"]
            c.execute("""insert into company_person (row_key, company_number, person_id, role, natures, notified_on)
                         values ('w-new', %s, %s, 'psc', '{ownership-of-shares-75-to-100-percent}', current_date)""", (other, pid))
            assert watch.check(c) == 1
            ch = c.execute("select field, new_value from company_change where company_number = %s and kind = 'watch'", (other,)).fetchone()
            assert ch["new_value"] == "Became an owner" and "Watched owner" in ch["field"]
        rows = cl.get("/api/watch").json()["rows"]
        assert {r["kind"] for r in rows} == {"company", "owner"}
        assert cl.get("/api/meta").json()["counts"]["pipeline_new"] >= 1  # the alert badge
        assert other in {r["company_number"] for r in cl.get("/api/changes", params={"days": 7, "tracked": "true"}).json()["rows"]}
        cl.delete("/api/watch", params={"kind": "company", "ref": "01000003"})
        assert cl.get("/api/companies/01000003").json()["watching"] is False


def test_pdf_accounts_figures_are_read_and_checked():
    from acquireos import pdfaccounts

    from .conftest import FIX
    text = (FIX / "pdf_accounts.txt").read_text()
    ex = pdfaccounts.extract(text)
    f = ex["figures"]
    assert f["turnover"] == [4_123_456, 3_812_004]  # the note number "3" is not a figure
    assert f["operating_profit"] == [80_356, 111_504]
    assert f["profit_loss"] == [56_517, 87_078]
    assert f["net_assets"][0] == 2_100_000 and f["cash"][0] == 414_071 and f["debtors"][0] == 900_500
    assert ex["employees"] == 34 and not ex["dropped"]
    # contradictions are dropped, not guessed
    bad = text.replace("Total equity 2,100,000", "Total equity 9,999,999")
    assert "net_assets" not in pdfaccounts.extract(bad)["figures"]
    # £'000 accounts, and losses in brackets
    k = pdfaccounts.extract("£'000 £'000\nTurnover 12,500 11,000\nOperating loss (320) (150)\n")["figures"]
    assert k["turnover"][0] == 12_500_000 and k["operating_profit"][0] == -320_000
    # figures on the lines after the label (text taken from a table)
    t = pdfaccounts.extract("Turnover\n3\n1,234,567\n1,100,000\nCash at bank and in hand\n45,000\n30,000\n")["figures"]
    assert t["turnover"] == [1_234_567, 1_100_000] and t["cash"] == [45_000, 30_000]
    # common OCR slips: E for £, O for 0, full stops for commas
    o = pdfaccounts.extract("Turnover E1,2O4,000 £1.100.000\nDebtors 5 12.345 1O,000\n")["figures"]
    assert o["turnover"] == [1_204_000, 1_100_000] and o["debtors"] == [12_345, 10_000]
    # a micro-entity balance sheet: capital and reserves stands in for net assets
    m = pdfaccounts.extract("Net current assets 20,000 15,000\nCapital and reserves 52,310 40,100\n")["figures"]
    assert m["net_assets"] == [52_310, 40_100]
    # a policy sentence is not a figure
    assert "turnover" not in pdfaccounts.extract("Turnover represents amounts invoiced in 2024\n")["figures"]
    assert "cash" not in pdfaccounts.extract("Cash flow statement 2024 2023\n")["figures"]


def test_pdf_accounts_ocr_on_a_scanned_page():
    import io

    import pytest
    pytest.importorskip("PIL")
    from PIL import Image, ImageDraw, ImageFont

    from acquireos import pdfaccounts

    from .conftest import FIX
    if not pdfaccounts.ocr_available():
        pytest.skip("Tesseract not installed here")
    lines = (FIX / "pdf_accounts.txt").read_text().splitlines()
    img = Image.new("L", (1700, 60 + 44 * len(lines)), 255)
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
    for i, line in enumerate(lines):
        d.text((80, 30 + 44 * i), line, fill=0, font=font)
    buf = io.BytesIO()
    img.save(buf, "PDF", resolution=200)
    text, method = pdfaccounts.pdf_text(buf.getvalue())
    assert method == "ocr"
    f = pdfaccounts.extract(text)["figures"]
    assert f["turnover"][0] == 4_123_456 and f["net_assets"][0] == 2_100_000


def test_pdf_queue_newest_years_first(loaded):
    import json as _j

    from acquireos import pdfaccounts

    loaded.commit()
    with db.conn() as c:
        c.execute("delete from financial_period where company_number in ('01000001', '01000002')")
        for num, mu in (("01000001", "2025-03-31"), ("01000001", "2024-03-31"), ("01000001", "2015-03-31"),
                        ("01000002", "2025-12-31"), ("01000002", "2023-12-31")):
            c.execute("""insert into filing (company_number, transaction_id, filed_on, type, category, description, detail)
                         values (%s, %s, %s, 'AA', 'accounts', 'accounts-with-accounts-type-small', %s)""",
                      (num, f"t{num}{mu}", mu, _j.dumps({"made_up_date": mu, "document": f"/document/{num}{mu}"})))
        # a dormant year is never read
        c.execute("""insert into filing (company_number, transaction_id, filed_on, type, category, description, detail)
                     values ('01000002', 'dorm', '2024-12-31', 'AA', 'accounts', 'accounts-with-accounts-type-dormant', %s)""",
                  (_j.dumps({"made_up_date": "2024-12-31", "document": "/document/d"}),))
        q = [(r["company_number"], str(r["made_up"])) for r in pdfaccounts.queue(c, 10)]
        # each company's latest year before anyone's older ones; nothing over 5 years old
        assert {x[1] for x in q[:2]} == {"2025-03-31", "2025-12-31"}
        assert ("01000001", "2015-03-31") not in q and len(q) == 4
        assert pdfaccounts.queue_size(c) == 4
        assert pdfaccounts.todo_for(c, "01000001") == ["2025-03-31", "2024-03-31"]
        # a year that couldn't be read by an older reader is tried again; by this one, not
        c.execute("""insert into pdf_read (company_number, made_up, status, version) values
                     ('01000001', '2025-03-31', 'nothing_found', 1), ('01000002', '2025-12-31', 'nothing_found', %s)""",
                  (pdfaccounts.VERSION,))
        assert pdfaccounts.queue_size(c) == 3
        assert len(pdfaccounts.failures(c)) == 2 and pdfaccounts.retry(c, "01000002") == 1
        assert pdfaccounts.queue_size(c) == 4
        c.rollback()


def test_pdf_read_and_save(loaded, monkeypatch):
    import json as _j

    from acquireos import chapi, pdfaccounts
    from acquireos.api import app

    from .conftest import FIX
    loaded.commit()
    monkeypatch.setattr(chapi, "_document", lambda link, limit=0, accept="": b"%PDF")
    monkeypatch.setattr(chapi, "_doc_formats", lambda link: ["application/pdf"])
    monkeypatch.setattr(pdfaccounts, "pdf_text", lambda pdf, ocr_pages=20: ((FIX / "pdf_accounts.txt").read_text(), "ocr"))
    with db.conn() as c:
        c.execute("delete from financial_period where company_number = '01000003'")
        c.execute("""insert into filing (company_number, transaction_id, filed_on, type, category, description, detail)
                     values ('01000003', 'aa25', '2025-12-01', 'AA', 'accounts', 'accounts-with-accounts-type-full',
                             %s)""", (_j.dumps({"made_up_date": "2025-03-31", "document": "/document/zz"}),))
        r = pdfaccounts.read_and_save(c, "01000003", "2025-03-31")
        assert r["status"] == "done" and r["method"] == "ocr"
        rows = {str(x["period_end"]): x for x in c.execute(
            "select period_end, turnover, source from financial_period where company_number = '01000003'")}
        assert float(rows["2025-03-31"]["turnover"]) == 4_123_456 and rows["2025-03-31"]["source"] == "pdf:ocr"
        assert float(rows["2024-03-31"]["turnover"]) == 3_812_004  # the prior-year column fills the year before
        assert c.execute("select status from pdf_read where company_number = '01000003'").fetchone()["status"] == "done"
    with TestClient(app) as cl:
        d = cl.get("/api/companies/01000003").json()
        assert d["pdf_reads"][0]["method"] == "ocr" and d["estimate"]["basis"] == "filed"
        assert cl.get("/api/pdf-read").json()["done"] == 1


def test_disqualified_directors_exemptions_and_stream(loaded, monkeypatch):
    from acquireos import chapi, chextras, chstream

    loaded.commit()
    with db.conn() as c:
        num = "01000001"
        c.execute("insert into ch_fetch (company_number, checked_at, profile, psc) values (%s, now(), '{}', '[]') "
                  "on conflict (company_number) do update set psc = '[]'", (num,))
        c.execute("delete from officer where company_number = %s", (num,))
        c.execute("""insert into officer (company_number, officer_key, name, role, birth_year, birth_month)
                     values (%s, 'k1', 'SMITH, John Paul', 'director', 1970, 5),
                            (%s, 'k2', 'SMITH, Jane', 'director', 1970, 5)""", (num, num))
        calls = []

        def fake_get(path):
            calls.append(path)
            if path.startswith("/search/disqualified-officers"):
                return {"items": [{"title": "John Paul SMITH", "date_of_birth": "1970-05-12",
                                   "links": {"self": "/disqualified-officers/natural/abc"}},
                                  {"title": "John SMITH", "date_of_birth": "1981-02-01",
                                   "links": {"self": "/disqualified-officers/natural/other"}}]}
            if path == "/disqualified-officers/natural/abc":
                return {"forename": "John", "other_forenames": "Paul", "surname": "Smith", "date_of_birth": "1970-05-12",
                        "disqualifications": [{"disqualified_from": "2022-01-01", "disqualified_until": "2030-01-01",
                                               "reason": {"description_identifier": "misconduct", "act": "company-directors-disqualification-act-1986"},
                                               "company_names": ["OLD CO LIMITED"]}]}
            if path.endswith("/exemptions"):
                return {"exemptions": {"psc_exempt_as_trading_on_regulated_market": {
                    "exemption_type": "psc-exempt-as-trading-on-regulated-market", "items": [{"exempt_from": "2019-01-01"}]}}}
            return {}
        monkeypatch.setattr(chapi, "_get", fake_get)
        assert chextras.check_director(c, "k1", "SMITH, John Paul", 1970, 5) == 1  # the 1981 one is not him
        d = chextras.disqualified_for(c, num)
        # matched on surname, first name and month and year of birth: John, not Jane
        assert [x["officer_key"] for x in d] == ["k1"] and d[0]["company_names"] == ["OLD CO LIMITED"]
        assert "misconduct" in d[0]["reason"]
        chextras.company_extras(c, num)
        ex = c.execute("select exemptions, extras_version from ch_fetch where company_number = %s", (num,)).fetchone()
        assert ex["exemptions"][0]["from"] == "2019-01-01" and ex["extras_version"] == chextras.EXTRAS_VERSION
        st = chextras.status(c)
        assert st["disqualified_found"] >= 1 and st["directors_checked"] >= 1
        # a new disqualification on the stream is stored and matched
        chstream.process(c, [("disqualified", {"resource_uri": "/disqualified-officers/natural/xyz", "event": {"type": "changed"},
                                               "data": {"forename": "Jane", "surname": "SMITH", "date_of_birth": "1970-05-03",
                                                        "disqualifications": [{"disqualified_from": "2026-01-01"}]}})])
        assert {x["officer_key"] for x in chextras.disqualified_for(c, num)} == {"k1", "k2"}
        c.rollback()


def test_ebitda_adds_back_filed_depreciation():
    from acquireos import valuation

    a = valuation.assumptions(None)
    with_da = valuation.value({"operating_profit": 200_000, "da": 50_000, "bank_debt": 120_000}, a)
    assert with_da["ebitda_low"] == 250_000 and "EBITDA of £250k" in with_da["steps"][0]
    assert any("Bank loans" in x for x in with_da["steps"])
    without = valuation.value({"operating_profit": 200_000}, a)
    assert without["ebitda_low"] == 200_000 and "may be higher" in without["steps"][0]


def test_network_companies_and_people(loaded):
    from acquireos import network
    from acquireos.api import app

    loaded.commit()
    with db.conn() as c:
        num = c.execute("""select cp.company_number from company_person cp join person p on p.id = cp.person_id
                           where p.kind = 'individual' and cp.ceased_on is null and p.birth_year is not null limit 1""").fetchone()["company_number"]
        own = c.execute("""select p.id, p.name, p.birth_year, p.birth_month from company_person cp join person p on p.id = cp.person_id
                           where cp.company_number = %s and p.kind = 'individual' and cp.ceased_on is null limit 1""", (num,)).fetchone()
        # the same person as a director here and elsewhere (officer list format), and one unrelated director
        sur, first = network._parts(own["name"])
        c.execute("""insert into officer (company_number, officer_key, name, role, birth_year, birth_month)
                     values (%s, 'offA', %s, 'director', %s, %s), (%s, 'offB', 'NOBODY, Else', 'director', 1950, 1)
                     on conflict do nothing""",
                  (num, f"{sur}, {first.title()}", own["birth_year"], own["birth_month"], num))
        c.execute("""insert into officer_appointment (officer_key, company_number, company_name, role)
                     values ('offA', 'ZZ000001', 'OTHER CO LIMITED', 'director') on conflict do nothing""")
        c.commit()
        r = network.neighbours(c, f"c:{num}")
        ids = {n["id"] for n in r["nodes"]}
        # the owner who is also a director appears once, as the owner
        assert f"p:{own['id']}" in ids and "o:offA" not in ids and "o:offB" in ids
        kinds = {(e["source"], e["kind"]) for e in r["edges"]}
        assert (f"p:{own['id']}", "owns") in kinds and (f"p:{own['id']}", "director") in kinds
        # opening the person shows their other directorship
        p = network.neighbours(c, f"p:{own['id']}")
        assert "c:ZZ000001" in {n["id"] for n in p["nodes"]} and p["node"]["director"]
        # an officer link resolves to the same person
        assert network.neighbours(c, "o:offA")["node"]["id"] == f"p:{own['id']}"
    with TestClient(app) as cl:
        assert cl.get(f"/api/network/c:{num}").status_code == 200
        assert cl.get("/api/network/c:NOPE0000").status_code == 404


def test_compare_with_similar_companies(loaded):
    from acquireos.api import app

    loaded.commit()
    with TestClient(app) as cl:
        num = "01000001"
        r = cl.get(f"/api/companies/{num}/compare")
        assert r.status_code == 200
        d = r.json()
        assert set(d) == {"peers", "group", "metrics"}
        # too few similar companies in the test data to rank against: no percentile is made up
        assert all(m["pct"] is None for m in d["metrics"])
        assert cl.get("/api/companies/NOPE0000/compare").status_code == 404


def test_old_own_margin_does_not_cap_the_value():
    from acquireos import valuation

    a = valuation.assumptions(None)
    base = {"revenue_low": 3_400_000, "revenue_high": 4_100_000, "revenue_basis": "estimated", "filed_margin": 1.9}
    recent = valuation.value({**base, "filed_margin_period": "2024-09-30", "latest_period": "2025-09-30"}, a)
    old = valuation.value({**base, "filed_margin_period": "2023-09-30", "latest_period": "2025-09-30"}, a)
    # same low end (the company's own margin), but an old year no longer pins the top end near it
    assert recent["ebitda_low"] == old["ebitda_low"]
    assert old["ebitda_high"] == 4_100_000 * a["margin_high"] / 100 > recent["ebitda_high"]
    assert "older than its latest" in old["steps"][0]


def test_pdf_reader_never_replaces_figures_and_rejects_tiny_ones(loaded, monkeypatch):
    import json as _j
    from datetime import date

    from acquireos import chapi, pdfaccounts
    from acquireos.importers.accounts import _upsert

    # a "8" gross profit beside £34m turnover is a misread
    f = pdfaccounts.extract("Turnover 34,000,000 31,000,000\nGross profit 8 9\n")
    assert "gross_profit" not in f["figures"] and any("too small" in d for d in f["dropped"])
    loaded.commit()
    monkeypatch.setattr(chapi, "_document", lambda link, limit=0, accept="": b"%PDF")
    monkeypatch.setattr(chapi, "_doc_formats", lambda link: ["application/pdf"])
    monkeypatch.setattr(pdfaccounts, "pdf_text", lambda pdf, ocr_pages=20: ("Turnover 1,000,000 900,000\nGross profit 300,000 250,000\n", "ocr"))
    with db.conn() as c:
        num = "01000003"
        c.execute("delete from financial_period where company_number = %s", (num,))
        fy = date(2024, 9, 30)
        _upsert(c, num, fy, {"turnover": 4_970_000}, "pdf:claude", balance_date=fy)   # saved by Claude
        c.execute("""insert into filing (company_number, transaction_id, filed_on, type, category, description, detail)
                     values (%s, 'aa24', '2025-01-01', 'AA', 'accounts', 'accounts', %s) on conflict do nothing""",
                  (num, _j.dumps({"made_up_date": "2024-09-30", "document": "/document/zz"})))
        r = pdfaccounts.read_and_save(c, num, "2024-09-30")
        row = c.execute("select turnover, gross_profit from financial_period where company_number = %s and period_end = %s", (num, fy)).fetchone()
        assert float(row["turnover"]) == 4_970_000          # not replaced by the reading
        assert float(row["gross_profit"]) == 300_000         # the gap is filled
        assert "already held" in (r["note"] or "")
        c.rollback()


def test_pdf_redo_keeps_saves_and_flags_suspicious_years(loaded, monkeypatch):
    from datetime import date

    from acquireos import pdfaccounts
    from acquireos.api import app

    monkeypatch.setattr(pdfaccounts, "rescore_later", lambda nums: None)
    loaded.commit()
    client = TestClient(app)
    from acquireos.importers.accounts import _upsert

    with db.conn() as c:
        num = "01000003"
        c.execute("delete from financial_period where company_number = %s", (num,))
        c.execute("delete from pdf_read where company_number = %s", (num,))
        _upsert(c, num, date(2022, 3, 31), {"turnover": 2_000_000}, "accounts:x", balance_date=date(2022, 3, 31))
        _upsert(c, num, date(2023, 3, 31), {"turnover": 40_000_000, "gross_profit": 8}, "pdf:ocr", balance_date=date(2023, 3, 31))
        _upsert(c, num, date(2024, 3, 31), {"turnover": 2_200_000}, "pdf:claude", balance_date=date(2024, 3, 31))
        c.execute("insert into pdf_read (company_number, made_up, status, method, figures) values (%s, '2023-03-31', 'done', 'ocr', '{}')", (num,))
    sus = client.get("/api/pdf-read/suspicious").json()
    mine = [s for s in sus if s["company_number"] == num]
    assert len(mine) == 1 and str(mine[0]["period_end"]).startswith("2023")
    assert any("year before" in w for w in mine[0]["why"]) and any("under £100" in w for w in mine[0]["why"])
    assert client.get("/api/pdf-read").json()["suspicious"] >= 1
    # marking it checked takes it off the list
    client.post("/api/pdf-read/checked", json={"company_number": num, "period_end": "2023-03-31"})
    assert not [s for s in client.get("/api/pdf-read/suspicious").json() if s["company_number"] == num]
    # redo clears only the reader's figures and requeues the year
    r = client.post("/api/pdf-read/redo").json()
    assert r["figures_cleared"] >= 1
    with db.conn() as c:
        left = {str(x["period_end"]): x["source"] for x in c.execute(
            "select period_end, source from financial_period where company_number = %s", (num,))}
        assert left == {"2022-03-31": "accounts:x", "2024-03-31": "pdf:claude"}
        assert not c.execute("select 1 from pdf_read where company_number = %s", (num,)).fetchone()
        assert not c.execute("select 1 from figure_check where company_number = %s", (num,)).fetchone()


def test_buy_box_can_leave_out_industries():
    from acquireos import scoring

    c = {"company_number": "X1", "name": "HARBOUR JOINERY LTD", "status": "active", "sic_codes": ["43320", "68209"]}
    out = lambda ex: scoring.score_company(c, {"exclude": ex})
    assert out({"sic_prefixes": ["68"]})["exclusion"] == "Industry left out: 68209"
    assert not out({"sic_prefixes": ["68"], "sic_all": True})["excluded"]          # still does joinery
    assert out({"sic_prefixes": ["68", "4332"], "sic_all": True})["excluded"]       # everything it does is left out
    assert not out({"sic_prefixes": ["62"]})["excluded"]


def test_website_guesses_use_owners_and_town():
    from acquireos import website

    assert website._person_parts("HARRIS, John Michael") == ("john", "harris")
    assert website._person_parts("Mr John Michael Harris") == ("john", "harris")
    s = website.extra_stems("HARBOUR JOINERY LIMITED", ["HARRIS, John"], "Bridgend")
    assert "harrisjoinery" in s and "harrisandsons" in s and "johnharris" in s and "bridgendjoinery" in s
    c = website.candidates(["HARBOUR JOINERY LIMITED"], people=["Mr John Harris"], town="Bridgend")
    assert c[0] == "harbourjoinery.co.uk" and "harrisjoinery.co.uk" in c


def test_manually_saved_website_is_read_for_offices(loaded, monkeypatch):
    from acquireos import website
    from acquireos.api import app

    monkeypatch.setattr(website, "_fetch", lambda url, limit=0: (url, "<html><title>Us</title><p>Office: 1 High St, Lerwick ZE1 0AX</p></html>"))
    loaded.commit()
    num = loaded.execute("select company_number from company limit 1").fetchone()["company_number"]
    r = TestClient(app).post(f"/api/companies/{num}/find-website", json={"url": "example.co.uk", "save": True}).json()
    assert r["saved"] and [a["postcode"] for a in r["offices_added"]] == ["ZE1 0AX"]
    with db.conn() as c:
        e = c.execute("select website, locations from enrichment where company_number = %s", (num,)).fetchone()
        assert e["website"].startswith("https://example.co.uk") and any(l["postcode"] == "ZE1 0AX" for l in e["locations"])


def test_remove_website_lets_the_check_look_again(loaded):
    from acquireos import enrich
    from acquireos.api import app

    num = loaded.execute("select company_number from company limit 1").fetchone()["company_number"]
    enrich.save_enrichment(loaded, num, source_url="manual", website="https://wrong.example", by="me")
    loaded.execute("insert into website_check (company_number, result) values (%s, 'confirmed') on conflict do nothing", (num,))
    loaded.commit()
    r = TestClient(app).delete(f"/api/companies/{num}/website").json()
    assert r["removed"] == "https://wrong.example"
    with db.conn() as c:
        assert c.execute("select website from enrichment where company_number = %s", (num,)).fetchone()["website"] is None
        assert not c.execute("select 1 from website_check where company_number = %s", (num,)).fetchone()
        assert c.execute("select 1 from research where company_number = %s and content like 'Website removed%%'", (num,)).fetchone()


def test_pdf_check_shows_lines_and_saves_corrections(loaded, monkeypatch):
    import json as _j
    from datetime import date

    from acquireos import chapi, pdfaccounts
    from acquireos.api import app

    text = "[[page 6]]\nTurnover 4,110,456 2,704,331\nGross profit 1,913,374 1,292,427\nOperating profit 80,214 90,877\n" \
           "[[page 7]]\nNet assets 1,702,118 1,320,551\n"
    ex = pdfaccounts.extract(text)
    assert ex["lines"]["turnover"] == "Turnover 4,110,456 2,704,331" and ex["lines"]["net_assets"].startswith("Net assets")
    monkeypatch.setattr(chapi, "_document", lambda link, limit=0, accept="": b"%PDF-1.4 test")
    monkeypatch.setattr(chapi, "_doc_formats", lambda link: ["application/pdf"])
    monkeypatch.setattr(chapi, "enabled", lambda: True)
    monkeypatch.setattr(pdfaccounts, "pdf_text", lambda pdf, ocr_pages=20: (text, "ocr"))
    monkeypatch.setattr(pdfaccounts, "rescore_later", lambda nums: None)
    loaded.commit()
    with db.conn() as c:
        num = c.execute("select company_number from company order by company_number limit 1").fetchone()["company_number"]
        c.execute("delete from financial_period where company_number = %s", (num,))
        c.execute("delete from pdf_read where company_number = %s", (num,))
        c.execute("""insert into filing (company_number, transaction_id, filed_on, type, category, description, detail)
                     values (%s, 'aa23', '2024-01-01', 'AA', 'accounts', 'accounts', %s) on conflict do nothing""",
                  (num, _j.dumps({"made_up_date": "2023-09-30", "document": "/document/yy"})))
        assert pdfaccounts.read_and_save(c, num, "2023-09-30")["status"] == "done"
    cl = TestClient(app)
    d = cl.get(f"/api/pdf-read/check?company_number={num}&period_end=2023-09-30").json()
    assert d["figures"]["turnover"] == 4_110_456 and d["full"] and "[[page 7]]" in d["text"]
    assert d["lines"]["gross_profit"] == "Gross profit 1,913,374 1,292,427" and d["method"] == "ocr"
    assert cl.get(f"/api/pdf-read/pdf?company_number={num}&made_up=2023-09-30").content.startswith(b"%PDF")
    assert any(r["company_number"] == num for r in cl.get("/api/pdf-read/years?show=all").json())
    # correct one figure, clear another
    r = cl.post("/api/pdf-read/correct", json={"company_number": num, "period_end": d["period_end"],
                                                "values": {"gross_profit": 1_913_000, "operating_profit": None}}).json()
    assert len(r["changed"]) == 2
    with db.conn() as c:
        row = c.execute("select gross_profit, operating_profit, turnover, source from financial_period where company_number = %s and period_end = %s",
                        (num, date(2023, 9, 30))).fetchone()
        assert float(row["gross_profit"]) == 1_913_000 and row["operating_profit"] is None
        assert float(row["turnover"]) == 4_110_456 and row["source"] == "manual"
        assert c.execute("select 1 from figure_check where company_number = %s", (num,)).fetchone()


def test_control_only_person_is_not_the_owner_and_research_flows_to_subsidiaries(loaded):
    from acquireos import enrich, ownership, scoring

    c = loaded
    c.execute("insert into company (company_number, name, status) values ('77000001', 'LOOPTEST GROUP PLC', 'active'), "
              "('77000002', 'LOOPTEST LIMITED', 'active') on conflict do nothing")
    c.execute("""insert into person (person_key, kind, name, birth_year) values ('t:scott', 'individual', 'Andrew Scott', 1966),
                 ('t:grp', 'corporate', 'LOOPTEST GROUP PLC', null) on conflict do nothing""")
    c.execute("update person set registration_number = '77000001' where person_key = 't:grp'")
    sid = c.execute("select id from person where person_key = 't:scott'").fetchone()["id"]
    gid = c.execute("select id from person where person_key = 't:grp'").fetchone()["id"]
    c.execute("""insert into company_person (row_key, company_number, person_id, role, natures) values
                 ('t1', '77000001', %s, 'psc', '{significant-influence-or-control}'),
                 ('t2', '77000002', %s, 'psc', '{ownership-of-shares-75-to-100-percent}') on conflict do nothing""", (sid, gid))
    ownership.rebuild(c, links=False)
    for num in ("77000001", "77000002"):
        o = c.execute("select ownership_type, oldest_birth_year, flags from company_ownership where company_number = %s", (num,)).fetchone()
        assert o["ownership_type"] != "owner_held" and o["oldest_birth_year"] is None and "control_only" in o["flags"], (num, o)
    # Research on the group (investor-backed) applies to the subsidiary held through it.
    enrich.save_enrichment(c, "77000001", source_url="https://example.com/news", ownership="investor_backed", by="claude")
    f = scoring.load_facts(c, "77000002")[0]
    assert f["research_ownership"] == "investor_backed" and f["ownership_from_parent"]
    c.rollback()


def test_claude_saving_or_closing_takes_a_year_off_the_unreadable_list(loaded):
    import json as _j

    from acquireos import mcp_server as m, pdfaccounts

    loaded.commit()
    with db.conn() as c:
        num = c.execute("select company_number from company order by company_number limit 1").fetchone()["company_number"]
        c.execute("delete from pdf_read where company_number = %s", (num,))
        c.execute("""insert into pdf_read (company_number, made_up, status, method, figures) values
                     (%s, '2022-03-31', 'nothing_found', 'ocr', '{}'), (%s, '2021-03-31', 'failed', 'ocr', '{}')""", (num, num))
    r = _j.loads(m.save_financials(company_number=num, period_end="2022-03-31", source_url="https://example.com", turnover=1_234_567))
    assert r.get("checked")
    assert "Closed." == m.close_unreadable_accounts(company_number=num, made_up_date="2021-03-31", reason="dormant")
    with db.conn() as c:
        assert not [f for f in pdfaccounts.failures(c, 500) if f["company_number"] == num]
        rows = {str(x["made_up"]): (x["status"], x["method"]) for x in c.execute("select * from pdf_read where company_number = %s", (num,))}
        assert rows == {"2022-03-31": ("done", "claude"), "2021-03-31": ("closed", "ocr")}
        pdfaccounts.redo(c)  # a redo keeps Claude's reads and closed years
        assert c.execute("select count(*) as n from pdf_read where company_number = %s", (num,)).fetchone()["n"] == 2
        assert pdfaccounts.status(c)["closed"] >= 1
        c.rollback()


def test_cli_commands_still_run(loaded):
    """Every command shares main(): a local import there once broke all the others."""
    from acquireos import cli

    loaded.commit()
    cli.main(["rescore"])
    cli.main(["reclassify-owners"])
    cli.main(["fix-staff-years"])
    from acquireos import chsync, db as _db

    with _db.conn() as c:
        assert chsync.get_setting(c, "staff_year_fix", None)["at"]


def test_trustees_are_not_owners_and_a_trust_holdco_is_not_a_buyer(loaded):
    from acquireos import ownership

    c = loaded
    # Trading co <- holdco <- trust (trustees hold its shares "as trust"), like an EOT sale.
    c.execute("""insert into company (company_number, name, status, incorporation_date) values
                 ('78000001', 'DEANS TEST SERVICES LIMITED', 'active', '1982-01-01'),
                 ('78000002', 'DTS IT MANAGEMENT LIMITED', 'active', '2023-12-01') on conflict do nothing""")
    c.execute("""insert into person (person_key, kind, name, birth_year, registration_number) values
                 ('t:pr', 'individual', 'Peter Rogerson', 1940, null), ('t:gb', 'individual', 'Graham Berks', 1960, null),
                 ('t:hold', 'corporate', 'DTS IT MANAGEMENT LIMITED', null, '78000002') on conflict do nothing""")
    ids = {r["person_key"]: r["id"] for r in c.execute("select id, person_key from person where person_key in ('t:pr', 't:gb', 't:hold')")}
    c.execute("""insert into company_person (row_key, company_number, person_id, role, natures, notified_on) values
                 ('d1', '78000001', %(h)s, 'psc', '{ownership-of-shares-75-to-100-percent}', current_date - 300),
                 ('d2', '78000002', %(p)s, 'psc', '{ownership-of-shares-75-to-100-percent-as-trust,voting-rights-75-to-100-percent-as-trust}', current_date - 300),
                 ('d3', '78000002', %(g)s, 'psc', '{ownership-of-shares-75-to-100-percent-as-trust}', current_date - 300)
                 on conflict do nothing""", {"h": ids["t:hold"], "p": ids["t:pr"], "g": ids["t:gb"]})
    ownership.rebuild(c, links=False)
    o = c.execute("select ownership_type, oldest_birth_year from company_ownership where company_number = '78000001'").fetchone()
    assert o["ownership_type"] == "trust" and o["oldest_birth_year"] is None, o
    c.execute("select ao_refresh_company_signals()")
    sig = c.execute("select signals from company_signal where company_number = '78000002'").fetchone()
    assert not sig or "possible_buyer" not in sig["signals"]
    c.rollback()


def test_long_summary_is_shortened_and_links_saved(loaded):
    from acquireos import enrich

    num = loaded.execute("select company_number from company order by company_number limit 1").fetchone()["company_number"]
    long = ("WHAT IT DOES: Example gives firms phone lines inside Teams. Staff make calls from Teams in 100 countries.\n\n"
            "LATEST: revenue £14.9m, adjusted EBITDA -£0.7m.\n\nOWNERSHIP: founders still co-CEOs.")
    enrich.save_enrichment(loaded, num, source_url="https://example.com", summary=long, by="claude",
                           links=[{"title": "Raises £12m", "url": "https://example.com/news", "date": "2024-11-04"}])
    e = loaded.execute("select summary, links from enrichment where company_number = %s", (num,)).fetchone()
    assert e["summary"] == "Example gives firms phone lines inside Teams. Staff make calls from Teams in 100 countries."
    assert e["links"][0]["title"] == "Raises £12m" and e["links"][0]["kind"] == "news"
    full = loaded.execute("select content from research where company_number = %s and kind = 'summary' order by id desc limit 1", (num,)).fetchone()
    assert "OWNERSHIP: founders" in full["content"]   # the whole write-up is kept
    loaded.rollback()


def test_deals_from_companies_house_and_research(loaded):
    from acquireos import deals, enrich

    c = loaded
    c.execute("""insert into company (company_number, name, status, incorporation_date) values
                 ('79000001', 'TARGET IT LIMITED', 'active', '1995-01-01'), ('79000002', 'BUYER GROUP LIMITED', 'active', '2001-01-01'),
                 ('79000003', 'SMALLCO LIMITED', 'active', '2005-01-01') on conflict do nothing""")
    c.execute("""insert into person (person_key, kind, name, birth_year, registration_number) values
                 ('t:own', 'individual', 'Jane Owner', 1960, null), ('t:buyer', 'corporate', 'BUYER GROUP LIMITED', null, '79000002'),
                 ('t:tgt', 'corporate', 'TARGET IT LIMITED', null, '79000001') on conflict do nothing""")
    ids = {r["person_key"]: r["id"] for r in c.execute("select id, person_key from person where person_key in ('t:own','t:buyer','t:tgt')")}
    c.execute("""insert into company_person (row_key, company_number, person_id, role, natures, notified_on, ceased_on) values
                 ('e1', '79000001', %(o)s, 'psc', '{ownership-of-shares-75-to-100-percent}', '2016-04-06', '2024-03-28'),
                 ('e2', '79000001', %(b)s, 'psc', '{ownership-of-shares-75-to-100-percent}', '2024-03-28', null),
                 ('e3', '79000003', %(t)s, 'psc', '{ownership-of-shares-50-to-75-percent}', '2022-06-01', null)""",
              {"o": ids["t:own"], "b": ids["t:buyer"], "t": ids["t:tgt"]})
    c.execute("""insert into filing (company_number, transaction_id, filed_on, type, category, description) values
                 ('79000001', 'sh1', '2019-05-01', 'SH03', 'capital', 'purchase of own shares')""")
    c.execute("""insert into charge (company_number, charge_id, status, holders, created_on) values
                 ('79000001', 'ch1', 'outstanding', '{Barclays Bank UK PLC}', '2024-03-28')""")
    enrich.save_enrichment(c, "79000001", source_url="https://news.example.com/deal", by="claude",
                           deals=[{"date": "2024-03", "kind": "sold", "title": "Sold to Buyer Group", "value": "£4.2m"}])
    ev = deals.events(c, "79000001")
    kinds = [e["kind"] for e in ev]
    assert "sold" in kinds and "acquired" in kinds and "buyback" in kinds
    sale = next(e for e in ev if e["kind"] == "sold" and e["source"] == "Companies House")
    assert sale["title"] == "Sold to BUYER GROUP LIMITED" and "Barclays" in sale["detail"]
    # The researched sale is the same deal: merged into the Companies House event, with its value and source.
    assert "£4.2m" in sale["detail"] and sale["research_url"] == "https://news.example.com/deal"
    assert not any(e["source"] == "research" and e["kind"] == "sold" for e in ev)
    assert next(e for e in ev if e["kind"] == "acquired")["counterparty_number"] == "79000003"
    c.rollback()


def test_year_heading_is_not_read_as_staff_and_cleanup_keeps_saves(loaded):
    from datetime import date

    from acquireos import pdfaccounts
    from acquireos.importers.accounts import _upsert, fix_year_staff, year_as_staff

    # PDF staff note with the years as column headings.
    t = "Turnover 400,000 380,000\nThe average number of employees during the year was:\n2025 2024\nNo. No.\n4 3\n"
    assert pdfaccounts.extract(t)["employees"] == 4
    assert pdfaccounts.extract("Average number of employees 12 11")["employees"] == 12
    # Electronic accounts: the year tagged as the staff figure.
    assert year_as_staff(2025, date(2025, 3, 31)) and year_as_staff(2024, date(2025, 3, 31))
    assert not year_as_staff(2025, date(2025, 3, 31), turnover=150_000_000)   # really that big
    assert not year_as_staff(25, date(2025, 3, 31))

    c = loaded
    nums = [r["company_number"] for r in c.execute("select company_number from company order by company_number limit 3")]
    for n in nums:
        c.execute("delete from financial_period where company_number = %s", (n,))
    _upsert(c, nums[0], date(2025, 3, 31), {"employees": 2025, "net_assets": 10_000}, "pdf:ocr", balance_date=date(2025, 3, 31))
    _upsert(c, nums[1], date(2024, 12, 31), {"employees": 2024}, "manual", balance_date=date(2024, 12, 31))       # yours: kept
    _upsert(c, nums[2], date(2024, 12, 31), {"employees": 2024, "turnover": 90_000_000}, "accounts:x", balance_date=date(2024, 12, 31))
    r = fix_year_staff(c)
    emp = {n: c.execute("select employees from financial_period where company_number = %s", (n,)).fetchone()["employees"] for n in nums}
    assert emp[nums[0]] is None and emp[nums[1]] == 2024 and emp[nums[2]] == 2024
    assert r["companies"] == 1
    c.rollback()


def test_electronic_accounts_prefer_the_real_staff_figure_over_the_year():
    from acquireos.importers.accounts import implausible_staff, parse

    ctx = ('<xbrli:context id="d0"><xbrli:entity><xbrli:identifier>01</xbrli:identifier></xbrli:entity>'
           '<xbrli:period><xbrli:startDate>2024-04-01</xbrli:startDate><xbrli:endDate>2025-03-31</xbrli:endDate></xbrli:period></xbrli:context>')
    # The year heading tagged as staff first, then the real figure.
    doc = (f'<html><ix:header>{ctx}</ix:header>'
           '<ix:nonFraction name="core:AverageNumberEmployeesDuringPeriod" contextRef="d0">2025</ix:nonFraction>'
           '<ix:nonFraction name="core:AverageNumberEmployeesDuringPeriod" contextRef="d0">4</ix:nonFraction></html>')
    from datetime import date
    assert parse(doc)[date(2025, 3, 31)]["employees"] == 4
    # Only the year: dropped, not kept as 2,025 staff.
    only = doc.replace('<ix:nonFraction name="core:AverageNumberEmployeesDuringPeriod" contextRef="d0">4</ix:nonFraction>', "")
    assert "employees" not in parse(only).get(date(2025, 3, 31), {})
    assert implausible_staff(1200, 400_000) and not implausible_staff(1200, 60_000_000) and not implausible_staff(40, 100)


def test_cleared_staff_years_are_read_again_from_companies_house(loaded, monkeypatch):
    from datetime import date

    from acquireos import chapi
    from acquireos.importers.accounts import _upsert, fix_year_staff

    ctx = ('<xbrli:context id="d0"><xbrli:entity><xbrli:identifier>01</xbrli:identifier></xbrli:entity>'
           '<xbrli:period><xbrli:startDate>2024-04-01</xbrli:startDate><xbrli:endDate>2025-03-31</xbrli:endDate></xbrli:period></xbrli:context>')
    doc = (f'<html><ix:header>{ctx}</ix:header>'
           '<ix:nonFraction name="core:AverageNumberEmployeesDuringPeriod" contextRef="d0">2025</ix:nonFraction>'
           '<ix:nonFraction name="core:AverageNumberEmployeesDuringPeriod" contextRef="d0">7</ix:nonFraction></html>').encode()
    monkeypatch.setattr(chapi, "enabled", lambda: True)
    calls = []
    monkeypatch.setattr(chapi, "_get", lambda path: calls.append(path) or {"items": [
        {"type": "AA", "description_values": {"made_up_date": "2025-03-31"}, "links": {"document_metadata": "/document/abc"}}]})
    monkeypatch.setattr(chapi, "_doc_formats", lambda link: ["application/xhtml+xml", "application/pdf"])
    monkeypatch.setattr(chapi, "_document", lambda link, limit=0, accept="": doc)
    c = loaded
    num = c.execute("select company_number from company order by company_number limit 1").fetchone()["company_number"]
    c.execute("delete from financial_period where company_number = %s", (num,))
    _upsert(c, num, date(2025, 3, 31), {"employees": 2025, "net_assets": 5000}, "accounts:x", balance_date=date(2025, 3, 31))
    r = fix_year_staff(c)
    assert r["data_years_reread"] == 1 and calls and "filing-history" in calls[0]
    assert c.execute("select employees from financial_period where company_number = %s", (num,)).fetchone()["employees"] == 7
    c.rollback()


def test_staff_scale_nil_and_page_scales():
    from datetime import date

    from acquireos import pdfaccounts
    from acquireos.importers.accounts import parse

    ctx = ('<xbrli:context id="d0"><xbrli:entity><xbrli:identifier>01</xbrli:identifier></xbrli:entity>'
           '<xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period></xbrli:context>')
    def doc(staff_tag, turnover_tag=""):
        return f'<html><ix:header>{ctx}</ix:header>{turnover_tag}{staff_tag}</html>'
    # £000 scale on the headcount is ignored; on money it applies.
    d = parse(doc('<ix:nonFraction name="core:AverageNumberEmployeesDuringPeriod" contextRef="d0" scale="3">956</ix:nonFraction>',
                  '<ix:nonFraction name="core:TurnoverRevenue" contextRef="d0" scale="3">250,000</ix:nonFraction>'))[date(2024, 12, 31)]
    assert d["employees"] == 956 and d["turnover"] == 250_000_000
    # "Nil" is zero, not missing.
    d = parse(doc('<ix:nonFraction name="core:AverageNumberEmployeesDuringPeriod" contextRef="d0">Nil</ix:nonFraction>'))[date(2024, 12, 31)]
    assert d["employees"] == 0
    # A reference number read as staff, with no turnover: dropped.
    d = parse(doc('<ix:nonFraction name="core:AverageNumberEmployeesDuringPeriod" contextRef="d0">858226</ix:nonFraction>'))
    assert "employees" not in d.get(date(2024, 12, 31), {})
    # PDFs: statements in £m on one page, notes in £ on another; staff never scaled.
    t = ("[[page 3]]\nIncome statement £m\nTurnover 4.97 4.11\nOperating profit 0.49 0.08\n"
         "[[page 9]]\nNotes (in £)\nAverage number of employees 2024 2023\n41 38\n")
    ex = pdfaccounts.extract(t)
    assert ex["figures"]["turnover"][0] == 4_970_000 and ex["employees"] == 41
    assert pdfaccounts.extract("Turnover 500,000\nThere were no employees apart from the directors (2020: Nil)")["employees"] == 0


def test_cleanup_covers_scaled_and_reference_staff_and_checks_big_companies(loaded, monkeypatch):
    from datetime import date

    from acquireos import chapi
    from acquireos.importers.accounts import _upsert, fix_year_staff

    ctx = ('<xbrli:context id="d0"><xbrli:entity><xbrli:identifier>01</xbrli:identifier></xbrli:entity>'
           '<xbrli:period><xbrli:startDate>2018-01-01</xbrli:startDate><xbrli:endDate>2018-12-31</xbrli:endDate></xbrli:period></xbrli:context>')
    filing = (f'<html><ix:header>{ctx}</ix:header>'
              '<ix:nonFraction name="core:AverageNumberEmployeesDuringPeriod" contextRef="d0">2018</ix:nonFraction>'
              '<ix:nonFraction name="core:AverageNumberEmployeesDuringPeriod" contextRef="d0">144</ix:nonFraction></html>').encode()
    monkeypatch.setattr(chapi, "enabled", lambda: True)
    monkeypatch.setattr(chapi, "_get", lambda path: {"items": [{"type": "AA", "description_values": {"made_up_date": "2018-12-31"},
                                                                "links": {"document_metadata": "/document/x"}}]})
    monkeypatch.setattr(chapi, "_doc_formats", lambda link: ["application/xhtml+xml"])
    monkeypatch.setattr(chapi, "_document", lambda link, limit=0, accept="": filing)
    c = loaded
    nums = [r["company_number"] for r in c.execute("select company_number from company order by company_number limit 3")]
    for n in nums:
        c.execute("delete from financial_period where company_number = %s", (n,))
    _upsert(c, nums[0], date(2024, 12, 31), {"employees": 956000, "turnover": 250_000_000}, "accounts:x", balance_date=date(2024, 12, 31))
    _upsert(c, nums[1], date(2024, 12, 31), {"employees": 858226, "net_assets": 1000}, "accounts:x", balance_date=date(2024, 12, 31))
    _upsert(c, nums[2], date(2018, 12, 31), {"employees": 2018, "turnover": 60_000_000}, "accounts:x", balance_date=date(2018, 12, 31))
    r = fix_year_staff(c)
    emp = {n: c.execute("select employees from financial_period where company_number = %s", (n,)).fetchone()["employees"] for n in nums}
    assert r["years"] == 2 and r["large_corrected"] == 1
    assert emp[nums[2]] == 144                       # big company: checked against the filing and corrected
    assert emp[nums[0]] == 144 or emp[nums[0]] is None  # cleared, then refilled from the (mocked) filing
    c.rollback()


def test_sic_exclusion_rules_with_exceptions():
    from acquireos import scoring

    rule = {"exclude": {"sic_rules": [{"codes": ["61200"], "unless": ["62", "63"]}]}}
    op = {"company_number": "X1", "name": "WIRELESS OP LTD", "status": "active", "sic_codes": ["61200", "61900"]}
    sw = {"company_number": "X2", "name": "CHAT SOFTWARE LTD", "status": "active", "sic_codes": ["61200", "62012"]}
    tel = {"company_number": "X3", "name": "TELEPHONY LTD", "status": "active", "sic_codes": ["61900"]}
    assert scoring.score_company(op, rule)["exclusion"] == "Industry left out: 61200 (no 62 or 63 code)"
    assert not scoring.score_company(sw, rule)["excluded"]
    assert not scoring.score_company(tel, rule)["excluded"]


def test_claude_can_change_buy_box_settings(loaded):
    import json as _j

    from acquireos import mcp_server as m

    loaded.commit()
    r = _j.loads(m.update_buy_box({"exclude": {"sic_rules": [{"codes": ["61200"], "unless": ["62", "63"]}]}, "staff": {"min": 5}}))
    assert any(x.startswith("exclude.sic_rules") for x in r["changed"]) and any(x.startswith("staff.min") for x in r["changed"])
    bb = _j.loads(m.get_buy_box())
    assert bb["criteria"]["exclude"]["sic_rules"][0]["unless"] == ["62", "63"] and bb["criteria"]["staff"]["min"] == 5
    assert bb["criteria"]["exclude"]["keywords"]   # other settings kept
