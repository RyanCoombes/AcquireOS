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
    # For EBITDA: depreciation and amortisation charged in the year (P&L or
    # the fixed-asset notes' totals).
    "depreciation": ["DepreciationExpensePropertyPlantEquipment", "IncreaseFromDepreciationChargeForYearPropertyPlantEquipment",
                     "DepreciationImpairmentExpensePropertyPlantEquipment", "DepreciationTangibleFixedAssets",
                     "DepreciationOwnedTangibleFixedAssets", "DepreciationChargeForPeriodTangibleFixedAssets"],
    "amortisation": ["AmortisationExpenseIntangibleAssets", "IncreaseFromAmortisationChargeForYearIntangibleAssets",
                     "AmortisationImpairmentExpenseIntangibleAssets", "AmortisationIntangibleFixedAssets",
                     "AmortisationGoodwill"],
    "depreciation_amortisation": ["DepreciationAmortisationImpairmentExpense", "DepreciationAmortisationExpense"],
    "interest_payable": ["InterestPayableSimilarChargesFinanceCosts", "InterestPayableSimilarCharges",
                         "InterestPayableAndSimilarCharges"],
    "tax": ["TaxTaxCreditOnProfitOrLossOnOrdinaryActivities", "TaxOnProfitOrLossOnOrdinaryActivities",
            "IncomeTaxExpenseCredit", "TaxExpenseCreditApplicableTaxRate"],
    # Debt and working capital. Creditors are usually tagged once with a
    # "within one year" / "after one year" breakdown, read below (_SPLIT).
    "creditors_within": ["CreditorsDueWithinOneYear", "CreditorsAmountsFallingDueWithinOneYear", "TotalCreditorsDueWithinOneYear"],
    "creditors_after": ["CreditorsDueAfterOneYear", "CreditorsAmountsFallingDueAfterMoreThanOneYear", "TotalCreditorsDueAfterOneYear"],
    "bank_loans": ["BankBorrowingsOverdrafts", "BankBorrowings", "BankLoansOverdrafts", "BankLoans", "LoansFromBanks"],
    "bank_overdrafts": ["BankOverdrafts"],
    "stock": ["Stocks", "Inventories", "StocksInventory", "TotalInventories"],
    "trade_debtors": ["TradeDebtorsTradeReceivables", "TradeDebtors"],
    "trade_creditors": ["TradeCreditorsTradePayables", "TradeCreditors"],
    "retained_earnings": ["RetainedEarningsAccumulatedLosses", "ProfitLossAccountReserve", "ProfitLossReserve"],
    "share_capital": ["CalledUpShareCapital", "CalledUpShareCapitalPaid", "ShareCapital"],
}
# Figures that are a size, never negative whatever the sign in the filing.
POSITIVE = {"depreciation", "amortisation", "depreciation_amortisation", "interest_payable", "creditors_within",
            "creditors_after", "bank_loans", "bank_overdrafts", "stock", "trade_debtors", "trade_creditors"}
# Tagged once with a maturity breakdown: Creditors[WithinOneYear] and so on.
# A total with no breakdown wins; otherwise within + after are added up.
_SPLIT = {"Creditors": {"WithinOneYear": "creditors_within", "AfterOneYear": "creditors_after"},
          "BankBorrowingsOverdrafts": {"WithinOneYear": "bank_loans", "AfterOneYear": "bank_loans"},
          "BankBorrowings": {"WithinOneYear": "bank_loans", "AfterOneYear": "bank_loans"}}
# Text kept as well as figures.
TEXT_CONCEPTS = {"principal_activity": ["DescriptionPrincipalActivities", "PrincipalActivities", "DescriptionPrincipalActivity"]}
# Bumped when new figures are read, so months read earlier can be read again.
LOADER_VERSION = 4  # 4: a year's own accounts win over later comparatives
_LOCAL_TO_FIELD = {local: (field, rank) for field, names in CONCEPTS.items() for rank, local in enumerate(names)}
_WANTED_LOCALS = set(_LOCAL_TO_FIELD) | set(_SPLIT)

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
_WANTED = "|".join(sorted(_WANTED_LOCALS, key=len, reverse=True))
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


