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
    # Balance sheet totals. Creditors are usually tagged with a "within / after
    # one year" breakdown, which we do not read, so they are worked out from
    # these totals instead (current assets - net current assets, and so on).
    "fixed_assets": ["FixedAssets", "NonCurrentAssets", "TotalFixedAssets"],
    "intangible_assets": ["IntangibleAssets", "IntangibleAssetsIncludingGoodwill", "IntangibleFixedAssets"],
    "current_assets": ["CurrentAssets", "TotalCurrentAssets"],
    "net_current_assets": ["NetCurrentAssetsLiabilities", "NetCurrentAssets"],
    "total_assets_less_cl": ["TotalAssetsLessCurrentLiabilities"],
    # Profit and loss detail: only in fuller accounts.
    "gross_profit": ["GrossProfitLoss", "GrossProfit"],
    "director_pay": ["DirectorRemuneration", "DirectorsRemuneration", "DirectorRemunerationBenefitsIncludingPayments",
                     "DirectorsRemunerationAndOtherBenefits"],
    "staff_costs": ["StaffCostsEmployeeBenefitsExpense", "StaffCosts", "WagesSalaries"],
}
# Bumped when new figures are read, so months read earlier can be read again.
LOADER_VERSION = 2
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


# Fast path (bytes, no decoding): only <ix:nonFraction> tags whose name is one
# of the concepts we keep are matched at all, so the hundreds of other
# figures in a filing are skipped by the regex engine.
_WANTED = "|".join(sorted(_LOCAL_TO_FIELD, key=len, reverse=True))
_IX_WANTED_B = re.compile(
    rb'<ix:nonFraction\b(?=[^>]*\bname="[\w.-]+:(?:' + _WANTED.encode() + rb')")([^>]*)>(.*?)</ix:nonFraction>',
    re.S | re.I)
_ATTR_B = re.compile(rb'([\w:-]+)\s*=\s*"([^"]*)"')
_CONTEXT_B = re.compile(rb'<(?:\w+:)?context\b[^>]*\bid="([^"]+)"[^>]*>(.*?)</(?:\w+:)?context>', re.S | re.I)
_END_B = re.compile(rb'<(?:\w+:)?(?:endDate|instant)>\s*(\d{4}-\d{2}-\d{2})\s*<', re.I)
_SEGMENT_B = re.compile(rb'<(?:\w+:)?(?:segment|scenario)\b', re.I)
_TAG_B = re.compile(rb'<[^>]+>')
# Faster still: search for the wanted names directly (a literal-led pattern the
# regex engine scans for quickly), then find the enclosing tag with bytes ops.
_NAME_B = re.compile(rb'name="[\w.-]+:(?:' + _WANTED.encode() + rb')"')
_OPEN_TAG = b"<ix:nonfraction"
_CLOSE_TAG = b"</ix:nonfraction>"


def _facts_fast(raw: bytes, low: bytes | None = None):
    """[(attrs bytes, value bytes)] for wanted ix:nonFraction tags."""
    out = []
    for m in _NAME_B.finditer(raw):
        if low is None:
            low = raw.lower()  # tag names can be any case; offsets are unchanged
        start = low.rfind(_OPEN_TAG, 0, m.start())
        if start == -1 or low.find(b">", start, m.start()) != -1:
            continue  # the name belongs to some other element
        gt = raw.find(b">", m.end())
        if gt == -1:
            continue
        attrs = raw[start + len(_OPEN_TAG):gt]
        # A self-closing or nil fact has no value: skip it, rather than reading
        # on to the next fact's closing tag and taking that figure instead.
        if attrs.rstrip().endswith(b"/") or b'nil="true"' in low[start:gt]:
            continue
        end = low.find(_CLOSE_TAG, gt)
        if end == -1:
            continue
        out.append((attrs, raw[gt + 1:end]))
    return out


def _context_date(raw: bytes, low: bytes, cid: str):
    """Period end for one context id, or None if it is a breakdown/missing."""
    needle = b'id="' + cid.encode() + b'"'
    pos = 0
    while True:
        i = raw.find(needle, pos)
        if i == -1:
            return None
        lt = raw.rfind(b"<", 0, i)
        head = low[lt:i]
        if b"context" in head.split(b" ", 1)[0]:
            close = low.find(b"context>", i)
            body = raw[i:close] if close != -1 else raw[i:i + 4000]
            if _SEGMENT_B.search(body):
                return None
            ends = _END_B.findall(body)
            try:
                return date.fromisoformat(ends[-1].decode()) if ends else None
            except ValueError:
                return None
        pos = i + len(needle)


