"""Import company lists: the ranked Companies House CSV, the audit workbook,
or any CSV/Excel file with a company number column.

Columns the importer recognises go into proper fields. Everything else is
kept in company.extra so nothing from your files is thrown away.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .. import normalise as n
from .tables import detect, head_rows, open_table

ALIASES: dict[str, list[str]] = {
    "company_number": ["company_number", "companynumber", "company_no", "crn", "number", "~company_number", "~company_no"],
    "name": ["company_name", "companyname", "name", "~company_name"],
    "status": ["company_status", "companystatus", "status"],
    "dissolution_date": ["dissolution_date", "dissolutiondate", "date_of_cessation"],
    "company_type": ["company_type", "companycategory", "company_category", "type"],
    "company_subtype": ["company_subtype", "subtype"],
    "incorporation_date": ["incorporation_date", "incorporationdate", "date_of_creation", "incorporated", "~incorporat"],
    "sic": ["nature_of_business", "sic_codes", "sic", "siccode_sictext_1", "~sic"],
    "address": ["registered_office_address", "registered_address", "address", "~registered_office"],
    "postcode": ["postcode", "post_code", "regaddress_postcode", "registeredaddress_postcode"],
    "wales_flag": ["wales_flag", "in_wales", "wales"],
    "region": ["region"],
    "review_tier": ["review_tier", "tier"],
    "accounts_made_up_to": ["accounts_made_up_to", "accounts_lastmadeupdate", "period_end", "accounts_date", "last_accounts"],
    "employees": ["employees", "staff", "headcount", "average_employees"],
    "employees_prev": ["employees_prev", "staff_prev", "employees_previous"],
    "turnover": ["turnover", "revenue"],
    "profit_loss": ["profit_loss", "profit", "profit_after_tax"],
    "operating_profit": ["operating_profit", "ebit"],
    "net_assets": ["net_assets"],
    "net_assets_prev": ["net_assets_prev", "net_assets_previous"],
    "cash": ["cash", "cash_at_bank"],
    "debtors": ["debtors", "trade_debtors"],
    "dividends": ["dividends", "dividends_paid"],
    "est_revenue_low": ["est_revenue_low", "revenue_low"],
    "est_revenue_high": ["est_revenue_high", "revenue_high"],
}

# Per-head revenue range used when only staff numbers are known. It matches
# the range used in the original search scripts. Shown on every estimate.
REVENUE_PER_HEAD = (80_000, 150_000)
# Fewer rows than this and a "full register" file is treated as partial.
FULL_REGISTER_MIN_ROWS = 500_000


MULTI = {
    # field: header prefixes whose columns are joined, in order
    "sic": ["siccode_sictext_"],
    "address": ["regaddress_careof", "regaddress_pobox", "regaddress_addressline1", "regaddress_addressline2",
                "regaddress_posttown", "regaddress_county", "regaddress_postcode"],
}


def detect_mapping(headers: list[str]) -> dict:
    """Single columns by alias, plus the bulk file's split columns as lists."""
    from .tables import norm_header

    mapping = detect(headers, ALIASES)
    normed = {h: norm_header(h) for h in headers}
    for field, prefixes in MULTI.items():
        cols = [h for p in prefixes for h, nh in normed.items() if nh.startswith(p)]
        if len(cols) > 1 and (not mapping.get(field) or mapping[field] in cols):
            mapping[field] = cols
    return mapping


def preview(path: Path, sheet: str | None = None) -> dict:
    headers, rows, count = head_rows(path, sheet)
    mapping = detect_mapping(headers)
    return {
        "headers": headers,
        "mapping": mapping,
        "row_count": count,
        "sample": rows[:5],
        "unmapped": [h for h in headers if h not in _used(mapping)],
        "fields": list(ALIASES.keys()),
        "problems": [] if mapping.get("company_number") else ["No company number column found."],
    }


def _used(mapping: dict) -> set[str]:
    out = set()
    for v in mapping.values():
        if isinstance(v, list):
            out.update(v)
        elif v:
            out.add(v)
    return out


TRACKED = {"name": "name", "status": "status", "registered_address": "address", "sic_codes": "sic"}