_MEMBER_B = re.compile(rb'<(?:\w+:)?explicitMember\b[^>]*>\s*[\w.-]*:?(\w+)\s*<', re.I)


def _context_date(raw: bytes, low: bytes, cid: str):
    """Period end for one context id, or None if it is a breakdown/missing."""
    d, member = _context(raw, low, cid)
    return None if member else d


def _context(raw: bytes, low: bytes, cid: str):
    """(period end, maturity member or None). A breakdown other than a single
    "within / after one year" member gives (None, None)."""
    needle = b'id="' + cid.encode() + b'"'
    pos = 0
    while True:
        i = raw.find(needle, pos)
        if i == -1:
            return None, None
        lt = raw.rfind(b"<", 0, i)
        head = low[lt:i]
        if b"context" in head.split(b" ", 1)[0]:
            close = low.find(b"context>", i)
            body = raw[i:close] if close != -1 else raw[i:i + 4000]
            member = None
            if _SEGMENT_B.search(body):
                members = _MEMBER_B.findall(body)
                if len(members) != 1 or members[0].decode() not in ("WithinOneYear", "AfterOneYear"):
                    return None, None
                member = members[0].decode()
            ends = _END_B.findall(body)
            try:
                return (date.fromisoformat(ends[-1].decode()) if ends else None), member
            except ValueError:
                return None, None
        pos = i + len(needle)


def parse(content: str | bytes) -> dict[date, dict[str, float]]:
    """Return {period_end: {field: value}} for the plain (undimensioned)
    contexts in one set of accounts. Accepts text or raw bytes."""
    raw = content.encode("utf-8", "replace") if isinstance(content, str) else content
    found: dict[date, dict[str, tuple[int, float]]] = {}
    low = raw.lower()
    facts = _facts_fast(raw, low)
    split: dict[date, dict[str, dict[tuple[str, str], float]]] = {}
    if facts:
        contexts: dict[str, tuple] = {}

        def ctx(cid: str):
            if cid not in contexts:
                contexts[cid] = _context(raw, low, cid)
            return contexts[cid]

        for attrs_b, val_b in facts:
            attrs = {k.decode(): v.decode("utf-8", "replace") for k, v in _ATTR_B.findall(attrs_b)}
            local = attrs.get("name", "").split(":")[-1]
            d, member = ctx(attrs.get("contextRef", ""))
            if d is None:
                continue
            if member:
                field = _SPLIT.get(local, {}).get(member)
                if not field:
                    continue
                v = _number(_TAG_B.sub(b"", val_b).decode("utf-8", "replace"), attrs)
                if v is not None:
                    split.setdefault(d, {}).setdefault(field, {})[(local, member)] = abs(v)
                continue
            hit = _LOCAL_TO_FIELD.get(local)
            if not hit:
                continue
            v = _number(_TAG_B.sub(b"", val_b).decode("utf-8", "replace"), attrs)
            if v is None:
                continue
            field, rank = hit
            if field == "employees" and v in (d.year, d.year - 1):
                rank += 100  # the year heading tagged as staff: any real figure for the year wins
            slot = found.setdefault(d, {})
            if field not in slot or rank < slot[field][0]:
                slot[field] = (rank, v)
        # Maturity breakdowns, where there is no plain total.
        for d, fields in split.items():
            slot = found.setdefault(d, {})
            for field, parts in fields.items():
                if field in slot:
                    continue
                by_concept: dict[str, float] = {}
                for (local, _), v in parts.items():
                    by_concept[local] = by_concept.get(local, 0.0) + v
                # one concept only (BankBorrowingsOverdrafts before BankBorrowings), never both added
                best = next(c for c in ("Creditors", "BankBorrowingsOverdrafts", "BankBorrowings") if c in by_concept)
                slot[field] = (99, by_concept[best])
    else:
        # Older plain-XBRL filings (.xml): the original, more general parser.
        found = _parse_plain(raw.decode("utf-8", "replace"))

    out = {}
    texts = _texts(raw, low) if facts else {}
    for d, fields in found.items():
        vals = {f: (abs(v) if f in POSITIVE else v) for f, (_, v) in fields.items()}
        for f, by_date in texts.items():
            if d in by_date:
                vals[f] = by_date[d]
        if "employees" in vals:
            # Mis-tagged filings sometimes put a money figure in the staff
            # field (no UK company has a million employees), or tag the year
            # heading above the staff note ("2025 2024") as the staff count.
            emp = vals["employees"]
            if 0 <= emp < 1_000_000 and not year_as_staff(emp, d, vals.get("turnover")) \
                    and not implausible_staff(emp, vals.get("turnover")):
                vals["employees"] = int(round(emp))
            else:
                del vals["employees"]
        out[d] = vals
    return out


