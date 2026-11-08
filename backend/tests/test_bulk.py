import zipfile
from datetime import date

from acquireos import fetch
from acquireos.importers import accounts, companies

from .conftest import FIX

ACC = FIX / "Prod224_0001_01000001_20270331.html"


def test_parse_ixbrl():
    data = accounts.parse(ACC.read_text())
    cy, py = data[date(2027, 3, 31)], data[date(2026, 3, 31)]
    assert cy["employees"] == 41 and py["employees"] == 34
    assert cy["turnover"] == 4_120_000  # scale="3"
    assert py["operating_profit"] == -20_000  # sign="-"
    assert cy["cash"] == 1_020_000  # nested span
    assert py["debtors"] == 0  # zerodash
    assert cy["net_assets"] == 2_100_000  # preferred over Equity, dimensioned context ignored


def test_parse_name():
    assert accounts.parse_name("Prod224_0001_01000001_20270331.html") == ("01000001", date(2027, 3, 31))
    assert accounts.parse_name("x/Prod223_9_SC123456_20251231.xml") == ("SC123456", date(2025, 12, 31))
    assert accounts.parse_name("readme.txt") is None


def test_accounts_import_from_nested_zip(loaded, tmp_path):
    c = loaded
    inner = tmp_path / "Accounts_Bulk_Data-2027-04-02.zip"
    with zipfile.ZipFile(inner, "w") as z:
        z.write(ACC, ACC.name)
        z.writestr("Prod224_0001_09999999_20270331.html", "<html>not ours</html>")
    outer = tmp_path / "Accounts_Monthly_Data-April2027.zip"
    with zipfile.ZipFile(outer, "w") as z:
        z.write(inner, inner.name)
    r = accounts.run(c, [outer])
    assert r["files_seen"] == 2 and r["companies_matched"] == 1
    rows = c.execute("select * from financial_period where company_number='01000001' order by period_end").fetchall()
    ends = [x["period_end"] for x in rows]
    assert date(2027, 3, 31) in ends and date(2026, 3, 31) in ends
    real = {x["period_end"]: x for x in rows if not x["period_inferred"]}
    assert real[date(2027, 3, 31)]["employees"] == 41 and real[date(2026, 3, 31)]["employees"] == 34
    # the ranked file's inferred 2025 row stays: no filed accounts cover it yet
    assert [x["period_end"] for x in rows if x["period_inferred"]] == [date(2025, 3, 31)]
    est = c.execute("select * from estimate where company_number='01000001'").fetchone()
    assert est["basis"] == "filed" and float(est["revenue_low"]) == 4_120_000
    kinds = {x["kind"] for x in c.execute("select kind from company_change where company_number='01000001'")}
    assert {"accounts", "staff"} <= kinds
    # re-importing the same file changes nothing
    n = c.execute("select count(*) as n from company_change").fetchone()["n"]
    accounts.run(c, [outer])
    assert c.execute("select count(*) as n from company_change").fetchone()["n"] == n


def test_universe_filter():
    t = companies.universe_filter({"universe": {"sic_prefixes": ["620"], "keyword_sic_prefixes": ["70229"],
                                                "name_keywords": ["software"], "postcode_areas": ["CF", "SA"],
                                                "min_years": 3}})
    base = {"status": "active", "postcode": "CF10 1AA", "inc": date(2010, 1, 1), "sic": ["62020"], "name": "X LTD"}
    assert t(base)
    assert not t({**base, "postcode": "LS1 1AA"})
    assert not t({**base, "status": "dissolved"})
    assert not t({**base, "inc": date.today()})
    assert not t({**base, "sic": ["70229"]})
    assert t({**base, "sic": ["70229"], "name": "ACME SOFTWARE LTD"})
    assert not t({**base, "sic": ["47110"], "name": "ACME SOFTWARE LTD"})


def test_universe_and_full_register(loaded, monkeypatch):
    c = loaded
    monkeypatch.setattr(companies, "FULL_REGISTER_MIN_ROWS", 1)
    r = companies.run(c, FIX / "ch_bulk_update.csv", universe=True, full_register=True)
    # 01234567 (SIC 62012, Leeds, 2010) matches the default universe and is added
    added = c.execute("select region from company where company_number='01234567'").fetchone()
    assert added and added["region"] == "England"
    # companies in the list but missing from the "register" are flagged, not deleted
    gone = c.execute("select status from company where company_number='01000003'").fetchone()
    assert gone["status"] == "removed from register"
    assert any("no longer on the live register" in m for m in r["messages"])