def universe_filter(criteria: dict):
    """Return a test(row_values) -> bool for adding new companies."""
    import re as _re
    from datetime import date as _date

    u = (criteria or {}).get("universe") or {}
    sic = tuple(u.get("sic_prefixes") or ())
    ksic = tuple(u.get("keyword_sic_prefixes") or ())
    kw = [k.lower() for k in u.get("name_keywords") or []]
    kw_re = _re.compile(r"\b(" + "|".join(_re.escape(k) for k in kw) + r")\b", _re.I) if kw else None
    areas = {a.upper() for a in u.get("postcode_areas") or []}
    min_years = int(u.get("min_years") or 0)
    today = _date.today()

    def test(v: dict) -> bool:
        if (v.get("status") or "active") != "active":
            return False
        if areas and n.postcode_area(v.get("postcode")) not in areas:
            return False
        inc = v.get("inc")
        if min_years and inc and (today - inc).days < min_years * 365.25:
            return False
        codes = v.get("sic") or []
        if sic and any(c.startswith(sic) for c in codes):
            return True
        if kw_re and (not ksic or any(c.startswith(ksic) for c in codes)) and kw_re.search(v.get("name") or ""):
            return True
        return not sic and not kw_re

    return test


def run(conn, path: Path, mapping: dict | None = None, sheet: str | None = None, source: str | None = None,
        only_existing: bool = False, universe: bool = False, full_register: bool = False) -> dict:
    """Import or refresh companies.

    only_existing: update companies already in the database and ignore the
    rest (use this with the full Companies House bulk file).
    universe: add new companies only if they match the buy box "universe"
    (SIC codes, name keywords, postcode areas, age). Existing ones are always
    updated. Use with the full Companies House file.
    full_register: the file is the complete live register, so companies in
    the database that are missing from it have left the register.
    Differences from what was stored before are recorded in company_change.
    """
    headers, rows = open_table(path, sheet)
    mapping = mapping or detect_mapping(headers)
    if not mapping.get("company_number"):
        raise ValueError("No company number column found. Map one before importing.")
    source = source or path.name
    mapped_headers = _used(mapping)
    run_id = conn.execute(
        "insert into import_run (kind, filename) values ('companies', %s) returning id", (source,),
    ).fetchone()["id"]

    # Existing rows are fetched per chunk of the file, so a small file does not
    # load millions of companies into memory.
    before: dict = {}
    latest_period: dict = {}
    first_import = conn.execute("select 1 from company limit 1").fetchone() is None

    def prefetch(items):
        import itertools

        it = iter(items)
        while True:
            chunk = list(itertools.islice(it, 2000))
            if not chunk:
                return
            nums = list({n.company_number(get(r, "company_number")) for _, r in chunk} - {None})
            before.clear()
            latest_period.clear()
            for r in conn.execute(
                """select company_number, name, status, registered_address, address_key, sic_codes
                   from company where company_number = any(%s)""", (nums,)):
                before[r["company_number"]] = r
            for r in conn.execute(
                """select c.company_number, greatest(c.last_accounts_date, fp.period_end) as period_end, fp.employees
                   from company c left join lateral (
                       select period_end, employees from financial_period f
                       where f.company_number = c.company_number and not f.period_inferred
                       order by period_end desc limit 1) fp on true
                   where c.company_number = any(%s)
                     and (c.last_accounts_date is not null or fp.period_end is not null)""", (nums,)):
                latest_period[r["company_number"]] = r
            yield from chunk
    in_universe = None
    if universe:
        from ..scoring import active_buy_box, merged

        in_universe = universe_filter(merged(active_buy_box(conn)["criteria"]))
    seen_numbers: set[str] = set()

    def get(row, field):
        h = mapping.get(field)
        if isinstance(h, list):
            parts = [str(row.get(x)).strip() for x in h if row.get(x) not in (None, "")]
            return ", ".join(p for p in parts if p) or None
        return row.get(h) if h else None

    ok, skipped, not_in_list, messages, changes = 0, 0, 0, [], 0
    rows_in = 0
    sic_texts: set[str] = set()
    for i, row in prefetch(enumerate(rows, start=2)):
        rows_in += 1
        num = n.company_number(get(row, "company_number"))
        name = n.text(get(row, "name"))
        if not num:
            skipped += 1
            if len(messages) < 50:
                messages.append(f"Row {i}: no company number, skipped.")
            continue
        seen_numbers.add(num)
        if only_existing and num not in before:
            not_in_list += 1
            continue
        address = n.text(get(row, "address"))
        pc = n.text(get(row, "postcode")) or n.postcode(address)
        pc = pc.upper() if pc else None
        if in_universe is not None and num not in before:
            if not in_universe({"status": (n.text(get(row, "status")) or "active").lower(), "postcode": pc,
                                "inc": n.parse_date(get(row, "incorporation_date")),
                                "sic": n.sic_codes(get(row, "sic")), "name": name}):
                not_in_list += 1
                continue
        flag = n.known_address_flag(pc)
        region = n.text(get(row, "region"))
        if not region and mapping.get("wales_flag") and n.yes(get(row, "wales_flag")):
            region = "Wales"
        if not region:
            region = n.region_for(pc)
        extra = {
            h: _jsonable(v) for h, v in row.items() if h not in mapped_headers and v not in (None, "")
        }
        status = (n.text(get(row, "status")) or "").lower() or None
        sic_raw = n.text(get(row, "sic"))
        if sic_raw and " - " in sic_raw and len(sic_texts) < 5000:
            sic_texts.add(sic_raw)
        new = {
            "name": name,
            "status": status,
            "registered_address": address,
            "sic_codes": n.sic_codes(get(row, "sic")),
        }
        old = before.get(num)
        status_changed = False
        if old is not None:
            for col, kind in TRACKED.items():
                nv, ov = new[col], old[col]
                if not nv:
                    continue
                if col == "registered_address":
                    if n.address_key(nv) == old["address_key"]:
                        continue
                elif col == "sic_codes":
                    if sorted(nv) == sorted(ov or []):
                        continue
                    nv, ov = ", ".join(nv), ", ".join(ov or [])
                elif (ov or "").strip().lower() == str(nv).strip().lower():
                    continue
                _change(conn, num, run_id, kind, col, ov, nv)
                changes += 1
                status_changed = status_changed or col == "status"

        conn.execute(
            """
            insert into company (company_number, name, status, company_type, company_subtype,
                incorporation_date, dissolution_date, sic_codes, nature_of_business, registered_address, postcode,
                address_key, address_flag, region, review_tier, extra, source, last_accounts_date)
            values (%(num)s, %(name)s, %(status)s, %(type)s, %(subtype)s, %(inc)s, %(dis)s, %(sic)s,
                %(nob)s, %(addr)s, %(pc)s, %(akey)s, %(flag)s, %(region)s, %(tier)s, %(extra)s, %(source)s, %(acc)s)
            on conflict (company_number) do update set
                name = coalesce(excluded.name, company.name),
                status = coalesce(excluded.status, company.status),
                status_changed_at = case when %(status_changed)s then now() else company.status_changed_at end,
                company_type = coalesce(excluded.company_type, company.company_type),
                company_subtype = coalesce(excluded.company_subtype, company.company_subtype),
                incorporation_date = coalesce(excluded.incorporation_date, company.incorporation_date),
                dissolution_date = coalesce(excluded.dissolution_date, company.dissolution_date),
                sic_codes = case when cardinality(excluded.sic_codes) > 0 then excluded.sic_codes else company.sic_codes end,
                nature_of_business = coalesce(excluded.nature_of_business, company.nature_of_business),
                registered_address = coalesce(excluded.registered_address, company.registered_address),
                postcode = coalesce(excluded.postcode, company.postcode),
                address_key = coalesce(excluded.address_key, company.address_key),
                address_flag = coalesce(excluded.address_flag, company.address_flag),
                region = coalesce(excluded.region, company.region),
                review_tier = coalesce(excluded.review_tier, company.review_tier),
                extra = company.extra || excluded.extra,
                source = excluded.source,
                last_accounts_date = greatest(company.last_accounts_date, excluded.last_accounts_date),
                updated_at = now()
            """,
            {
                "num": num,
                "name": name or num,
                "status": status,
                "status_changed": status_changed,
                "type": n.text(get(row, "company_type")),
                "subtype": n.text(get(row, "company_subtype")),
                "inc": n.parse_date(get(row, "incorporation_date")),
                "dis": n.parse_date(get(row, "dissolution_date")),
                "sic": new["sic_codes"],
                "nob": n.text(get(row, "sic")),
                "addr": address,
                "pc": pc,
                "akey": n.address_key(address),
                "flag": flag[0] if flag else None,
                "region": region,
                "tier": n.text(get(row, "review_tier")),
                "extra": json.dumps(extra),
                "source": source,
                "acc": n.parse_date(get(row, "accounts_made_up_to")),
            },
        )
        if old is None and not first_import:
            _change(conn, num, run_id, "new_company", None, None, "Added to your list")
            changes += 1
        changes += _financials(conn, num, row, get, source, latest_period.get(num) if old else None, run_id)
        ok += 1

    if full_register:
        conn.execute("drop table if exists seen_numbers; create temp table seen_numbers (num text primary key)")
        with conn.cursor().copy("copy seen_numbers (num) from stdin") as cp:
            for x in seen_numbers:
                cp.write_row((x,))
        prior = {r["company_number"]: r for r in conn.execute(
            """select company_number, status from company c
               where not exists (select 1 from seen_numbers s where s.num = c.company_number)""")}
        before = prior
        missing = list(prior)
        if rows_in < FULL_REGISTER_MIN_ROWS:
            messages.append("Not treated as the full register (too few rows), so missing companies were not flagged.")
        else:
            for num in missing:
                if (before[num]["status"] or "") in ("removed from register", "dissolved"):
                    continue
                _change(conn, num, run_id, "status", "status", before[num]["status"], "removed from register")
                changes += 1
            if missing:
                conn.execute(
                    """update company set status = 'removed from register', status_changed_at = now()
                       where company_number = any(%s) and coalesce(status, '') not in ('removed from register', 'dissolved')""",
                    (missing,),
                )
                messages.append(f"{len(missing):,} companies are no longer on the live register (usually dissolved).")
    if not_in_list:
        messages.insert(0, f"{not_in_list:,} rows were outside your list{' and universe' if universe else ''} and were skipped.")
    conn.execute(
        "update import_run set rows_in=%s, rows_ok=%s, rows_skipped=%s, messages=%s, finished_at=now() where id=%s",
        (rows_in, ok, skipped + not_in_list, json.dumps(messages), run_id),
    )
    refresh_estimates(conn)
    flag_mass_addresses(conn)
    from .. import sic as sic_mod

    sic_mod.seed(conn)
    sic_mod.learn(conn, sic_texts)
    return {"run_id": run_id, "rows_in": rows_in, "rows_ok": ok, "rows_skipped": skipped + not_in_list,
            "changes": changes, "messages": messages}