_NONNUM_B = re.compile(rb'<ix:nonNumeric\b(?=[^>]*\bname="[\w.-]+:(' +
                       "|".join(n for v in TEXT_CONCEPTS.values() for n in v).encode() + rb')")([^>]*)>(.*?)</ix:nonNumeric>',
                       re.S | re.I)


def _texts(raw: bytes, low: bytes) -> dict[str, dict[date, str]]:
    """Tagged text (principal activity) by period end."""
    out: dict[str, dict[date, str]] = {}
    if b"nonnumeric" not in low:
        return out
    for m in _NONNUM_B.finditer(raw):
        local = m.group(1).decode()
        field = next(f for f, names in TEXT_CONCEPTS.items() if local in names)
        attrs = {k.decode(): v.decode("utf-8", "replace") for k, v in _ATTR_B.findall(m.group(2))}
        d, member = _context(raw, low, attrs.get("contextRef", ""))
        if d is None or member:
            continue
        text = " ".join(html.unescape(_TAG_B.sub(b" ", m.group(3)).decode("utf-8", "replace")).split())
        text = re.sub(r"\s+([.,;:])", r"\1", text)
        if 8 <= len(text):
            out.setdefault(field, {}).setdefault(d, text[:600])
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
TEXT_FIELDS = list(TEXT_CONCEPTS.keys())
ALL_FIELDS = FIELDS + TEXT_FIELDS


# Which figures win for a year:
# - a year's own accounts (balance sheet date within 45 days of the year end) are
#   always applied, even when a later filing's comparative column got there first;
# - a later filing's comparative column never blanks or zeroes a figure the year
#   already has (small companies' comparatives often have no P&L, and "-" reads as 0);
# - a real, non-zero restated comparative still replaces a filed figure (restatements
#   correct errors), but never figures saved by you or Claude (source manual / pdf:claude).
_OWN_NEW = "(excluded.source_balance_date - excluded.period_end) <= 45"
_OWN_OLD = "(fp.source_balance_date is not null and (fp.source_balance_date - fp.period_end) <= 45 and not fp.period_inferred)"
_KEEP = f"(not {_OWN_NEW} and {_OWN_OLD})"   # a comparative arriving on top of a year's own figures
_SAVED = "(coalesce(fp.source, '') in ('manual', 'pdf:claude') or coalesce(fp.source, '') like 'manual%%')"
_SAVING = "(coalesce(excluded.source, '') in ('manual', 'pdf:claude'))"   # you or Claude saving figures now: always applied
# a year's own (older) accounts arriving after a newer filing's comparative: they fill gaps, but don't undo a restatement
_FILL = f"({_OWN_NEW} and not {_OWN_OLD} and fp.source_balance_date > excluded.source_balance_date and not {_SAVING})"


def year_as_staff(emp, period_end, turnover=None) -> bool:
    """A staff count that is really the year heading: equal to the accounts'
    year or the year before, unless turnover shows a company that big
    (£20k+ a head)."""
    try:
        yr = period_end.year
    except AttributeError:
        return False
    return emp in (yr, yr - 1) and not (turnover and float(turnover) >= 20_000 * emp)


def implausible_staff(emp, turnover) -> bool:
    """A large staff count with turnover far too small to pay them (under £5k a
    head): a misread, so left blank rather than inflating the revenue estimate."""
    return bool(emp and emp >= 500 and turnover is not None and 0 < float(turnover) < 5_000 * emp)


