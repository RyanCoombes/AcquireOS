import json
from datetime import date
from pathlib import Path

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
    assert o["01000004"]["ownership_type"] == "foreign_owned"  # a Delaware corporation: a real foreign group
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
    assert all(x["status"] == "unknown" for x in r["reasons"] if not x.get("manual"))
    assert all(x["status"] == "unscored" for x in r["reasons"] if x.get("manual"))


def test_manual_scores_count_only_when_given():
    base = {"name": "X", "employees": 30, "incorporation_date": date(2000, 1, 1), "sic_codes": ["62020"],
            "ownership_type": "owner_held", "oldest_birth_year": 1960, "revenue_low": 3e6, "revenue_high": 3e6}
    a = scoring.score_company(base, {}, date(2026, 11, 4))
    high = scoring.score_company({**base, "manual": {"recurring_quality": 5, "owner_openness": 5}}, {}, date(2026, 11, 4))
    low = scoring.score_company({**base, "manual": {"recurring_quality": 0, "owner_openness": 1}}, {}, date(2026, 11, 4))
    assert low["score"] < a["score"] < high["score"] or a["score"] == high["score"]
    assert low["score"] < a["score"]
    # unscored personal criteria do not change the coverage figure
    assert a["coverage"] == high["coverage"]


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


def test_ownership_classification_edge_cases(c, tmp_path):
    """Family holding companies, minority employee trusts and foreign parents."""
    import json as _json

    from acquireos.importers import companies, psc

    companies.run(c, FIX / "ranked_sample.csv")
    corp = "corporate-entity-person-with-significant-control"
    ind = "individual-person-with-significant-control"
    recs = [
        # 01000001: owned by "J SMITH INVESTMENTS LIMITED" (UK, number as free text), itself owned by John Smith
        ("01000001", {"kind": corp, "name": "J SMITH INVESTMENTS LIMITED", "natures_of_control": ["ownership-of-shares-75-to-100-percent"],
                      "identification": {"registration_number": "Company No. 09999991", "country_registered": "England"}}),
        ("09999991", {"kind": ind, "name": "Mr John Smith", "date_of_birth": {"year": 1960, "month": 5},
                      "natures_of_control": ["ownership-of-shares-75-to-100-percent"]}),
        # 01000002: founder 60%, employee benefit trust 25-50%
        ("01000002", {"kind": ind, "name": "Ms Jane Founder", "date_of_birth": {"year": 1958, "month": 2},
                      "natures_of_control": ["ownership-of-shares-50-to-75-percent"]}),
        ("01000002", {"kind": "legal-person-person-with-significant-control", "name": "ACME EMPLOYEE BENEFIT TRUST",
                      "natures_of_control": ["ownership-of-shares-25-to-50-percent"]}),
        # 01000004: Irish parent whose number would pad to an unrelated UK company (01000003)
        ("01000004", {"kind": corp, "name": "EMERALD HOLDINGS DAC", "natures_of_control": ["ownership-of-shares-75-to-100-percent"],
                      "identification": {"registration_number": "1000003", "country_registered": "Ireland"}}),
    ]
    f = tmp_path / "psc.jsonl"
    f.write_text("\n".join(_json.dumps({"company_number": n_, "data": d}) for n_, d in recs))
    psc.run(c, [f])
    o = {r["company_number"]: r for r in c.execute("select * from company_ownership")}
    assert o["01000001"]["ownership_type"] == "owner_held" and o["01000001"]["oldest_birth_year"] == 1960
    assert "via_holdco" in o["01000001"]["flags"]
    assert o["01000002"]["ownership_type"] == "owner_held" and "ebt" in o["01000002"]["flags"]
    # A one-company Irish parent (a DAC, its private limited company) whose owners aren't traced:
    # not assumed to be a group (could be a founder's vehicle); flagged, not excluded.
    assert o["01000004"]["ownership_type"] == "unknown"
    assert {"foreign_parent", "holdco_unresolved"} <= set(o["01000004"]["flags"])
    # the Irish number is not turned into a UK one, so no link to 01000003
    assert not c.execute("select 1 from company_link where a = '01000004' and b = '01000003'").fetchone()
    assert c.execute("select registration_number from person where name = 'EMERALD HOLDINGS DAC'").fetchone()["registration_number"] is None


