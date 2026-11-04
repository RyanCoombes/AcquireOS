"""Read filed accounts from Companies House accounts bulk data.

Companies House publishes every electronically filed set of accounts as
inline XBRL (iXBRL) in daily and monthly zip files:
    https://download.companieshouse.gov.uk/en_accountsdata.html
    https://download.companieshouse.gov.uk/en_monthlyaccountsdata.html
Each file inside the zip is named like
    Prod224_0123_01234567_20250331.html
where the third part is the company number and the fourth the balance sheet
date. We use the name to skip companies that are not in the database, so a
multi-gigabyte zip is processed without reading most of it.

Each set of accounts normally holds the current year and the prior-year
comparatives, so loading a year or two of monthly files builds up several
years of history per company.
"""
from __future__ import annotations

import html
import json
import re
import zipfile
from datetime import date
from pathlib import Path

from .. import normalise as n

# Field -> taxonomy element local names, in order of preference. Covers the
# FRS 102 / FRS 105 taxonomies ("core:", "uk-core:", "bus:") and the older
# UK GAAP taxonomy used before 2015.
CONCEPTS: dict[str, list[str]] = {
    "employees": ["AverageNumberEmployeesDuringPeriod", "EmployeesTotal", "AverageNumberEmployees"],
    "turnover": ["TurnoverRevenue", "Turnover", "Revenue", "TurnoverGrossOperatingRevenue"],
    "operating_profit": ["OperatingProfitLoss", "OperatingProfit"],
    "profit_loss": ["ProfitLoss", "ProfitLossForPeriod", "ProfitLossOnOrdinaryActivitiesAfterTax",
                    "ProfitLossForFinancialYear"],
    "net_assets": ["NetAssetsLiabilities", "NetAssetsLiabilitiesIncludingPensionAssetLiability",
                   "TotalNetAssetsLiabilities", "Equity", "ShareholderFunds"],
    "cash": ["CashBankOnHand", "CashBankInHand", "CashAtBankAndInHand", "CashCashEquivalents"],
    "debtors": ["Debtors", "DebtorsDueWithinOneYear"],
    "dividends": ["DividendsPaid", "DividendsPaidOnShares", "DividendsPaidClassifiedAsFinancingActivities",
                  "EquityDividendsPaid"],
}
_LOCAL_TO_FIELD = {local: (field, rank) for field, names in CONCEPTS.items() for rank, local in enumerate(names)}

NAME_RE = re.compile(r"_(?P<num>[A-Z0-9]{8})_(?P<date>\d{8})\.(?:html|xhtml|xml)$", re.I)

_CONTEXT_RE = re.compile(r"<(?:\w+:)?context\b[^>]*\bid=\"(?P<id>[^\"]+)\"[^>]*>(?P<body>.*?)</(?:\w+:)?context>", re.S | re.I)
_END_RE = re.compile(r"<(?:\w+:)?(?:endDate|instant)>\s*(\d{4}-\d{2}-\d{2})\s*<", re.I)
_SEGMENT_RE = re.compile(r"<(?:\w+:)?(?:segment|scenario)\b", re.I)
# Inline XBRL numeric facts: <ix:nonFraction name="core:X" contextRef="c1" ...>1,234</ix:nonFraction>
_IX_RE = re.compile(r"<ix:nonFraction\b(?P<attrs>[^>]*)>(?P<val>.*?)</ix:nonFraction>", re.S | re.I)
# Plain XBRL facts (older .xml filings): <uk-gaap:Turnover contextRef="c1" ...>1234</uk-gaap:Turnover>
_XML_RE = re.compile(r"<(?P<tag>[\w-]+:(?P<local>\w+))\b(?P<attrs>[^>]*\bcontextRef=[^>]*)>(?P<val>[^<]*)</(?P=tag)>", re.S)
_ATTR_RE = re.compile(r"([\w:-]+)\s*=\s*\"([^\"]*)\"")
_TAG_RE = re.compile(r"<[^>]+>")


def parse_name(name: str) -> tuple[str, date] | None:
    m = NAME_RE.search(name.rsplit("/", 1)[-1])
    if not m:
        return None
    num = n.company_number(m.group("num"))
    try:
        d = date(int(m.group("date")[:4]), int(m.group("date")[4:6]), int(m.group("date")[6:]))
    except ValueError:
        return None
    return num, d


def _number(text: str, attrs: dict) -> float | None:
    raw = html.unescape(_TAG_RE.sub("", text)).strip()
    fmt = attrs.get("format", "").lower()
    if raw in {"", "-", "–", "—"} or "zerodash" in fmt or "fixedzero" in fmt or "fixed-zero" in fmt:
        value = 0.0
    else:
        if "commadecimal" in fmt:  # 1.234,56
            raw = raw.replace(".", "").replace(" ", "").replace(",", ".")
        else:
            raw = raw.replace(",", "").replace(" ", "")
        raw = raw.strip("()")
        try:
            value = float(raw)
        except ValueError:
            return None
    scale = attrs.get("scale")
    if scale and scale.lstrip("-").isdigit():
        value *= 10 ** int(scale)
    if attrs.get("sign") == "-":
        value = -value
    return value


