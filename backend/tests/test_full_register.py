"""Whole-register loading: snapshot order, filing order, back-fill and scope."""
import csv
import json
import zipfile
from datetime import date
from pathlib import Path

from acquireos import fetch, scoring
from acquireos.importers import accounts, register

from .conftest import FIX

BULK = FIX / "ch_bulk_update.csv"


def _snapshot(tmp_path, name, edits):
    rows = list(csv.DictReader(BULK.open(encoding="utf-8-sig")))
    for r in rows:
        r.update(edits.get(r[" CompanyNumber"], {}))
    out = tmp_path / name
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(rows)
    return out


def test_register_bulk_load_and_snapshot_order(loaded, tmp_path):
    c = loaded
    assert register.is_register(list(csv.DictReader(BULK.open(encoding="utf-8-sig")).fieldnames))
    r = register.load(c, BULK, register_date=date(2026, 11, 1), full=False)
    assert r["rows_in"] == 4
    added = c.execute("select * from company where company_number = '01234567'").fetchone()
    assert added and added["region"] == "England" and added["sic_codes"] == ["62012"]
    ch = {(x["company_number"], x["kind"]) for x in c.execute("select * from company_change")}
    assert ("01000006", "status") in ch and ("01000002", "name") in ch
    assert ("01234567", "new_company") not in ch  # first register load: no flood of "added"
    assert c.execute("select description from sic_code where code = '43210'").fetchone()["description"] == "Electrical installation"
    # an OLDER snapshot loaded afterwards must not roll the company back
    old = _snapshot(tmp_path, "BasicCompanyData-2026-10-01.csv", {"01000006": {"CompanyStatus": "Active"},
                                                                  "01000002": {"CompanyName": "OLD NAME LTD"}})
    n_before = c.execute("select count(*) as n from company_change").fetchone()["n"]
    register.load(c, old, full=False)
    co = {x["company_number"]: x for x in c.execute("select * from company")}
    assert co["01000006"]["status"] == "dissolved" and co["01000002"]["name"] == "SAMPLE DATA GROUP LTD"
    assert c.execute("select count(*) as n from company_change").fetchone()["n"] == n_before
    # a NEWER snapshot is applied, and now new companies are recorded
    newer = _snapshot(tmp_path, "BasicCompanyData-2026-12-01.csv", {"01000002": {"CompanyName": "SAMPLE DATA 2027 LTD"}})
    register.load(c, newer, full=False)
    assert c.execute("select name from company where company_number='01000002'").fetchone()["name"] == "SAMPLE DATA 2027 LTD"


def _filing(path: Path, num: str, balance: date, periods: dict):
    ctx, facts = [], []
    for i, (end, staff) in enumerate(periods.items()):
        ctx.append(f'<xbrli:context id="d{i}"><xbrli:entity><xbrli:identifier>{num}</xbrli:identifier></xbrli:entity>'
                   f'<xbrli:period><xbrli:startDate>{end.replace(year=end.year - 1)}</xbrli:startDate>'
                   f'<xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>')
        facts.append(f'<ix:nonFraction name="core:AverageNumberEmployeesDuringPeriod" contextRef="d{i}">{staff}</ix:nonFraction>')
    name = f"Prod224_0001_{num}_{balance:%Y%m%d}.html"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(name, f"<html><ix:header>{''.join(ctx)}</ix:header>{''.join(facts)}</html>")
    return path


def test_older_filing_never_overwrites_newer(loaded, tmp_path):
    c = loaded
    newer = _filing(tmp_path / "new.zip", "01000001", date(2028, 3, 31), {date(2028, 3, 31): 50, date(2027, 3, 31): 44})
    older = _filing(tmp_path / "old.zip", "01000001", date(2027, 3, 31), {date(2027, 3, 31): 40, date(2026, 3, 31): 34})
    accounts.run(c, [newer], workers=1)
    accounts.run(c, [older], workers=1)  # loaded out of order
    staff = {x["period_end"]: x["employees"] for x in c.execute(
        "select period_end, employees from financial_period where company_number='01000001' and not period_inferred")}
    assert staff[date(2027, 3, 31)] == 44  # restated figure from the newer filing kept
    assert staff[date(2028, 3, 31)] == 50 and staff[date(2026, 3, 31)] == 34


