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