def _change(conn, num, run_id, kind, field, old, new):
    conn.execute(
        """insert into company_change (company_number, import_run_id, kind, field, old_value, new_value)
           values (%s, %s, %s, %s, %s, %s)""",
        (num, run_id, kind, field, None if old is None else str(old), None if new is None else str(new)),
    )


def _financials(conn, num, row, get, source, latest=None, run_id=None) -> int:
    """Store the period(s) in this row. Returns the number of changes noted."""
    noted = 0
    period = n.parse_date(get(row, "accounts_made_up_to"))
    values = {
        "employees": n.integer(get(row, "employees")),
        "turnover": n.number(get(row, "turnover")),
        "profit_loss": n.number(get(row, "profit_loss")),
        "operating_profit": n.number(get(row, "operating_profit")),
        "net_assets": n.number(get(row, "net_assets")),
        "cash": n.number(get(row, "cash")),
        "debtors": n.number(get(row, "debtors")),
        "dividends": n.number(get(row, "dividends")),
    }
    if period and latest and period > latest["period_end"]:
        _change(conn, num, run_id, "accounts", "period_end", latest["period_end"], period)
        noted += 1
        if values["employees"] is not None and latest["employees"] is not None and values["employees"] != latest["employees"]:
            _change(conn, num, run_id, "staff", "employees", latest["employees"], values["employees"])
            noted += 1
    if period and any(v is not None for v in values.values()):
        _upsert_period(conn, num, period, False, values, source, period)
    prev = {
        "employees": n.integer(get(row, "employees_prev")),
        "net_assets": n.number(get(row, "net_assets_prev")),
    }
    if period and any(v is not None for v in prev.values()):
        # The ranked file gives "previous year" figures without a date. We
        # assume the prior period ended a year earlier and mark it inferred.
        try:
            prev_end = period.replace(year=period.year - 1)
        except ValueError:  # 29 February
            prev_end = date(period.year - 1, 2, 28)
        _upsert_period(conn, num, prev_end, True, prev, source, period)

    low, high = n.number(get(row, "est_revenue_low")), n.number(get(row, "est_revenue_high"))
    if low and high and low > 0:
        conn.execute(
            """insert into estimate (company_number, revenue_low, revenue_high, basis, method)
               values (%s, %s, %s, 'estimated', %s)
               on conflict (company_number) do update set revenue_low=excluded.revenue_low,
                 revenue_high=excluded.revenue_high, basis=excluded.basis, method=excluded.method, updated_at=now()""",
            (num, low, high, "Imported estimate from your search file"),
        )
    return noted