def test_backfill_records_no_changes(loaded, tmp_path):
    c = loaded
    f = _filing(tmp_path / "x.zip", "01000001", date(2028, 3, 31), {date(2028, 3, 31): 60})
    accounts.run(c, [f], workers=1, record_changes=False)
    assert c.execute("select count(*) as n from company_change where kind in ('accounts','staff')").fetchone()["n"] == 0
    g = _filing(tmp_path / "y.zip", "01000001", date(2029, 3, 31), {date(2029, 3, 31): 70})
    accounts.run(c, [g], workers=1, record_changes=True)
    kinds = {x["kind"] for x in c.execute("select kind from company_change")}
    assert {"accounts", "staff"} <= kinds


def test_parallel_parse_matches(loaded, tmp_path):
    c = loaded
    f = _filing(tmp_path / "p.zip", "01000002", date(2028, 12, 31), {date(2028, 12, 31): 25})
    r = accounts.run(c, [f], workers=2)
    assert r["companies_matched"] == 1
    assert c.execute("select employees from financial_period where company_number='01000002' and period_end='2028-12-31'").fetchone()["employees"] == 25


def test_universe_scope_excludes(loaded):
    s = {x["company_number"]: x for x in loaded.execute("select * from score")}
    assert not s["01000001"]["excluded"]
    # SIC 70100 holding company that owns 01000002 (in the universe): in scope as its parent
    hold = s["01000003"]
    assert not hold["excluded"]
    assert "parent" in json.dumps(hold["reasons"], default=str).lower()
    # With parents switched off it falls outside the universe and no score row is stored
    bb = scoring.active_buy_box(loaded)
    crit = bb["criteria"]
    crit["universe"]["include_parents"] = False
    loaded.execute("update buy_box set criteria = %s where id = %s", (json.dumps(crit), bb["id"]))
    scoring.rescore(loaded)
    assert not loaded.execute("select 1 from score where company_number = '01000003'").fetchone()
    # ...unless you are working on it: then it is stored, marked outside the universe
    loaded.execute("insert into user_company (user_id, company_number, status) values (1, '01000003', 'watching')")
    scoring.rescore(loaded)
    row = loaded.execute("select * from score where company_number = '01000003'").fetchone()
    assert row["excluded"] and "universe" in row["exclusion"]


