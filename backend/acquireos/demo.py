"""Generate a fictional demo dataset (for screenshots, trials and testing).

Every company and person here is invented. Company numbers start with 9
to keep them away from real-looking ranges.

    acquireos-demo /tmp/demo   # writes companies.csv, psc.jsonl, notes.csv
"""
from __future__ import annotations

import csv
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

WORDS_A = ["Northgate", "Tidewell", "Brightfield", "Harbourline", "Kestrel", "Ashcombe", "Copperleaf", "Marlow",
           "Fernhill", "Stonebridge", "Larkspur", "Redwater", "Oakmere", "Silverton", "Bramble", "Westcliff",
           "Hazelwood", "Greystone", "Pennant", "Saltmarsh", "Linden", "Thornbury", "Wrenfield", "Elmstead"]
WORDS_B = ["Systems", "Data", "Software", "IT Services", "Networks", "Computing", "Digital", "Solutions",
           "Technology", "Cloud", "Analytics", "IT Support", "Electrical Services", "Security Systems"]
TOWNS = [("Swansea", "SA1", "Wales"), ("Cardiff", "CF10", "Wales"), ("Newport", "NP20", "Wales"),
         ("Bridgend", "CF31", "Wales"), ("Wrexham", "LL11", "Wales"), ("Bristol", "BS1", None),
         ("Gloucester", "GL1", None), ("Hereford", "HR1", None), ("Chester", "CH1", None)]
FIRST = ["Alex", "Sam", "Jo", "Chris", "Robin", "Morgan", "Jamie", "Taylor", "Rhys", "Gareth", "Sian", "Bethan",
         "Huw", "Carys", "Dylan", "Megan", "Owen", "Ffion", "Tom", "Kate"]
LAST = ["Example", "Sample", "Placeholder", "Demo", "Testwell", "Mockford", "Fakely", "Pretend", "Notreal", "Imagin"]
TIERS = ["A - shortlist (15+ staff, 10+ yrs)", "B - possible (8-14 staff)", "C - too small or too young", "Dormant"]
SIC = {"Systems": "62020", "Data": "63110", "Software": "62012", "IT Services": "62020", "Networks": "61900",
       "Computing": "62090", "Digital": "62012", "Solutions": "62090", "Technology": "62020", "Cloud": "63110",
       "Analytics": "63110", "IT Support": "62090", "Electrical Services": "43210", "Security Systems": "80200"}