def _upsert_period(conn, num, period, inferred, values, source, balance_date=None):
    cols = [k for k, v in values.items() if v is not None]
    if not cols:
        return
    col_sql = ", ".join(cols)
    val_sql = ", ".join(f"%({c})s" for c in cols)
    upd = ", ".join(f"{c} = excluded.{c}" for c in cols)
    params = {**{c: values[c] for c in cols}, "num": num, "period": period, "inferred": inferred, "source": source,
              "bd": balance_date or period}
    # Never let an inferred period overwrite a real one, or an older filing a newer one.
    where = ("where financial_period.period_inferred" if inferred else
             "where financial_period.period_inferred or financial_period.source_balance_date is null "
             "or excluded.source_balance_date >= financial_period.source_balance_date")
    conn.execute(
        f"""insert into financial_period (company_number, period_end, period_inferred, source, source_balance_date, {col_sql})
            values (%(num)s, %(period)s, %(inferred)s, %(source)s, %(bd)s, {val_sql})
            on conflict (company_number, period_end) do update set
              period_inferred = excluded.period_inferred, source = excluded.source,
              source_balance_date = excluded.source_balance_date, {upd} {where}""",
        params,
    )


def refresh_estimates(conn):
    """Fill in revenue ranges for companies with filed turnover or staff only."""
    conn.execute(
        """
        with latest as (
            select distinct on (company_number) company_number, turnover, employees
            from financial_period where not period_inferred
            order by company_number, period_end desc
        )
        insert into estimate (company_number, revenue_low, revenue_high, basis, method)
        select l.company_number, l.turnover, l.turnover, 'filed', 'Turnover as filed in latest accounts'
        from latest l where l.turnover is not null and l.turnover > 0
        on conflict (company_number) do update set revenue_low=excluded.revenue_low,
            revenue_high=excluded.revenue_high, basis='filed', method=excluded.method, updated_at=now()
        """
    )
    lo, hi = REVENUE_PER_HEAD
    conn.execute(
        """
        with latest as (
            select distinct on (company_number) company_number, employees
            from financial_period where not period_inferred and employees is not null
            order by company_number, period_end desc
        )
        insert into estimate (company_number, revenue_low, revenue_high, basis, method)
        select l.company_number, l.employees::numeric * %s, l.employees::numeric * %s, 'estimated', %s
        from latest l where l.employees > 0
        on conflict (company_number) do nothing
        """,
        (lo, hi, f"Staff × £{lo // 1000}k–£{hi // 1000}k revenue per head"),
    )


def flag_mass_addresses(conn):
    conn.execute(
        """
        update company c set address_flag = 'mass_address'
        from (select address_key from company where address_key is not null
              group by address_key having count(*) > %s) m
        where c.address_key = m.address_key and c.address_flag is null
        """,
        (n.MASS_ADDRESS_THRESHOLD,),
    )


def _jsonable(v):
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)