def parse(content: str | bytes) -> dict[date, dict[str, float]]:
    """Return {period_end: {field: value}} for the plain (undimensioned)
    contexts in one set of accounts. Accepts text or raw bytes."""
    raw = content.encode("utf-8", "replace") if isinstance(content, str) else content
    found: dict[date, dict[str, tuple[int, float]]] = {}
    low = raw.lower()
    facts = _facts_fast(raw, low)
    if facts:
        contexts: dict[str, date | None] = {}

        def ctx_date(cid: str):
            if cid not in contexts:
                contexts[cid] = _context_date(raw, low, cid)
            return contexts[cid]

        for attrs_b, val_b in facts:
            attrs = {k.decode(): v.decode("utf-8", "replace") for k, v in _ATTR_B.findall(attrs_b)}
            hit = _LOCAL_TO_FIELD.get(attrs.get("name", "").split(":")[-1])
            if not hit:
                continue
            d = ctx_date(attrs.get("contextRef", ""))
            if d is None:
                continue
            v = _number(_TAG_B.sub(b"", val_b).decode("utf-8", "replace"), attrs)
            if v is None:
                continue
            field, rank = hit
            slot = found.setdefault(d, {})
            if field not in slot or rank < slot[field][0]:
                slot[field] = (rank, v)
    else:
        # Older plain-XBRL filings (.xml): the original, more general parser.
        found = _parse_plain(raw.decode("utf-8", "replace"))

    out = {}
    for d, fields in found.items():
        vals = {f: v for f, (_, v) in fields.items()}
        if "employees" in vals:
            # Mis-tagged filings sometimes put a money figure in the staff
            # field; no UK company has a million employees.
            emp = vals["employees"]
            if 0 <= emp < 1_000_000:
                vals["employees"] = int(round(emp))
            else:
                del vals["employees"]
        out[d] = vals
    return out


def _parse_plain(content: str) -> dict[date, dict[str, tuple[int, float]]]:
    contexts: dict[str, date] = {}
    for m in _CONTEXT_RE.finditer(content):
        body = m.group("body")
        if _SEGMENT_RE.search(body):
            continue
        ends = _END_RE.findall(body)
        if ends:
            try:
                contexts[m.group("id")] = date.fromisoformat(ends[-1])
            except ValueError:
                pass
    found: dict[date, dict[str, tuple[int, float]]] = {}
    for pattern in (_IX_RE, _XML_RE):
        for m in pattern.finditer(content):
            attrs = dict(_ATTR_RE.findall(m.group("attrs")))
            local = attrs.get("name", "").split(":")[-1] if pattern is _IX_RE else m.group("local")
            hit = _LOCAL_TO_FIELD.get(local)
            ctx = contexts.get(attrs.get("contextRef", ""))
            if not hit or ctx is None:
                continue
            v = _number(m.group("val"), attrs)
            if v is None:
                continue
            field, rank = hit
            slot = found.setdefault(ctx, {})
            if field not in slot or rank < slot[field][0]:
                slot[field] = (rank, v)
        if found:
            break
    return found


_ZIP_CACHE: dict = {}


def _parse_member(item):
    """Worker: (fname, raw bytes) or (fname, zip path, member name) ->
    (fname, number, balance date, {period: values}) or None. Reading the
    member inside the worker keeps the main process free."""
    if len(item) == 3:
        fname, zpath, member = item
        z = _ZIP_CACHE.get(zpath)
        if z is None:
            z = _ZIP_CACHE[zpath] = zipfile.ZipFile(zpath)
        try:
            raw = z.read(member)
        except Exception:
            return None
    else:
        fname, raw = item
    meta = parse_name(fname)
    if not meta:
        return None
    try:
        data = parse(raw)
    except Exception:
        return None
    return (fname.rsplit("/", 1)[-1], meta[0], meta[1], data)


FIELDS = list(CONCEPTS.keys())


