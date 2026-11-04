from datetime import date

from acquireos import normalise as n
from acquireos import scoring
from acquireos.importers import companies, notes

from .conftest import FIX


def test_company_numbers_are_padded():
    assert n.company_number("2511854") == "02511854"
    assert n.company_number(2511854.0) == "02511854"
    assert n.company_number("SC123456") == "SC123456"
    assert n.company_number("sc12345") == "SC012345"


def test_detects_ranked_columns():
    p = companies.preview(FIX / "ranked_sample.csv")
    m = p["mapping"]
    assert m["company_number"] == "company_number"
    assert m["name"] == "company_name"
    assert m["sic"] == "nature_of_business"
    assert m["net_assets_prev"] == "net_assets_prev"
    assert "rank" in p["unmapped"]


def test_import_companies(c):
    r = companies.run(c, FIX / "ranked_sample.csv")
    assert r["rows_ok"] == 7
    co = c.execute("select * from company where company_number = '01000001'").fetchone()
    assert co["region"] == "Wales"
    assert co["sic_codes"] == ["62020", "62090"]
    assert co["postcode"] == "SA1 1AA"
    assert co["extra"]["rank"] == "1"
    flags = {x["company_number"]: x["address_flag"] for x in c.execute("select company_number, address_flag from company")}
    assert flags["01000004"] == "ch_default"
    assert flags["01000005"] == "formation_agent"
    periods = c.execute("select * from financial_period where company_number='01000001' order by period_end").fetchall()
    assert [p["period_inferred"] for p in periods] == [True, False]
    assert periods[0]["employees"] == 31
    est = c.execute("select * from estimate where company_number='01000002'").fetchone()
    assert est["basis"] == "filed" and float(est["revenue_low"]) == 2950000


def test_reimport_is_idempotent(c):
    companies.run(c, FIX / "ranked_sample.csv")
    companies.run(c, FIX / "ranked_sample.csv")
    assert c.execute("select count(*) as n from company").fetchone()["n"] == 7
    assert c.execute("select count(*) as n from financial_period").fetchone()["n"] == 14


def test_ownership(loaded):
    c = loaded
    o = {r["company_number"]: r for r in c.execute("select * from company_ownership")}
    assert o["01000001"]["ownership_type"] == "owner_held"
    assert o["01000001"]["oldest_birth_year"] == 1961
    # owned via holdco 01000003, whose owners are two individuals
    assert o["01000002"]["ownership_type"] == "owner_held"
    assert "via_holdco" in o["01000002"]["flags"]
    assert o["01000002"]["owner_count"] == 2
    assert o["01000004"]["ownership_type"] == "foreign_owned"
    assert o["SC123456"]["ownership_type"] == "eot"
    assert "recent_change" in o["01000003"]["flags"]
    assert "recent_change" not in o["01000001"]["flags"]  # 2016-04-06 is the register start
    assert o["01000006"]["ownership_type"] == "unknown"


def test_links(loaded):
    c = loaded
    links = {(r["a"], r["b"], r["kind"]): r for r in c.execute("select * from company_link")}
    assert links[("01000002", "01000003", "owned_by")]["confidence"] == "confirmed"
    shared = links[("01000001", "01000002", "shared_owner")]
    assert shared["confidence"] == "likely" and "Alex Example" in shared["via"]
    assert ("01000001", "01000002", "shared_address") in links


def test_scoring_explains_and_excludes(loaded):
    c = loaded
    s = {r["company_number"]: r for r in c.execute("select * from score")}
    assert s["01000006"]["excluded"] and "electrical" in s["01000006"]["exclusion"]
    assert s["SC123456"]["excluded"]
    assert s["01000005"]["excluded"]  # dormant tier
    top = s["01000001"]
    assert not top["excluded"] and top["score"] > 60
    keys = {r["key"] for r in top["reasons"]}
    assert {"staff", "owner_age", "ownership", "revenue"} <= keys
    assert all(r["text"] for r in top["reasons"])


def test_unknown_data_is_not_a_miss():
    r = scoring.score_company({"name": "X"}, {}, date(2026, 11, 4))
    assert r["coverage"] == 0
    assert all(x["status"] == "unknown" for x in r["reasons"])