def _reread_staff(conn, rows) -> dict:
    """For cleared years filed as data, read the filing again from Companies House
    (the real staff figure is often tagged too) and fill the blank. Only where
    the filing link is held and the API key is set; the rest stay blank."""
    from .. import chapi

    done = missing = 0
    if not chapi.enabled():
        return {"data_years_reread": 0, "data_years_no_link": len(rows)}
    for r in rows:
        f = conn.execute("""select detail from filing where company_number = %s and type = 'AA'
                            and detail ? 'document' and abs((detail->>'made_up_date')::date - %s) <= 45
                            order by filed_on desc limit 1""", (r["company_number"], r["period_end"])).fetchone()
        link = (f or {}).get("detail", {}).get("document") if f else None
        if not link:
            missing += 1
            continue
        try:
            if "application/xhtml+xml" not in chapi._doc_formats(link):
                missing += 1
                continue
            raw = chapi._document(link, limit=20_000_000, accept="application/xhtml+xml")
            vals = (parse(raw) or {}).get(r["period_end"], {}) if raw else {}
        except Exception:
            vals = {}
        emp = vals.get("employees")
        if emp is not None:
            conn.execute("""update financial_period set employees = %s where company_number = %s and period_end = %s
                            and employees is null""", (emp, r["company_number"], r["period_end"]))
            done += 1
    return {"data_years_reread": done, "data_years_no_link": missing}


def fix_year_staff(conn) -> dict:
    """One-off: clear staff counts that are the year heading. Figures saved by
    you or Claude are never touched. The PDF years affected are read again
    (gaps only), and estimates and scores refreshed for those companies."""
    from .. import scoring
    from .companies import refresh_estimates

    rows = conn.execute("""
        update financial_period fp set employees = null
        where employees between 1990 and 2035
          and employees in (extract(year from period_end)::int, extract(year from period_end)::int - 1)
          and coalesce(source, '') not in ('manual', 'pdf:claude')
          and not (turnover is not null and turnover >= 20000 * employees)
        returning company_number, period_end""").fetchall()
    if rows:
        conn.execute("""insert into staff_year_cleared (company_number, period_end)
                        select unnest(%s::text[]), unnest(%s::date[]) on conflict do nothing""",
                     ([r["company_number"] for r in rows], [r["period_end"] for r in rows]))
    # Every cleared year still blank (this run's, and earlier ones) gets another read.
    todo = conn.execute("""select k.company_number, k.period_end from staff_year_cleared k
                           join financial_period fp using (company_number, period_end)
                           where fp.employees is null""").fetchall()
    nums = sorted({r["company_number"] for r in rows} | {r["company_number"] for r in todo})
    if not nums:
        return {"years": 0, "companies": 0}
    # Years read from a PDF: read again with the fixed reader (it only fills gaps).
    requeued = conn.execute("""delete from pdf_read r using (select unnest(%s::text[]) n, unnest(%s::date[]) p) x
                               where r.company_number = x.n and abs(r.made_up - x.p) <= 45
                                 and r.status = 'done' and r.method in ('text', 'ocr')""",
                            ([r["company_number"] for r in rows], [r["period_end"] for r in rows])).rowcount
    reread = _reread_staff(conn, todo)
    conn.execute("drop table if exists staff_fix")
    conn.execute("create temp table staff_fix (company_number text)")
    conn.execute("insert into staff_fix select unnest(%s::text[])", (nums,))
    refresh_estimates(conn, from_table="staff_fix")
    scoring.refresh_latest(conn, from_table="staff_fix")
    conn.commit()
    for n in nums:
        scoring.rescore(conn, company_number=n)
    conn.commit()
    return {"years": len(rows), "companies": len({r["company_number"] for r in rows}), "pdf_years_requeued": requeued, **reread}