def run(conn, paths: list[Path], only_numbers: set[str] | None = None, record_changes: bool = True,
        workers: int | None = None, batch: int = 5000, progress=None) -> dict:
    """Import filed accounts for every company in the database.

    - Files are parsed in parallel (all CPU cores by default).
    - Figures are written in batches through a staging table.
    - A figure is only replaced by one from a filing with the same or a later
      balance sheet date (source_balance_date), so loading older months after
      newer ones can never overwrite newer figures.
    - record_changes=False (used when back-filling history) records no
      "new accounts" or staff changes.
    """
    import os
    from multiprocessing import get_context

    from .companies import refresh_estimates

    if only_numbers is not None:
        wanted = set(only_numbers)
    else:
        wanted = set()
        with conn.cursor(name="acc_nums") as cur:
            cur.itersize = 200_000
            cur.execute("select company_number from company")
            for r in cur:
                wanted.add(r["company_number"])
    name = ", ".join(p.name for p in paths)
    run_id = conn.execute("insert into import_run (kind, filename, loader_version) values ('accounts', %s, %s) returning id",
                          (name[:500], LOADER_VERSION)).fetchone()["id"]
    conn.execute("drop table if exists acc_stage; drop table if exists acc_touched")
    conn.execute("create temp table acc_touched (company_number text primary key)")
    conn.execute(f"""create temp table acc_stage (company_number text, period_end date, balance_date date,
                    source text, {", ".join(f"{f} numeric" for f in FIELDS)})""")

    seen = matched = periods = changes = 0
    buf: list[tuple] = []
    total_files = _count_members(paths)

    def flush():
        nonlocal periods, changes, buf
        if not buf:
            return
        with conn.cursor().copy(
            f"copy acc_stage (company_number, period_end, balance_date, source, {', '.join(FIELDS)}) from stdin"
        ) as cp:
            for r in buf:
                cp.write_row(r)
        if record_changes:
            changes += _batch_changes(conn, run_id)
        periods += conn.execute(f"""
            insert into financial_period as fp (company_number, period_end, period_inferred, source,
                source_balance_date, {', '.join(FIELDS)})
            select distinct on (company_number, period_end) company_number, period_end, false, source, balance_date,
                   {', '.join(FIELDS)}
            from acc_stage order by company_number, period_end, balance_date desc, source desc
            on conflict (company_number, period_end) do update set
                period_inferred = false, source = excluded.source, source_balance_date = excluded.source_balance_date,
                {', '.join(f"{f} = coalesce(excluded.{f}, fp.{f})" for f in FIELDS)}
            where fp.period_inferred or fp.source_balance_date is null
               or excluded.source_balance_date >= fp.source_balance_date""").rowcount
        conn.execute("insert into acc_touched select distinct company_number from acc_stage on conflict do nothing")
        conn.execute("""
            update company c set last_accounts_date = greatest(c.last_accounts_date, x.d)
            from (select company_number, max(balance_date) as d from acc_stage group by 1) x
            where x.company_number = c.company_number""")
        conn.execute("truncate acc_stage")
        buf = []

    def items():
        nonlocal seen
        for path in paths:
            for fname, read, ref in _members(path, refs=True):
                seen += 1
                meta = parse_name(fname)
                if meta and meta[0] in wanted:
                    # Flat zips: hand the worker a reference, not the bytes.
                    yield (fname, str(ref[0]), ref[1]) if ref else (fname, read())

    def handle(res):
        nonlocal matched
        if not res:
            return
        fname, num, bdate, data = res
        if not data:
            return
        matched += 1
        for pe, vals in data.items():
            buf.append((num, pe, bdate, f"accounts:{fname}", *[vals.get(f) for f in FIELDS]))
        if len(buf) >= batch:
            flush()
            if progress:
                progress(f"{seen:,} of about {total_files:,} filings read; {matched:,} loaded",
                         min(seen / max(total_files, 1), 1))

    workers = workers if workers is not None else (os.cpu_count() or 1)
    if workers > 1:
        # "spawn" so worker processes start clean even inside the threaded web server.
        with get_context("spawn").Pool(workers) as pool:
            for res in pool.imap_unordered(_parse_member, items(), chunksize=32):
                handle(res)
    else:
        for it in items():
            handle(_parse_member(it))
    flush()

    # Real periods replace the "inferred" prior-year rows from the ranked file.
    # Only the companies this file touched (not the whole table, every month).
    conn.execute(
        """delete from financial_period i using financial_period r
           where i.company_number = r.company_number and i.period_inferred and not r.period_inferred
             and abs(i.period_end - r.period_end) <= 45
             and i.company_number in (select company_number from acc_touched)"""
    )
    refresh_estimates(conn, from_table="acc_touched")
    from ..scoring import refresh_latest

    if progress:
        progress("Updating each company's latest figures", 0.99)
    refresh_latest(conn, from_table="acc_touched")
    conn.execute(
        "update import_run set rows_in=%s, rows_ok=%s, messages=%s, finished_at=now() where id=%s",
        (seen, matched, json.dumps([]), run_id),
    )
    return {"run_id": run_id, "files_seen": seen, "companies_matched": matched, "periods": periods,
            "changes": changes, "messages": []}


