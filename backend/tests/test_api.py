import io

from fastapi.testclient import TestClient

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
        assert lst["rows"][0]["score"] >= lst["rows"][-1]["score"]
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
        assert cl.put("/api/buybox", json={"criteria": bb["criteria"]}).json()["rescored"] == 7
        assert cl.get("/api/export.csv").status_code == 200
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
        # saved search belongs to the active buy box
        s = cl.post("/api/searches", json={"name": "Wales", "params": {"region": "Wales"}}).json()
        assert s["buy_box_id"] == copy["id"]
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