def _merge_sql(cols) -> str:
    """The SET and WHERE of the upsert into financial_period, by the rule above."""
    def one(c):
        blank = f"excluded.{c} is null" if c in TEXT_FIELDS else f"(excluded.{c} is null or excluded.{c} = 0)"
        fblank = f"fp.{c} is null" if c in TEXT_FIELDS else f"(fp.{c} is null or fp.{c} = 0)"
        return (f"{c} = case when {_SAVING} then coalesce(excluded.{c}, fp.{c}) "
                f"when {_KEEP} and ({_SAVED} or {blank}) then coalesce(fp.{c}, excluded.{c}) "
                f"when {_FILL} then case when {fblank} then coalesce(excluded.{c}, fp.{c}) else fp.{c} end "
                f"else coalesce(excluded.{c}, fp.{c}) end")
    sets = ", ".join(one(c) for c in cols)
    return f"""period_inferred = false,
                source = case when ({_KEEP} or {_FILL}) and not {_SAVING} then fp.source else excluded.source end,
                source_balance_date = case when ({_KEEP} or {_FILL}) and not {_SAVING} then fp.source_balance_date else excluded.source_balance_date end,
                {sets}
            where fp.period_inferred or fp.source_balance_date is null or {_OWN_NEW}
               or {_KEEP} or excluded.source_balance_date >= fp.source_balance_date"""


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
                    source text, {", ".join([f"{f} numeric" for f in FIELDS] + [f"{f} text" for f in TEXT_FIELDS])})""")

    seen = matched = periods = changes = 0
    buf: list[tuple] = []
    BAD_INNER.clear()
    total_files = _count_members(paths)

    def flush():
        nonlocal periods, changes, buf
        if not buf:
            return
        with conn.cursor().copy(
            f"copy acc_stage (company_number, period_end, balance_date, source, {', '.join(ALL_FIELDS)}) from stdin"
        ) as cp:
            for r in buf:
                cp.write_row(r)
        if record_changes:
            changes += _batch_changes(conn, run_id)
        periods += conn.execute(f"""
            insert into financial_period as fp (company_number, period_end, period_inferred, source,
                source_balance_date, {', '.join(ALL_FIELDS)})
            select distinct on (company_number, period_end) company_number, period_end, false, source, balance_date,
                   {', '.join(ALL_FIELDS)}
            from acc_stage order by company_number, period_end, (balance_date - period_end) <= 45 desc, balance_date desc, source desc
            on conflict (company_number, period_end) do update set
                {_merge_sql(ALL_FIELDS)}""").rowcount
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
            buf.append((num, pe, bdate, f"accounts:{fname}", *[vals.get(f) for f in ALL_FIELDS]))
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
            "changes": changes, "skipped_files": list(BAD_INNER),
            "messages": [f"Skipped a damaged file inside the zip: {b}" for b in BAD_INNER]}


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
    cols = [k for k in ALL_FIELDS if vals.get(k) is not None]
    if not cols:
        return
    params = {"num": num, "pe": period_end, "src": source, "bd": balance_date or period_end, **{c: vals[c] for c in cols}}
    conn.execute(
        f"""insert into financial_period as fp (company_number, period_end, period_inferred, source, source_balance_date,
                {', '.join(cols)})
            values (%(num)s, %(pe)s, false, %(src)s, %(bd)s, {', '.join(f'%({c})s' for c in cols)})
            on conflict (company_number, period_end) do update set
              {_merge_sql(cols)}""",
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

                inner = _open_inner(z, info)
                if inner is None:
                    continue
                with inner:
                    for name, read in _zip_members(inner):
                        yield (name, read, None) if refs else (name, read)
            elif low.endswith((".html", ".xhtml", ".xml")):
                reader = (lambda i=info: z.read(i))
                yield (info.filename, reader, (path, info.filename)) if refs else (info.filename, reader)


# Daily zips inside a monthly zip that could not be opened (Companies House
# archives occasionally hold a damaged one); skipped, and reported by run().
BAD_INNER: list[str] = []


def _open_inner(z: zipfile.ZipFile, info) -> zipfile.ZipFile | None:
    import io

    try:
        with z.open(info) as f:
            return zipfile.ZipFile(io.BytesIO(f.read()))
    except (zipfile.BadZipFile, OSError, EOFError) as e:
        BAD_INNER.append(f"{info.filename} ({e})")
        return None


def _zip_members(z: zipfile.ZipFile):
    import io

    for info in z.infolist():
        if info.is_dir():
            continue
        low = info.filename.lower()
        if low.endswith(".zip"):
            inner = _open_inner(z, info)
            if inner is None:
                continue
            with inner:
                yield from _zip_members(inner)
        elif low.endswith((".html", ".xhtml", ".xml")):
            yield info.filename, (lambda i=info: z.read(i))
