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