def generate(out: Path, n: int = 320, seed: int = 7):
    rnd = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)
    today = date(2026, 11, 4)
    companies, psc, notes = [], [], []
    holdcos = []
    used = set()
    for i in range(n):
        while True:
            a, b = rnd.choice(WORDS_A), rnd.choice(WORDS_B)
            name = f"{a} {b} Limited".upper()
            if name not in used:
                used.add(name)
                break
        num = f"9{i:07d}"
        inc = today - timedelta(days=int(rnd.triangular(365 * 2, 365 * 38, 365 * 18)))
        staff = max(0, int(rnd.lognormvariate(2.4, 0.9)))
        staff = min(staff, 220)
        town, pc_out, region = rnd.choice(TOWNS)
        pc = f"{pc_out} {rnd.randint(1, 9)}{rnd.choice('ABDEFGHJLNPQRSTUWXYZ')}{rnd.choice('ABDEFGHJLNPQRSTUWXYZ')}"
        addr = f"{rnd.randint(1, 120)} {rnd.choice(['High Street', 'Mill Lane', 'Station Road', 'Park Way', 'Dock Road'])}, {town}, {pc}"
        if rnd.random() < 0.04:
            addr, pc = "Companies House Default Address, Cardiff, CF14 8LH", "CF14 8LH"
        if rnd.random() < 0.05 and companies:
            addr = companies[-1]["registered_office_address"]  # shared accountant's office
        na = round(rnd.uniform(-50_000, 60_000 * max(staff, 1)), -2)
        na_prev = round(na * rnd.uniform(0.75, 1.15), -2)
        month = rnd.choice([3, 6, 12])
        period = date(2025 if month == 12 or rnd.random() < 0.4 else 2026, month, 30 if month == 6 else 31)
        turnover = round(staff * rnd.uniform(70_000, 160_000), -3) if staff >= 15 and rnd.random() < 0.35 else ""
        tier = TIERS[0] if staff >= 15 and (today - inc).days > 3650 else TIERS[1] if staff >= 8 else TIERS[2]
        if staff == 0 and rnd.random() < 0.5:
            tier = TIERS[3]
        companies.append({
            "rank": i + 1, "company_name": name, "company_number": num.lstrip("0"),
            "incorporation_date": inc.isoformat(), "years_trading": round((today - inc).days / 365.25, 1),
            "wales_flag": "Yes" if region == "Wales" else "No", "review_tier": tier,
            "employees": staff, "employees_prev": max(0, staff + rnd.randint(-4, 3)),
            "est_revenue_low": staff * 80_000 if staff else "", "est_revenue_high": staff * 150_000 if staff else "",
            "turnover": turnover, "profit_loss": "", "operating_profit": "",
            "net_assets": na, "net_assets_prev": na_prev, "net_assets_change": na - na_prev,
            "cash": max(0, round(na * rnd.uniform(0.2, 0.9), -2)), "debtors": round(staff * rnd.uniform(5_000, 25_000), -2),
            "accounts_made_up_to": period.isoformat(), "company_status": "active", "company_type": "ltd",
            "company_subtype": "", "registered_date": inc.isoformat(), "nature_of_business": SIC[b],
            "registered_office_address": addr, "source_sic_search": SIC[b], "incorporation_year": inc.year,
        })
        # owners
        r = rnd.random()
        def person():
            return {"kind": "individual-person-with-significant-control",
                    "name": f"{rnd.choice(['Mr', 'Mrs', 'Ms'])} {rnd.choice(FIRST)} {rnd.choice(LAST)}",
                    "date_of_birth": {"month": rnd.randint(1, 12), "year": rnd.randint(1946, 1990)},
                    "natures_of_control": [rnd.choice(["ownership-of-shares-75-to-100-percent", "ownership-of-shares-50-to-75-percent", "ownership-of-shares-25-to-50-percent"])],
                    "notified_on": rnd.choice(["2016-04-06", "2016-04-06", "2019-05-01", (today - timedelta(days=rnd.randint(30, 600))).isoformat()])}
        if r < 0.62:
            for _ in range(rnd.choice([1, 1, 2])):
                psc.append({"company_number": num, "data": person()})
        elif r < 0.75:
            h = f"8{i:07d}"
            holdcos.append(h)
            psc.append({"company_number": num, "data": {
                "kind": "corporate-entity-person-with-significant-control", "name": f"{a.upper()} HOLDINGS LIMITED",
                "identification": {"registration_number": h, "country_registered": "England And Wales"},
                "natures_of_control": ["ownership-of-shares-75-to-100-percent"], "notified_on": "2016-04-06"}})
            psc.append({"company_number": h, "data": person()})
        elif r < 0.8:
            psc.append({"company_number": num, "data": {
                "kind": "corporate-entity-person-with-significant-control", "name": f"{a.upper()} GROUP INC",
                "identification": {"registration_number": str(rnd.randint(100000, 999999)), "country_registered": "Delaware"},
                "natures_of_control": ["ownership-of-shares-75-to-100-percent"], "notified_on": "2018-01-01"}})
        elif r < 0.84:
            psc.append({"company_number": num, "data": {
                "kind": "corporate-entity-person-with-significant-control", "name": f"{a.upper()} CAPITAL PARTNERS LLP",
                "identification": {"registration_number": f"OC{rnd.randint(300000, 499999)}", "country_registered": "England And Wales"},
                "natures_of_control": ["ownership-of-shares-50-to-75-percent"], "notified_on": "2022-02-01"}})
        elif r < 0.87:
            psc.append({"company_number": num, "data": {
                "kind": "corporate-entity-person-with-significant-control", "name": f"{a.upper()} EMPLOYEE OWNERSHIP TRUSTEE LIMITED",
                "identification": {"registration_number": f"7{i:07d}", "country_registered": "England And Wales"},
                "natures_of_control": ["ownership-of-shares-75-to-100-percent"], "notified_on": "2023-09-01"}})
    # a serial owner with three companies
    serial = {"kind": "individual-person-with-significant-control", "name": "Mr Owen Example",
              "date_of_birth": {"month": 3, "year": 1958}, "natures_of_control": ["ownership-of-shares-75-to-100-percent"],
              "notified_on": "2016-04-06"}
    for k in (3, 41, 87):
        psc.append({"company_number": f"9{k:07d}", "data": serial})

    for c in companies[:60]:
        if rnd.random() < 0.5:
            notes.append({"Company Number": c["company_number"], "Company Name": c["company_name"],
                          "Ryan Assess": rnd.choice(["Looks like a genuine MSP; recurring contracts likely", "Field service, vans on website",
                                                     "Owner close to retirement age", "Website thin; check later", "Strong fit on paper"]),
                          "Decision": rnd.choice(["Shortlist", "Maybe", "Reject", "Watch", ""]), "Rating": rnd.choice(["", 2, 3, 4, 5])})

    with (out / "companies.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(companies[0].keys()))
        w.writeheader(); w.writerows(companies)

    # A later refresh: some companies file new accounts, some are dissolved,
    # renamed or move office. Imported second, it produces change history.
    upd = []
    for c in rnd.sample(companies, 40):
        c = dict(c)
        roll = rnd.random()
        if roll < 0.15:
            c["company_status"] = rnd.choice(["dissolved", "liquidation", "active - proposal to strike off"])
        elif roll < 0.65:
            old = date.fromisoformat(c["accounts_made_up_to"])
            c["accounts_made_up_to"] = date(old.year + 1, old.month, old.day).isoformat()
            c["employees_prev"] = c["employees"]
            c["employees"] = max(0, int(c["employees"]) + rnd.randint(-6, 8))
            c["net_assets_prev"] = c["net_assets"]
            c["net_assets"] = round(float(c["net_assets"]) * rnd.uniform(0.8, 1.3), -2)
            c["est_revenue_low"] = c["employees"] * 80_000 if c["employees"] else ""
            c["est_revenue_high"] = c["employees"] * 150_000 if c["employees"] else ""
        elif roll < 0.8:
            c["company_name"] = c["company_name"].replace(" LIMITED", " GROUP LIMITED")
        else:
            town, pc_out, _ = rnd.choice(TOWNS)
            c["registered_office_address"] = f"{rnd.randint(1, 99)} New Street, {town}, {pc_out} 1AB"
        upd.append(c)
    with (out / "companies_update.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(companies[0].keys()))
        w.writeheader(); w.writerows(upd)
    with (out / "psc.jsonl").open("w") as f:
        for p in psc:
            f.write(json.dumps(p) + "\n")
    with (out / "notes.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Company Number", "Company Name", "Ryan Assess", "Decision", "Rating"])
        w.writeheader(); w.writerows(notes)
    return out


IX_TEMPLATE = """<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" xmlns:xbrli="http://www.xbrl.org/2003/instance">
<body><!-- Fictional demo accounts generated by AcquireOS -->
<ix:header><ix:resources>{contexts}</ix:resources></ix:header>
{facts}
</body></html>"""


def _ix_filing(num: str, years: list[tuple[date, dict]]) -> str:
    ctx, facts = [], []
    for i, (end, v) in enumerate(years):
        ctx.append(f'<xbrli:context id="d{i}"><xbrli:entity><xbrli:identifier>{num}</xbrli:identifier></xbrli:entity>'
                   f'<xbrli:period><xbrli:startDate>{date(end.year - 1, end.month, 1)}</xbrli:startDate>'
                   f'<xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>')
        ctx.append(f'<xbrli:context id="i{i}"><xbrli:entity><xbrli:identifier>{num}</xbrli:identifier></xbrli:entity>'
                   f'<xbrli:period><xbrli:instant>{end}</xbrli:instant></xbrli:period></xbrli:context>')
        facts.append(f'<ix:nonFraction name="core:AverageNumberEmployeesDuringPeriod" contextRef="d{i}">{v["staff"]}</ix:nonFraction>')
        for name, key in (("NetAssetsLiabilities", "na"), ("CashBankOnHand", "cash"), ("Debtors", "debtors")):
            val = v[key]
            facts.append(f'<ix:nonFraction name="core:{name}" contextRef="i{i}"{" sign=\"-\"" if val < 0 else ""}>{abs(val):,.0f}</ix:nonFraction>')
        if v.get("turnover"):
            facts.append(f'<ix:nonFraction name="core:TurnoverRevenue" contextRef="d{i}">{v["turnover"]:,.0f}</ix:nonFraction>')
            facts.append(f'<ix:nonFraction name="core:OperatingProfitLoss" contextRef="d{i}"{" sign=\"-\"" if v["op"] < 0 else ""}>{abs(v["op"]):,.0f}</ix:nonFraction>')
    return IX_TEMPLATE.format(contexts="".join(ctx), facts="\n".join(facts))


def generate_accounts(out: Path, companies_csv: Path, seed: int = 11) -> Path:
    """Six years of fictional filed accounts for most demo companies, packed
    like a Companies House accounts zip (one file per filing)."""
    import zipfile

    rnd = random.Random(seed)
    rows = list(csv.DictReader(companies_csv.open()))
    z = out / "Accounts_Demo_Data.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in rows:
            if rnd.random() < 0.15:
                continue
            num = r["company_number"].zfill(8)
            end = date.fromisoformat(r["accounts_made_up_to"])
            staff = int(r["employees"] or 0)
            na = float(r["net_assets"] or 0)
            growth = rnd.uniform(-0.08, 0.14)
            files_turnover = staff >= 15 and rnd.random() < 0.4
            history = []
            for k in range(6):
                f = (1 + growth) ** -k
                s_ = max(0, round(staff * f * rnd.uniform(0.93, 1.07)))
                t = s_ * rnd.uniform(80_000, 140_000) if files_turnover else None
                history.append((date(end.year - k, end.month, end.day), {
                    "staff": s_, "na": round(na * f * rnd.uniform(0.9, 1.1), -2),
                    "cash": round(max(0, na * f * rnd.uniform(0.2, 0.8)), -2),
                    "debtors": round(s_ * rnd.uniform(6_000, 20_000), -2),
                    "turnover": t, "op": (t * rnd.uniform(-0.02, 0.18)) if t else None,
                }))
            # three filings, each with its year and the prior year
            for k in (4, 2, 0):
                pair = [history[k], history[k + 1]]
                fname = f"Prod224_{rnd.randint(1000, 9999)}_{num}_{pair[0][0]:%Y%m%d}.html"
                zf.writestr(fname, _ix_filing(num, pair))
    return z


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "demo-data")
    generate(out)
    print(f"Wrote fictional demo data to {out}/")


if __name__ == "__main__":
    main()