def parse(content: str) -> dict[date, dict[str, float]]:
    """Return {period_end: {field: value}} for the plain (undimensioned)
    contexts in one set of accounts."""
    contexts: dict[str, date] = {}
    for m in _CONTEXT_RE.finditer(content):
        body = m.group("body")
        if _SEGMENT_RE.search(body):
            continue  # a breakdown (by class of share, director and so on), not the company total
        ends = _END_RE.findall(body)
        if ends:
            try:
                contexts[m.group("id")] = date.fromisoformat(ends[-1])
            except ValueError:
                pass

    found: dict[date, dict[str, tuple[int, float]]] = {}

    def take(local: str, attrs: dict, val: str):
        hit = _LOCAL_TO_FIELD.get(local)
        if not hit:
            return
        ctx = contexts.get(attrs.get("contextRef", ""))
        if ctx is None:
            return
        v = _number(val, attrs)
        if v is None:
            return
        field, rank = hit
        slot = found.setdefault(ctx, {})
        if field not in slot or rank < slot[field][0]:
            slot[field] = (rank, v)

    for m in _IX_RE.finditer(content):
        attrs = dict(_ATTR_RE.findall(m.group("attrs")))
        local = attrs.get("name", "").split(":")[-1]
        take(local, attrs, m.group("val"))
    if not found:
        for m in _XML_RE.finditer(content):
            attrs = dict(_ATTR_RE.findall(m.group("attrs")))
            take(m.group("local"), attrs, m.group("val"))

    out = {}
    for d, fields in found.items():
        vals = {f: v for f, (_, v) in fields.items()}
        if "employees" in vals:
            vals["employees"] = int(round(vals["employees"]))
        out[d] = vals
    return out


def run(conn, paths: list[Path], only_numbers: set[str] | None = None) -> dict:
    """Import accounts for companies in the database from one or more
    accounts bulk zips (or single .html/.xml files)."""
    from .companies import _change, refresh_estimates

    wanted = only_numbers or {r["company_number"] for r in conn.execute("select company_number from company")}
    latest = {
        r["company_number"]: r
        for r in conn.execute(
            """select c.company_number, greatest(c.last_accounts_date, fp.period_end) as period_end, fp.employees
               from company c left join lateral (
                   select period_end, employees from financial_period f
                   where f.company_number = c.company_number and not f.period_inferred
                   order by period_end desc limit 1) fp on true"""
        )
    }
    name = ", ".join(p.name for p in paths)
    run_id = conn.execute("insert into import_run (kind, filename) values ('accounts', %s) returning id",
                          (name[:500],)).fetchone()["id"]
    seen = matched = periods = changes = 0
    messages: list[str] = []

    for path in paths:
        for fname, read in _members(path):
            seen += 1
            meta = parse_name(fname)
            if not meta or meta[0] not in wanted:
                continue
            num, balance_date = meta
            matched += 1
            try:
                content = read().decode("utf-8", errors="replace")
                data = parse(content)
            except Exception as e:  # one bad filing must not stop the run
                if len(messages) < 30:
                    messages.append(f"{fname}: could not read ({e})")
                continue
            if not data:
                continue
            prev = latest.get(num) or {}
            prev_end, prev_staff = prev.get("period_end"), prev.get("employees")
            current = data.get(balance_date) or data[max(data)]
            if prev_end is None or balance_date > prev_end:
                if prev_end is not None:
                    _change(conn, num, run_id, "accounts", "period_end", prev_end, balance_date)
                    changes += 1
                    if current.get("employees") is not None and prev_staff is not None and current["employees"] != prev_staff:
                        _change(conn, num, run_id, "staff", "employees", prev_staff, current["employees"])
                        changes += 1
                latest[num] = {"period_end": balance_date, "employees": current.get("employees", prev_staff)}
            for period_end, vals in data.items():
                _upsert(conn, num, period_end, vals, f"accounts:{fname.rsplit('/', 1)[-1]}")
                periods += 1
            conn.execute(
                "update company set last_accounts_date = greatest(last_accounts_date, %s) where company_number = %s",
                (balance_date, num),
            )

    # Real periods replace the "inferred" prior-year rows from the ranked file.
    conn.execute(
        """delete from financial_period i using financial_period r
           where i.company_number = r.company_number and i.period_inferred and not r.period_inferred
             and abs(i.period_end - r.period_end) <= 45"""
    )
    refresh_estimates(conn)
    conn.execute(
        "update import_run set rows_in=%s, rows_ok=%s, messages=%s, finished_at=now() where id=%s",
        (seen, matched, json.dumps(messages), run_id),
    )
    return {"run_id": run_id, "files_seen": seen, "companies_matched": matched, "periods": periods,
            "changes": changes, "messages": messages}


def _upsert(conn, num, period_end, vals, source):
    cols = [k for k in CONCEPTS if vals.get(k) is not None]
    if not cols:
        return
    params = {"num": num, "pe": period_end, "src": source, **{c: vals[c] for c in cols}}
    conn.execute(
        f"""insert into financial_period (company_number, period_end, period_inferred, source, {', '.join(cols)})
            values (%(num)s, %(pe)s, false, %(src)s, {', '.join(f'%({c})s' for c in cols)})
            on conflict (company_number, period_end) do update set
              period_inferred = false, source = excluded.source,
              {', '.join(f'{c} = excluded.{c}' for c in cols)}""",
        params,
    )


def _members(path: Path):
    """Yield (name, reader) for each accounts file in a zip, or the file itself.
    Monthly zips sometimes contain the daily zips, so nested zips are opened too."""
    if path.suffix.lower() != ".zip":
        yield path.name, path.read_bytes
        return
    with zipfile.ZipFile(path) as z:
        yield from _zip_members(z)


def _zip_members(z: zipfile.ZipFile):
    import io

    for info in z.infolist():
        if info.is_dir():
            continue
        low = info.filename.lower()
        if low.endswith(".zip"):
            with z.open(info) as f, zipfile.ZipFile(io.BytesIO(f.read())) as inner:
                yield from _zip_members(inner)
        elif low.endswith((".html", ".xhtml", ".xml")):
            yield info.filename, (lambda i=info: z.read(i))