def test_link_discovery():
    pages = {
        "en_output.html": '<a href="BasicCompanyDataAsOneFile-2026-10-01.zip">x</a> <a href="BasicCompanyDataAsOneFile-2026-11-01.zip">y</a>'
                          '<a href="BasicCompanyData-2026-11-01-part1_7.zip">part</a>',
        "en_monthlyaccountsdata.html": '<a href="Accounts_Monthly_Data-October2026.zip">a</a><a href="Accounts_Monthly_Data-September2026.zip">b</a>',
        "historicmonthlyaccountsdata.html": '<a href="archive/Accounts_Monthly_Data-December2025.zip">c</a>',
        "en_pscdata.html": '<a href="persons-with-significant-control-snapshot-2026-11-03_1of2.zip">1</a>'
                           '<a href="persons-with-significant-control-snapshot-2026-11-03_2of2.zip">2</a>',
    }
    comp = fetch.links("company", pages)
    assert comp[0][1].endswith("BasicCompanyDataAsOneFile-2026-11-01.zip") and len(comp) == 2
    acc = fetch.links("accounts", pages)
    assert [k for k, _ in acc] == ["2026-10", "2026-09", "2025-12"]
    assert acc[2][1].endswith("archive/Accounts_Monthly_Data-December2025.zip")
    psc = fetch.links("psc", pages)
    assert len(psc) == 2


def test_download_dir_falls_back_when_not_writable(tmp_path):
    import os

    locked = tmp_path / "locked"
    locked.mkdir()
    os.chmod(locked, 0o500)
    try:
        got = fetch._writable_dir(locked / "companies-house")
        if os.geteuid() == 0:  # root ignores permissions; nothing to fall back from
            assert got == locked / "companies-house"
        else:
            assert got.name == "acquireos-downloads"
    finally:
        os.chmod(locked, 0o700)
    ok = tmp_path / "ok"
    assert fetch._writable_dir(ok) == ok


def test_accounts_debt_working_capital_and_activity():
    """Creditors and bank loans tagged once with a within / after one year
    breakdown, depreciation shown as a negative, and the principal activity text."""
    from datetime import date

    from acquireos.importers import accounts
    ctx = lambda cid, d, mem="": (f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier scheme="x">01</xbrli:identifier>'
        + (f'<xbrli:segment><xbrldi:explicitMember dimension="core:MaturitiesOrExpirationPeriodsDimension">core:{mem}</xbrldi:explicitMember></xbrli:segment>' if mem else "")
        + f'</xbrli:entity><xbrli:period><xbrli:instant>{d}</xbrli:instant></xbrli:period></xbrli:context>')
    f = lambda n, c, v, extra="": f'<ix:nonFraction name="core:{n}" contextRef="{c}" unitRef="GBP" decimals="0"{extra}>{v}</ix:nonFraction>'
    doc = ("<html><body>" + ctx("i", "2025-03-31") + ctx("w", "2025-03-31", "WithinOneYear") + ctx("a", "2025-03-31", "AfterOneYear")
           + ctx("x", "2025-03-31", "SomethingElse")
           + f("NetAssetsLiabilities", "i", "500,000") + f("Creditors", "w", "120,000") + f("Creditors", "a", "80,000")
           + f("Creditors", "x", "999") + f("BankBorrowings", "w", "10,000") + f("BankBorrowings", "a", "40,000")
           + f("DepreciationExpensePropertyPlantEquipment", "i", "(15,000)", ' sign="-"') + f("Stocks", "i", "30,000")
           + f("RetainedEarningsAccumulatedLosses", "i", "(20,000)", ' sign="-"')
           + '<ix:nonNumeric name="core:DescriptionPrincipalActivities" contextRef="i">The provision of <b>IT managed services</b>.</ix:nonNumeric>'
           + "</body></html>")
    r = accounts.parse(doc)[date(2025, 3, 31)]
    assert r["creditors_within"] == 120_000 and r["creditors_after"] == 80_000 and r["bank_loans"] == 50_000
    assert r["depreciation"] == 15_000 and r["stock"] == 30_000 and r["retained_earnings"] == -20_000
    assert r["principal_activity"] == "The provision of IT managed services." and r["net_assets"] == 500_000