def test_fetch_accounts_newest_first(loaded, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(fetch, "links", lambda kind, pages=None: [
        ("2026-10", "https://x/Accounts_Monthly_Data-October2026.zip"),
        ("2026-09", "https://x/Accounts_Monthly_Data-September2026.zip"),
        ("2026-08", "https://x/Accounts_Monthly_Data-August2026.zip")])
    monkeypatch.setattr(fetch, "download", lambda url, *a, **k: tmp_path / url.rsplit("/", 1)[-1])
    monkeypatch.setattr(accounts, "run", lambda conn, paths, record_changes=True, progress=None, **k:
                        calls.append((paths[0].name, record_changes)) or
                        {"companies_matched": 0, "changes": 0, "files_seen": 0, "periods": 0})
    fetch.fetch_accounts(loaded, months=3, keep=True)
    assert calls == [("Accounts_Monthly_Data-October2026.zip", True),
                     ("Accounts_Monthly_Data-September2026.zip", False),
                     ("Accounts_Monthly_Data-August2026.zip", False)]


def test_job_progress_and_cancel(loaded):
    loaded.commit()
    from acquireos import jobs

    j = jobs.Job("test", ["Company register", "Owners (PSC)", "Scoring"])
    j.stage("Company register")
    j.progress(0.5, "halfway")
    j._write(force=True)
    row = loaded.execute("select * from job where id = %s", (j.id,)).fetchone()
    assert row["status"] == "running" and row["stage"] == "Company register" and float(row["pct"]) == 16.7
    j.stage("Accounts: October 2026")  # an unplanned stage is added
    assert [s["name"] for s in j.stages][-1] == "Accounts: October 2026"
    loaded.execute("update job set cancel_requested = true where id = %s", (j.id,))
    loaded.commit()
    import pytest

    with pytest.raises(jobs.Cancelled):
        j.check_cancel()
    j.finish(status="cancelled", error="Stopped by you")
    row = loaded.execute("select * from job where id = %s", (j.id,)).fetchone()
    assert row["status"] == "cancelled" and row["finished_at"] is not None
    assert jobs.current(loaded)["id"] == j.id


def test_already_loaded_snapshots_are_skipped(loaded, monkeypatch):
    c = loaded
    monkeypatch.setattr(fetch, "links", lambda kind, pages=None: {
        "company": [("2026-11-01x", "https://x/BasicCompanyDataAsOneFile-2026-11-01.zip")],
        "psc": [("2026-11-03p", "https://x/persons-with-significant-control-snapshot-2026-11-03.zip")]}[kind])
    monkeypatch.setattr(fetch, "download", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not download")))
    # read by an older loader (fewer fields): not skipped, it is read again
    c.execute("insert into import_run (kind, filename, finished_at) values ('register', 'BasicCompanyDataAsOneFile-2026-11-01.zip', now())")
    import pytest
    with pytest.raises(AssertionError, match="should not download"):
        fetch.fetch_company_data(c)
    c.execute("insert into import_run (kind, filename, finished_at, loader_version) values ('register', 'BasicCompanyDataAsOneFile-2026-11-01.zip', now(), %s)",
              (register.LOADER_VERSION,))
    c.execute("insert into import_run (kind, filename, finished_at) values ('psc', 'persons-with-significant-control-snapshot-2026-11-03.zip', now())")
    assert fetch.fetch_company_data(c) == {"skipped": "BasicCompanyDataAsOneFile-2026-11-01.zip"}
    assert "skipped" in fetch.fetch_psc(c)


def test_fast_register_path_matches_careful_reader(c):
    """The streamed SQL path is used, and gives the same rows as the Python reader."""
    from acquireos.importers.tables import open_table

    msgs = []
    register.load(c, BULK, register_date=date(2026, 11, 1), full=False, progress=lambda m, f=None: msgs.append(m))
    assert not any("Fast load failed" in m for m in msgs), msgs
    fast = {r["company_number"]: r for r in c.execute(
        "select company_number, name, status, sic_codes, registered_address, postcode, incorporation_date, "
        "dissolution_date, last_accounts_date, company_type, accounts_category, accounts_next_due, confirmation_next_due, "
        "charges_total, charges_outstanding, charges_part_satisfied, charges_satisfied, previous_names from company")}
    c.execute("delete from company_change; delete from company")
    headers, rows = open_table(BULK)
    idx = {register.norm_header(h): h for h in headers}
    col = {k: next((idx[a] for a in al if a in idx), None) for k, al in register.COLS.items()}
    c.execute("drop table if exists reg_stage")
    register._stage_python(c, rows, col, 10, None)
    slow = {r["num"]: r for r in c.execute("select * from reg_stage")}
    assert set(fast) == set(slow)
    for num, f in fast.items():
        s = slow[num]
        assert (f["name"], f["status"], f["sic_codes"], f["registered_address"], f["postcode"]) == \
               (s["name"], s["status"], s["sic"], s["addr"], s["pc"]), num
        assert (f["incorporation_date"], f["dissolution_date"], f["last_accounts_date"]) == (s["inc"], s["dissolved"], s["last_acc"])
        assert (f["accounts_category"], f["accounts_next_due"], f["confirmation_next_due"], f["charges_total"],
                f["charges_outstanding"], f["charges_part_satisfied"], f["charges_satisfied"], f["previous_names"]) == \
               (s["acc_cat"], s["acc_due"], s["cs_due"], s["mort_total"], s["mort_out"], s["mort_part"], s["mort_sat"],
                s["prev_names"]), num
    e = fast["01000001"]
    assert e["accounts_category"] == "small" and str(e["accounts_next_due"]) == "2027-12-31"
    assert str(e["confirmation_next_due"]) == "2027-03-14"
    assert (e["charges_total"], e["charges_outstanding"], e["charges_satisfied"]) == (3, 1, 2)
    assert e["previous_names"] == [{"name": "EXAMPLE ELECTRICAL LTD", "until": "2010-06-05"},
                                   {"name": "EXAMPLE HOLDINGS 2001 LTD", "until": "2001-02-01"}]


def test_failed_load_keeps_the_download_for_a_rerun(loaded, monkeypatch, tmp_path):
    f = tmp_path / "Accounts_Monthly_Data-October2026.zip"
    f.write_bytes(b"x")
    monkeypatch.setattr(fetch, "links", lambda kind, pages=None: [("2026-10", "https://x/" + f.name)])
    monkeypatch.setattr(fetch, "download", lambda url, *a, **k: f)

    def boom(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(accounts, "run", boom)
    import pytest
    with pytest.raises(RuntimeError):
        fetch.fetch_accounts(loaded, months=1)
    assert f.exists()  # not deleted, so the next run reuses it
    loaded.rollback()
    assert fetch.accounts_plan(loaded, 1)[0][2] is False  # and the month is not marked as loaded


def test_accounts_extra_figures_are_read():
    doc = (b'<html><ix:header><xbrli:context id="ci"><xbrli:period><xbrli:instant>2026-03-31</xbrli:instant></xbrli:period></xbrli:context>'
           b'<xbrli:context id="cy"><xbrli:period><xbrli:startDate>2025-04-01</xbrli:startDate><xbrli:endDate>2026-03-31</xbrli:endDate></xbrli:period></xbrli:context>'
           b'<xbrli:context id="cw"><xbrli:entity><xbrli:segment>within one year</xbrli:segment></xbrli:entity><xbrli:period><xbrli:instant>2026-03-31</xbrli:instant></xbrli:period></xbrli:context>'
           b'</ix:header>'
           b'<ix:nonFraction name="core:FixedAssets" contextRef="ci">120,000</ix:nonFraction>'
           b'<ix:nonFraction name="core:IntangibleAssets" contextRef="ci">20,000</ix:nonFraction>'
           b'<ix:nonFraction name="core:CurrentAssets" contextRef="ci">400,000</ix:nonFraction>'
           b'<ix:nonFraction name="core:NetCurrentAssetsLiabilities" contextRef="ci">150,000</ix:nonFraction>'
           b'<ix:nonFraction name="core:TotalAssetsLessCurrentLiabilities" contextRef="ci">270,000</ix:nonFraction>'
           b'<ix:nonFraction name="core:Creditors" contextRef="cw">250,000</ix:nonFraction>'
           b'<ix:nonFraction name="core:GrossProfitLoss" contextRef="cy">900,000</ix:nonFraction>'
           b'<ix:nonFraction name="core:DirectorRemuneration" contextRef="cy">85,000</ix:nonFraction>'
           b'<ix:nonFraction name="core:StaffCostsEmployeeBenefitsExpense" contextRef="cy">1,200,000</ix:nonFraction></html>')
    v = accounts.parse(doc)[date(2026, 3, 31)]
    assert v["fixed_assets"] == 120000 and v["intangible_assets"] == 20000 and v["current_assets"] == 400000
    assert v["net_current_assets"] == 150000 and v["total_assets_less_cl"] == 270000
    assert v["gross_profit"] == 900000 and v["director_pay"] == 85000 and v["staff_costs"] == 1200000