def test_estimates_follow_the_latest_accounts(loaded):
    from acquireos.importers.companies import refresh_estimates

    c = loaded
    num = "01000006"
    c.execute("delete from financial_period where company_number = %s", (num,))
    c.execute("delete from estimate where company_number = %s", (num,))
    c.execute("insert into financial_period (company_number, period_end, employees, turnover) values (%s, '2019-12-31', 5, 3000000)", (num,))
    refresh_estimates(c)
    e = c.execute("select * from estimate where company_number = %s", (num,)).fetchone()
    assert e["basis"] == "filed" and float(e["revenue_low"]) == 3e6 and "31 Dec 2019" in e["method"]
    # newer accounts without turnover: the old turnover is not kept as "filed"
    c.execute("insert into financial_period (company_number, period_end, employees) values (%s, '2025-12-31', 40)", (num,))
    refresh_estimates(c)
    e = c.execute("select * from estimate where company_number = %s", (num,)).fetchone()
    assert e["basis"] == "estimated" and "40" in e["method"] and float(e["revenue_low"]) > 1e6
    # staff change: the estimate moves with it
    c.execute("update financial_period set employees = 12 where company_number = %s and period_end = '2025-12-31'", (num,))
    refresh_estimates(c)
    e2 = c.execute("select * from estimate where company_number = %s", (num,)).fetchone()
    assert float(e2["revenue_low"]) < float(e["revenue_low"])


def test_ownership_rebuild_rewrites_only_changes(loaded):
    from acquireos import ownership

    c = loaded
    before = {r["company_number"]: r["updated_at"] for r in c.execute("select company_number, updated_at from company_ownership")}
    assert before
    import time
    time.sleep(0.05)
    ownership.rebuild(c)
    after = {r["company_number"]: r["updated_at"] for r in c.execute("select company_number, updated_at from company_ownership")}
    assert after == before  # nothing changed, so nothing was rewritten


def test_rescore_is_incremental(loaded):
    c = loaded
    bb = scoring.active_buy_box(c)
    before = {r["company_number"]: r["computed_at"] for r in c.execute("select company_number, computed_at from score")}
    assert before
    import time
    time.sleep(0.05)
    scoring.rescore(c)  # nothing changed: nothing recomputed (parents are always redone; they are few)
    after = {r["company_number"]: r["computed_at"] for r in c.execute("select company_number, computed_at from score")}
    parents = {"01000003"}
    assert {k: v for k, v in after.items() if k not in parents} == {k: v for k, v in before.items() if k not in parents}
    # one company's facts change: only it is rescored
    c.execute("update company_latest set employees = 55 where company_number = '01000001'")
    scoring.rescore(c)
    after2 = {r["company_number"]: r["computed_at"] for r in c.execute("select company_number, computed_at from score")}
    assert after2["01000001"] > before["01000001"]
    assert all(after2[k] == before[k] for k in before if k not in parents | {"01000001"})
    assert "55 staff" in json.dumps(c.execute("select reasons from score where company_number = '01000001'").fetchone()["reasons"])
    # a changed criterion rescores everything
    crit = bb["criteria"]; crit["staff"]["weight"] = 99
    c.execute("update buy_box set criteria = %s where id = %s", (json.dumps(crit), bb["id"]))
    scoring.rescore(c)
    after3 = {r["company_number"]: r["computed_at"] for r in c.execute("select company_number, computed_at from score")}
    assert all(after3[k] > after2[k] for k in after2)


def test_excluded_regions_are_left_out():
    crit = scoring.merged({"exclude": {"regions": ["England", "Scotland"]}})
    wales = scoring.score_company({"name": "X", "region": "Wales"}, crit, date(2026, 11, 4))
    england = scoring.score_company({"name": "Y", "region": "England"}, crit, date(2026, 11, 4))
    assert not wales["excluded"]
    assert england["excluded"] and "England" in england["exclusion"]