def test_notes_import_and_protection(loaded):
    c = loaded
    st = {r["company_number"]: r for r in c.execute("select * from user_company")}
    assert st["01000001"]["status"] == "approach" and st["01000001"]["rating"] == 4
    assert st["01000002"]["status"] == "researching"
    assert st["01000006"]["status"] == "rejected"
    n_before = c.execute("select count(*) as n from user_note").fetchone()["n"]
    assert n_before == 4  # 3 assess notes + 1 review log
    # my change in the app must survive re-importing the workbook
    c.execute("update user_company set status='in_talks', rating=5 where company_number='01000001'")
    notes.run(c, FIX / "notes_sample.csv")
    row = c.execute("select * from user_company where company_number='01000001'").fetchone()
    assert row["status"] == "in_talks" and row["rating"] == 5
    assert c.execute("select count(*) as n from user_note").fetchone()["n"] == n_before
    # and so must a full company re-import
    companies.run(c, FIX / "ranked_sample.csv")
    assert c.execute("select count(*) as n from user_note").fetchone()["n"] == n_before


def test_status_words():
    assert notes.map_status("Reject - field service") == "rejected"
    assert notes.map_status("Shortlist") == "approach"
    assert notes.map_status("") is None


def test_bulk_file_refresh_records_changes(loaded):
    c = loaded
    pv = companies.preview(FIX / "ch_bulk_update.csv")
    assert pv["mapping"]["company_number"].strip() == "CompanyNumber"
    assert isinstance(pv["mapping"]["sic"], list) and len(pv["mapping"]["sic"]) == 4
    assert isinstance(pv["mapping"]["address"], list)
    r = companies.run(c, FIX / "ch_bulk_update.csv", only_existing=True)
    assert r["rows_ok"] == 3 and r["rows_skipped"] == 1  # Someone Else Ltd ignored
    assert c.execute("select 1 from company where company_number='01234567'").fetchone() is None
    ch = {(x["company_number"], x["kind"]): x for x in c.execute("select * from company_change")}
    assert ch[("01000006", "status")]["new_value"] == "dissolved"
    assert ch[("01000002", "name")]["new_value"] == "SAMPLE DATA GROUP LTD"
    assert ("01000002", "address") in ch
    # new accounts filed (date only in the bulk file), recorded once
    assert ch[("01000001", "accounts")]["new_value"] == "2027-03-31"
    companies.run(c, FIX / "ch_bulk_update.csv", only_existing=True)
    assert c.execute("select count(*) as n from company_change").fetchone()["n"] == len(ch)
    co = c.execute("select * from company where company_number='01000006'").fetchone()
    assert co["status"] == "dissolved" and co["dissolution_date"] == date(2026, 10, 1)
    assert co["status_changed_at"] is not None
    # unchanged SIC codes (same set) are not recorded as a change
    assert ("01000001", "sic") not in ch


def test_new_accounts_recorded(loaded):
    import csv, tempfile
    from pathlib import Path

    c = loaded
    rows = list(csv.DictReader((FIX / "ranked_sample.csv").open()))
    rows[0]["accounts_made_up_to"] = "2027-03-31"
    rows[0]["employees"] = "41"
    p = Path(tempfile.mkdtemp()) / "update.csv"
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows[:1])
    companies.run(c, p)
    kinds = {x["kind"]: x for x in c.execute("select * from company_change where company_number='01000001'")}
    assert kinds["accounts"]["new_value"] == "2027-03-31"
    assert kinds["staff"]["old_value"] == "34" and kinds["staff"]["new_value"] == "41"


def test_valuation():
    from acquireos import valuation

    a = valuation.assumptions({})
    v = valuation.value({"revenue_low": 2_000_000, "revenue_high": 4_000_000, "revenue_basis": "estimated"}, a)
    assert v["ebitda_low"] == 160_000 and v["ebitda_high"] == 600_000
    assert v["value_low"] == 480_000 and v["value_high"] == 3_000_000
    assert v["basis"] == "estimated" and len(v["steps"]) == 2
    f = valuation.value({"operating_profit": 300_000, "revenue_low": 1, "cash": 50_000}, a)
    assert f["basis"] == "filed" and f["value_low"] == 900_000 and "Cash" in f["steps"][-1]
    o = valuation.assumptions({}, {"multiple_high": 6})
    assert o["multiple_high"] == 6.0 and o["multiple_low"] == 3.0
    assert valuation.value({}, a)["value_low"] is None


def test_zipped_bulk_file_streams(loaded, tmp_path):
    import zipfile

    z = tmp_path / "BasicCompanyDataAsOneFile-2026-11-01.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(FIX / "ch_bulk_update.csv", "BasicCompanyDataAsOneFile-2026-11-01.csv")
    pv = companies.preview(z)
    assert pv["row_count"] is None and len(pv["sample"]) == 4
    r = companies.run(loaded, z, only_existing=True)
    assert r["rows_in"] == 4 and r["rows_ok"] == 3
