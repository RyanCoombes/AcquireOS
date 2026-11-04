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
from .tables import detect, read_rows

ALIASES: dict[str, list[str]] = {
    "company_number": ["company_number", "companynumber", "company_no", "crn", "number", "~company_number", "~company_no"],
    "name": ["company_name", "companyname", "name", "~company_name"],
    "status": ["company_status", "status"],
    "company_type": ["company_type", "type"],
    "company_subtype": ["company_subtype", "subtype"],
    "incorporation_date": ["incorporation_date", "date_of_creation", "incorporated", "~incorporat"],
    "sic": ["nature_of_business", "sic_codes", "sic", "siccode_sictext_1", "~sic"],
    "address": ["registered_office_address", "registered_address", "address", "~registered_office"],
    "postcode": ["postcode", "post_code", "registeredaddress_postcode"],
    "wales_flag": ["wales_flag", "in_wales", "wales"],
    "region": ["region"],
    "review_tier": ["review_tier", "tier"],
    "accounts_made_up_to": ["accounts_made_up_to", "period_end", "accounts_date", "last_accounts"],
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


def preview(path: Path, sheet: str | None = None) -> dict:
    headers, rows = read_rows(path, sheet)
    mapping = detect(headers, ALIASES)
    return {
        "headers": headers,
        "mapping": mapping,
        "row_count": len(rows),
        "sample": rows[:5],
        "unmapped": [h for h in headers if h not in mapping.values()],
        "fields": list(ALIASES.keys()),
        "problems": [] if mapping.get("company_number") else ["No company number column found."],
    }


def run(conn, path: Path, mapping: dict | None = None, sheet: str | None = None, source: str | None = None) -> dict:
    headers, rows = read_rows(path, sheet)
    mapping = mapping or detect(headers, ALIASES)
    if not mapping.get("company_number"):
        raise ValueError("No company number column found. Map one before importing.")
    source = source or path.name
    mapped_headers = {h for h in mapping.values() if h}
    run_id = conn.execute(
        "insert into import_run (kind, filename, rows_in) values ('companies', %s, %s) returning id",
        (source, len(rows)),
    ).fetchone()["id"]

    def get(row, field):
        h = mapping.get(field)
        return row.get(h) if h else None

    ok, skipped, messages = 0, 0, []
    for i, row in enumerate(rows, start=2):
        num = n.company_number(get(row, "company_number"))
        name = n.text(get(row, "name"))
        if not num:
            skipped += 1
            if len(messages) < 50:
                messages.append(f"Row {i}: no company number, skipped.")
            continue
        address = n.text(get(row, "address"))
        pc = n.text(get(row, "postcode")) or n.postcode(address)
        pc = pc.upper() if pc else None
        flag = n.known_address_flag(pc)
        region = n.text(get(row, "region"))
        if not region and mapping.get("wales_flag") and n.yes(get(row, "wales_flag")):
            region = "Wales"
        extra = {
            h: _jsonable(v) for h, v in row.items() if h not in mapped_headers and v not in (None, "")
        }
        conn.execute(
            """
            insert into company (company_number, name, status, company_type, company_subtype,
                incorporation_date, sic_codes, nature_of_business, registered_address, postcode,
                address_key, address_flag, region, review_tier, extra, source)
            values (%(num)s, %(name)s, %(status)s, %(type)s, %(subtype)s, %(inc)s, %(sic)s,
                %(nob)s, %(addr)s, %(pc)s, %(akey)s, %(flag)s, %(region)s, %(tier)s, %(extra)s, %(source)s)
            on conflict (company_number) do update set
                name = coalesce(excluded.name, company.name),
                status = coalesce(excluded.status, company.status),
                company_type = coalesce(excluded.company_type, company.company_type),
                company_subtype = coalesce(excluded.company_subtype, company.company_subtype),
                incorporation_date = coalesce(excluded.incorporation_date, company.incorporation_date),
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
                updated_at = now()
            """,
            {
                "num": num,
                "name": name or num,
                "status": (n.text(get(row, "status")) or "").lower() or None,
                "type": n.text(get(row, "company_type")),
                "subtype": n.text(get(row, "company_subtype")),
                "inc": n.parse_date(get(row, "incorporation_date")),
                "sic": n.sic_codes(get(row, "sic")),
                "nob": n.text(get(row, "sic")),
                "addr": address,
                "pc": pc,
                "akey": n.address_key(address),
                "flag": flag[0] if flag else None,
                "region": region,
                "tier": n.text(get(row, "review_tier")),
                "extra": json.dumps(extra),
                "source": source,
            },
        )
        _financials(conn, num, row, get, source)
        ok += 1

    conn.execute(
        "update import_run set rows_ok=%s, rows_skipped=%s, messages=%s, finished_at=now() where id=%s",
        (ok, skipped, json.dumps(messages), run_id),
    )
    refresh_estimates(conn)
    flag_mass_addresses(conn)
    return {"run_id": run_id, "rows_in": len(rows), "rows_ok": ok, "rows_skipped": skipped, "messages": messages}


def _financials(conn, num, row, get, source):
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
    if period and any(v is not None for v in values.values()):
        _upsert_period(conn, num, period, False, values, source)
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
        _upsert_period(conn, num, prev_end, True, prev, source)

    low, high = n.number(get(row, "est_revenue_low")), n.number(get(row, "est_revenue_high"))
    if low and high and low > 0:
        conn.execute(
            """insert into estimate (company_number, revenue_low, revenue_high, basis, method)
               values (%s, %s, %s, 'estimated', %s)
               on conflict (company_number) do update set revenue_low=excluded.revenue_low,
                 revenue_high=excluded.revenue_high, basis=excluded.basis, method=excluded.method, updated_at=now()""",
            (num, low, high, "Imported estimate from your search file"),
        )


def _upsert_period(conn, num, period, inferred, values, source):
    cols = [k for k, v in values.items() if v is not None]
    if not cols:
        return
    col_sql = ", ".join(cols)
    val_sql = ", ".join(f"%({c})s" for c in cols)
    upd = ", ".join(f"{c} = excluded.{c}" for c in cols)
    params = {**{c: values[c] for c in cols}, "num": num, "period": period, "inferred": inferred, "source": source}
    # Never let an inferred period overwrite a real one.
    where = "where financial_period.period_inferred" if inferred else ""
    conn.execute(
        f"""insert into financial_period (company_number, period_end, period_inferred, source, {col_sql})
            values (%(num)s, %(period)s, %(inferred)s, %(source)s, {val_sql})
            on conflict (company_number, period_end) do update set
              period_inferred = excluded.period_inferred, source = excluded.source, {upd} {where}""",
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
        select l.company_number, l.employees * %s, l.employees * %s, 'estimated', %s
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
