"""A company's deals and corporate events, newest first: what Companies House
shows (sold to a company, companies it took control of, share buy-backs,
renames, lending taken out around a sale) plus deals found by research, each
with where it came from."""
from __future__ import annotations

from datetime import date, timedelta

PSC_START = date(2016, 4, 6)  # the owners register began: entries dated then aren't events
KINDS = ("acquired", "sold", "merged", "investment", "eot", "mbo", "mbi", "disposal", "listing", "delisting", "refinancing", "other")


def _band(natures) -> str:
    for n in natures or []:
        if "ownership-of-shares-" in n:
            a, b = n.split("ownership-of-shares-")[1].split("-percent")[0].split("-to-")
            return f"over {a}%" if b == "100" else f"{a}–{b}%"
    return ""


def events(conn, company_number: str) -> list[dict]:
    num = company_number.strip().upper()
    out: list[dict] = []
    ch = "https://find-and-update.company-information.service.gov.uk/company/"
    # Sold: a company joined the owners register (as the previous owners left: a sale).
    rows = conn.execute("""select cp.notified_on, cp.ceased_on, cp.natures, p.name, p.kind, p.registration_number
                           from company_person cp join person p on p.id = cp.person_id
                           where cp.company_number = %s and cp.role = 'psc'""", (num,)).fetchall()
    for r in rows:
        if r["kind"] == "individual" or not r["notified_on"] or r["notified_on"] <= PSC_START:
            continue
        left = [x for x in rows if x is not r and x["ceased_on"] and abs((x["ceased_on"] - r["notified_on"]).days) <= 120]
        band = _band(r["natures"])
        out.append({"date": r["notified_on"], "kind": "sold" if left else "owner",
                    "title": f"Sold to {r['name']}" if left else f"{r['name']} became an owner",
                    "detail": ", ".join(x for x in [band and f"holds {band}", left and "previous owners left the register"] if x),
                    "counterparty": r["name"], "counterparty_number": r["registration_number"],
                    "source": "Companies House", "source_url": ch + num + "/persons-with-significant-control"})
    # Bought: it joined another company's owners register (or set one up).
    for r in conn.execute("""select cp.company_number, cp.notified_on, cp.ceased_on, cp.natures, c.name, c.incorporation_date
                             from person p join company_person cp on cp.person_id = p.id join company c on c.company_number = cp.company_number
                             where p.registration_number = %s and cp.company_number <> %s and cp.role = 'psc'""", (num, num)):
        if r["notified_on"] and r["notified_on"] > PSC_START:
            new = r["incorporation_date"] and abs((r["notified_on"] - r["incorporation_date"]).days) <= 90
            out.append({"date": r["notified_on"], "kind": "formed" if new else "acquired",
                        "title": f"Set up {r['name']}" if new else f"Took control of {r['name']}",
                        "detail": ", ".join(x for x in [_band(r["natures"]) and f"holds {_band(r['natures'])}",
                                                         not new and r["incorporation_date"] and f"established {r['incorporation_date'].year}"] if x),
                        "counterparty": r["name"], "counterparty_number": r["company_number"],
                        "source": "Companies House", "source_url": ch + r["company_number"] + "/persons-with-significant-control"})
        if r["ceased_on"]:
            out.append({"date": r["ceased_on"], "kind": "disposal", "title": f"No longer controls {r['name']}", "detail": "",
                        "counterparty": r["name"], "counterparty_number": r["company_number"],
                        "source": "Companies House", "source_url": ch + r["company_number"] + "/persons-with-significant-control"})
    # Share buy-backs and cancellations (often owners being bought out).
    for r in conn.execute("""select filed_on, type, description from filing where company_number = %s
                             and upper(type) in ('SH03', 'SH06') order by filed_on""", (num,)):
        out.append({"date": r["filed_on"], "kind": "buyback",
                    "title": "Bought back its own shares" if r["type"].upper() == "SH03" else "Cancelled shares",
                    "detail": "", "source": "Companies House", "source_url": ch + num + "/filing-history"})
    # Renamed.
    c = conn.execute("select previous_names from company where company_number = %s", (num,)).fetchone()
    for p in (c or {}).get("previous_names") or []:
        if p.get("until"):
            try:
                d = date.fromisoformat(str(p["until"])[:10])
            except ValueError:
                continue
            out.append({"date": d, "kind": "renamed", "title": f"Renamed (was {p['name']})", "detail": "",
                        "source": "Companies House", "source_url": ch + num})
    # Lending taken out around a sale: often how the price was paid.
    sales = [e for e in out if e["kind"] == "sold"]
    if sales:
        for r in conn.execute("select created_on, holders from charge where company_number = %s and created_on is not null", (num,)):
            for e in sales:
                if abs((r["created_on"] - e["date"]).days) <= 30:
                    e["detail"] = ", ".join(x for x in [e["detail"], f"charge to {', '.join(r['holders']) or 'a lender'} the same month"] if x)
    # Found by research (with a source).
    en = conn.execute("select deals from enrichment where company_number = %s", (num,)).fetchone()
    for d in (en or {}).get("deals") or []:
        try:
            when = date.fromisoformat((d.get("date") or "")[:10] if len(d.get("date") or "") >= 10 else (d.get("date") or "") + "-01")
        except ValueError:
            when = None
        detail = ", ".join(x for x in [d.get("value") and f"value {d['value']}", d.get("note")] if x)
        # The same deal as a Companies House event (same kind, within two months): one line, both sources.
        same = next((e for e in out if e["source"] == "Companies House" and when and e["kind"] == (d.get("kind") or "other")
                     and abs((e["date"] - when).days) <= 62), None)
        if same:
            same["detail"] = ", ".join(x for x in [detail, same["detail"]] if x)
            same["research_title"], same["research_url"] = d.get("title"), d.get("source_url")
            continue
        out.append({"date": when, "date_text": d.get("date"), "kind": d.get("kind") or "other", "title": d.get("title"),
                    "detail": detail, "counterparty": d.get("counterparty"), "source": "research", "source_url": d.get("source_url")})
    out.sort(key=lambda e: e["date"] or date.min, reverse=True)
    cutoff = date.today() - timedelta(days=365 * 25)
    return [e for e in out if not e["date"] or e["date"] >= cutoff]