def test_old_regions_only_setting_becomes_an_exclusion(c):
    import json as _j

    c.execute("insert into buy_box (user_id, name, criteria, is_active) values (1, 'Old', %s, false)",
              (_j.dumps({"regions": ["England", "Scotland"], "exclude": {"keywords": ["van"]}}),))
    sql = (Path(scoring.__file__).parent / "migrations" / "019_exclude_regions.sql").read_text()
    c.execute(sql)
    crit = c.execute("select criteria from buy_box where name = 'Old'").fetchone()["criteria"]
    assert "regions" not in crit and crit["exclude"]["regions"] == ["England", "Scotland"]
    assert crit["exclude"]["keywords"] == ["van"]


def test_holding_company_patterns_issue_23(c, tmp_path):
    """A company whose only shareholder is a holding company: owner-held when the
    holding company's owners are people (traced through owner records, an overseas
    entity's beneficial owners, or its shareholder list); unknown, not 'group',
    when they can't be traced; group-owned only for a real group."""
    import json as _json

    from acquireos import ownership
    from acquireos.importers import companies, psc

    companies.run(c, FIX / "ranked_sample.csv")
    for num, name in [("OE012345", "MELYN LIMITED"), ("07273556", "MELYN LTD"), ("09111111", "B2B IT SERVICES HOLDINGS LIMITED"),
                      ("09222222", "ACQUIS HOLDING LIMITED"), ("09333333", "BIGCO GROUP LIMITED"),
                      ("09444444", "SUB A LIMITED"), ("09555555", "SUB B LIMITED"), ("09666666", "SUB C LIMITED"),
                      ("09777777", "FAMILY HOLDINGS LIMITED")]:
        c.execute("insert into company (company_number, name, status) values (%s, %s, 'Active') on conflict do nothing", (num, name))
    corp = "corporate-entity-person-with-significant-control"
    ind = "individual-person-with-significant-control"
    big = ["ownership-of-shares-75-to-100-percent"]
    recs = [
        # BCC IT (issue 24): owned by "Melyn Ltd", UK number written without its leading zero; Melyn Ltd is owned by
        # Hywel (born 1975). An unrelated overseas entity "Melyn Limited" (OE012345) with an owner born 1948 must not be used.
        ("01000001", {"kind": corp, "name": "MELYN LTD", "natures_of_control": big,
                      "identification": {"registration_number": "7273556", "country_registered": "Wales"}}),
        ("07273556", {"kind": ind, "name": "Mr Hywel Example", "date_of_birth": {"year": 1975, "month": 1}, "natures_of_control": big}),
        ("OE012345", {"kind": "individual-beneficial-owner", "name": "Mr Dafydd Example", "date_of_birth": {"year": 1948, "month": 3},
                      "natures_of_control": big}),
        # An overseas parent with its own registry number and no UK owner records: not linked by name to the
        # overseas entity of the same name; unknown and flagged, not excluded as a group.
        ("01000005", {"kind": corp, "name": "Melyn Limited", "natures_of_control": big,
                      "identification": {"registration_number": "012345C", "country_registered": "Isle of Man", "legal_form": "Limited"}}),
        # B2B IT Services: its holding company has no owner records, but its shareholder list names a person who is a director.
        ("01000002", {"kind": corp, "name": "B2B IT SERVICES HOLDINGS LIMITED", "natures_of_control": big,
                      "identification": {"registration_number": "9111111", "country_registered": "England"}}),
        # Acquis: holding company whose owners can't be traced at all: unknown, not a group.
        ("01000003", {"kind": corp, "name": "ACQUIS HOLDING LIMITED", "natures_of_control": big,
                      "identification": {"registration_number": "09222222", "country_registered": "England"}}),
        # A real group: BIGCO GROUP owns three other companies too, owners untraced: group-owned.
        ("01000004", {"kind": corp, "name": "BIGCO GROUP LIMITED", "natures_of_control": big,
                      "identification": {"registration_number": "09333333", "country_registered": "England"}}),
        ("09444444", {"kind": corp, "name": "BIGCO GROUP LIMITED", "natures_of_control": big,
                      "identification": {"registration_number": "09333333", "country_registered": "England"}}),
        ("09555555", {"kind": corp, "name": "BIGCO GROUP LIMITED", "natures_of_control": big,
                      "identification": {"registration_number": "09333333", "country_registered": "England"}}),
        ("09666666", {"kind": corp, "name": "BIGCO GROUP LIMITED", "natures_of_control": big,
                      "identification": {"registration_number": "09333333", "country_registered": "England"}}),
        # A messy number ("Reg no 9777777", no leading zero) still leads to the family holding company and its owner.
        ("01000006", {"kind": corp, "name": "FAMILY HOLDINGS LIMITED", "natures_of_control": big,
                      "identification": {"registration_number": "Reg no 9777777", "country_registered": "Wales"}}),
        ("09777777", {"kind": ind, "name": "Mrs Ann Family", "date_of_birth": {"year": 1955, "month": 1}, "natures_of_control": big}),
    ]
    f = tmp_path / "psc.jsonl"
    f.write_text("\n".join(_json.dumps({"company_number": n_, "data": d}) for n_, d in recs))
    psc.run(c, [f])
    c.execute("""insert into shareholder (company_number, name, shares, share_class, as_at) values
                 ('09111111', 'Gareth Jones', 100, 'Ordinary', '2025-06-01'), ('09111111', 'Siân Jones', 100, 'Ordinary', '2025-06-01')""")
    c.execute("""insert into officer (company_number, officer_key, name, role, birth_year) values
                 ('09111111', 'k1', 'JONES, Gareth Wyn', 'director', 1965)""")
    ownership.rebuild(c, links=False)
    o = {r["company_number"]: r for r in c.execute("select * from company_ownership")}
    assert o["01000001"]["ownership_type"] == "owner_held" and o["01000001"]["oldest_birth_year"] == 1975  # BCC IT, by number
    assert o["01000005"]["ownership_type"] == "unknown" and o["01000005"]["oldest_birth_year"] is None     # no name match
    assert {"foreign_parent", "holdco_unresolved"} <= set(o["01000005"]["flags"])
    assert o["01000002"]["ownership_type"] == "owner_held" and o["01000002"]["owner_count"] == 2           # B2B
    assert o["01000002"]["oldest_birth_year"] == 1965 and "owners_from_shareholders" in o["01000002"]["flags"]
    assert o["01000003"]["ownership_type"] == "unknown" and "holdco_unresolved" in o["01000003"]["flags"]  # Acquis
    assert "ACQUIS HOLDING LIMITED" in o["01000003"]["explanation"]
    assert o["01000004"]["ownership_type"] == "group_owned"                                               # real group
    assert o["01000006"]["ownership_type"] == "owner_held" and o["01000006"]["oldest_birth_year"] == 1955


def test_unresolved_holdcos_are_listed_for_look_up(c, tmp_path):
    import json as _json

    from acquireos import gaps, ownership, scoring
    from acquireos.importers import companies, psc

    companies.run(c, FIX / "ranked_sample.csv")
    c.execute("insert into company (company_number, name, status) values ('09222222', 'ACQUIS HOLDING LIMITED', 'Active')")
    rec = {"kind": "corporate-entity-person-with-significant-control", "name": "ACQUIS HOLDING LIMITED",
           "natures_of_control": ["ownership-of-shares-75-to-100-percent"],
           "identification": {"registration_number": "09222222", "country_registered": "England"}}
    f = tmp_path / "psc.jsonl"
    f.write_text(_json.dumps({"company_number": "01000003", "data": rec}))
    psc.run(c, [f])
    ownership.rebuild(c, links=False)
    c.execute("insert into user_company (user_id, company_number, status) values (1, '01000003', 'researching') on conflict (user_id, company_number) do update set status = 'researching'")
    rows = gaps.holdcos_to_look_up(c)
    assert [(r["holdco"], r["target"]) for r in rows] == [("09222222", "01000003")]