def _batch_changes(conn, run_id) -> int:
    """New accounts (and staff changes) for filings newer than anything held."""
    n = conn.execute("""
        with newest as (
            select distinct on (company_number) company_number, balance_date, employees
            from acc_stage where period_end = balance_date
            order by company_number, balance_date desc
        ), prior as (
            select c.company_number, greatest(c.last_accounts_date, x.pe) as prev_end, x.emp as prev_emp
            from company c join newest nw on nw.company_number = c.company_number
            left join lateral (select period_end as pe, employees as emp from financial_period f
                               where f.company_number = c.company_number and not f.period_inferred
                               order by period_end desc limit 1) x on true
        ), acc as (
            insert into company_change (company_number, import_run_id, kind, field, old_value, new_value)
            select nw.company_number, %(run)s, 'accounts', 'period_end', pr.prev_end::text, nw.balance_date::text
            from newest nw join prior pr on pr.company_number = nw.company_number
            where pr.prev_end is not null and nw.balance_date > pr.prev_end
            returning 1
        ), staff as (
            insert into company_change (company_number, import_run_id, kind, field, old_value, new_value)
            select nw.company_number, %(run)s, 'staff', 'employees', pr.prev_emp::text, nw.employees::int::text
            from newest nw join prior pr on pr.company_number = nw.company_number
            where pr.prev_end is not null and nw.balance_date > pr.prev_end
              and nw.employees is not null and pr.prev_emp is not null and nw.employees <> pr.prev_emp
            returning 1
        )
        select (select count(*) from acc) + (select count(*) from staff) as n""", {"run": run_id}).fetchone()["n"]
    return n


def _upsert(conn, num, period_end, vals, source, balance_date=None):
    cols = [k for k in CONCEPTS if vals.get(k) is not None]
    if not cols:
        return
    params = {"num": num, "pe": period_end, "src": source, "bd": balance_date or period_end, **{c: vals[c] for c in cols}}
    conn.execute(
        f"""insert into financial_period as fp (company_number, period_end, period_inferred, source, source_balance_date,
                {', '.join(cols)})
            values (%(num)s, %(pe)s, false, %(src)s, %(bd)s, {', '.join(f'%({c})s' for c in cols)})
            on conflict (company_number, period_end) do update set
              period_inferred = false, source = excluded.source, source_balance_date = excluded.source_balance_date,
              {', '.join(f'{c} = excluded.{c}' for c in cols)}
            where fp.period_inferred or fp.source_balance_date is null
               or excluded.source_balance_date >= fp.source_balance_date""",
        params,
    )


def _count_members(paths) -> int:
    """Number of filings, for progress. Nested daily zips count roughly."""
    total = 0
    for p in paths:
        if p.suffix.lower() != ".zip":
            total += 1
            continue
        try:
            with zipfile.ZipFile(p) as z:
                infos = [i for i in z.infolist() if not i.is_dir()]
                inner = [i for i in infos if i.filename.lower().endswith(".zip")]
                if inner:
                    # Estimate from compressed size: about 12 KB per filing.
                    total += sum(max(int(i.compress_size / 12_000), 1) for i in inner)
                total += len(infos) - len(inner)
        except Exception:
            pass
    return total


def _members(path: Path, refs: bool = False):
    """Yield (name, reader) for each accounts file in a zip, or the file itself.
    Monthly zips sometimes contain the daily zips, so nested zips are opened too.
    With refs=True, yields (name, reader, (zip path, member) or None)."""
    if path.suffix.lower() != ".zip":
        yield (path.name, path.read_bytes, None) if refs else (path.name, path.read_bytes)
        return
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            low = info.filename.lower()
            if low.endswith(".zip"):
                import io

                with z.open(info) as f, zipfile.ZipFile(io.BytesIO(f.read())) as inner:
                    for name, read in _zip_members(inner):
                        yield (name, read, None) if refs else (name, read)
            elif low.endswith((".html", ".xhtml", ".xml")):
                reader = (lambda i=info: z.read(i))
                yield (info.filename, reader, (path, info.filename)) if refs else (info.filename, reader)


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
