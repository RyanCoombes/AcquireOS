"""Whole-register loading: snapshot order, filing order, back-fill and scope."""
import csv
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
    # SIC 70100 holding company: outside the universe, so no score row is stored
    assert "01000003" not in s
    assert not s["01000001"]["excluded"]
    # ...unless you are working on it: then it is stored, marked outside the universe
    loaded.execute("insert into user_company (user_id, company_number, status) values (1, '01000003', 'watching')")
    scoring.rescore(loaded)
    row = loaded.execute("select * from score where company_number = '01000003'").fetchone()
    assert row["excluded"] and "universe" in row["exclusion"]


def test_fetch_accounts_oldest_first(loaded, monkeypatch, tmp_path):
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
    assert calls == [("Accounts_Monthly_Data-August2026.zip", False),
                     ("Accounts_Monthly_Data-September2026.zip", False),
                     ("Accounts_Monthly_Data-October2026.zip", True)]


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
