"""Data accuracy: revenue per head learned from companies that file turnover, and
automatic plausibility checks that raise data issues for a person (or Claude) to look at."""
from __future__ import annotations

MIN_N = 30  # companies needed before a benchmark is used
BAND_SQL = ("case when {e} < 10 then '1–9' when {e} < 50 then '10–49' "
            "when {e} < 250 then '50–249' else '250+' end")


def refresh_benchmarks(conn) -> int:
    """Revenue per head (middle half and median) from each company's latest accounts that give
    both turnover and staff (last 4 years), by SIC division and staff band, with wider fallbacks.
    Companies that file turnover are mostly the larger ones, so these lean high for the smallest."""
    conn.execute("delete from rph_benchmark")
    conn.execute(
        f"""
        with latest as (
            select distinct on (f.company_number) f.company_number, f.turnover, f.employees
            from financial_period f
            where not f.period_inferred and f.turnover > 0 and f.employees > 0 and f.period_end > current_date - 1460
            order by f.company_number, f.period_end desc
        ), x as (
            select left(c.sic_codes[1], 2) as division, {BAND_SQL.format(e="l.employees")} as band,
                   l.turnover / l.employees as rph
            from latest l join company c on c.company_number = l.company_number
            where c.sic_codes[1] ~ '^[0-9]{{2}}' and l.turnover / l.employees between 10000 and 2000000
        )
        insert into rph_benchmark (division, band, n, p25, p50, p75)
        select case when grouping(division) = 1 then '*' else division end,
               case when grouping(band) = 1 then '*' else band end, count(*),
               -- to the nearest £1,000: a penny's drift must not rewrite every estimate and rescore
               round(percentile_cont(0.25) within group (order by rph)::numeric, -3),
               round(percentile_cont(0.5) within group (order by rph)::numeric, -3),
               round(percentile_cont(0.75) within group (order by rph)::numeric, -3)
        from x group by grouping sets ((division, band), (division), (band), ())
        having count(*) >= {MIN_N}
        """)
    return conn.execute("select count(*) as n from rph_benchmark").fetchone()["n"]


# Each check: key, SQL giving company_number, year (period_end) and the issue text.
_PAIRS = """
    with p as (
        select company_number, period_end, employees, turnover, net_assets,
               row_number() over (partition by company_number order by period_end desc) as rn
        from financial_period f
        where not period_inferred and company_number in (select company_number from company_best)
    ), two as (
        select a.company_number, a.period_end, a.employees as e1, b.employees as e0, a.turnover as t1, b.turnover as t0,
               a.net_assets as n1, b.net_assets as n0
        from p a join p b on b.company_number = a.company_number and a.rn = 1 and b.rn = 2
        where a.period_end - b.period_end between 180 and 460
    )"""
CHECKS = [
    ("staff_jump", _PAIRS + """
        select company_number, period_end,
               'Staff went from ' || e0 || ' to ' || e1 || ' in a year' as issue,
               'A misread figure is the usual cause (a group total, a figure from the notes, or the year before). Check the accounts.' as fix
        from two where e0 > 0 and e1 > 0 and abs(e1 - e0) >= 10 and (e1 >= 3 * e0 or e0 >= 3 * e1)"""),
    ("turnover_jump", _PAIRS + """
        select company_number, period_end,
               'Turnover went from £' || to_char(t0, 'FM999,999,999,990') || ' to £' || to_char(t1, 'FM999,999,999,990') || ' in a year' as issue,
               'Often a figure in £000s read as pounds (or the reverse). Check the accounts.' as fix
        from two where t0 > 0 and t1 > 0 and greatest(t0, t1) >= 1000000 and (t1 >= 10 * t0 or t0 >= 10 * t1)"""),
    ("net_assets_jump", _PAIRS + """
        select company_number, period_end,
               'Net assets went from £' || to_char(n0, 'FM999,999,999,990') || ' to £' || to_char(n1, 'FM999,999,999,990') || ' in a year' as issue,
               'Often a figure in £000s read as pounds (or the reverse). Check the balance sheet.' as fix
        from two where n0 <> 0 and n1 <> 0 and greatest(abs(n0), abs(n1)) >= 1000000
                   and (abs(n1) >= 50 * abs(n0) or abs(n0) >= 50 * abs(n1))"""),
    ("revenue_per_head", """
        with l as (
            select distinct on (company_number) company_number, period_end, turnover, employees
            from financial_period where not period_inferred and company_number in (select company_number from company_best)
            order by company_number, period_end desc)
        select company_number, period_end,
               'Revenue per head of £' || to_char(round(turnover / employees / 1000), 'FM999,990') || 'k looks unlikely ('
                 || employees || ' staff, £' || to_char(turnover, 'FM999,999,999,990') || ' turnover)' as issue,
               'Either the staff count or the turnover is probably misread (or staff are counted in another company of the group).' as fix
        from l where turnover > 0 and employees >= 5 and (turnover / employees > 1500000 or turnover / employees < 10000)"""),
]


def run_checks(conn) -> dict:
    """Raise a data issue for each implausible figure, once per company, check and year
    (a dismissed one is not raised again). Only companies scored against a buy box."""
    out = {}
    for key, sql in CHECKS:
        r = conn.execute(
            f"""with found as ({sql})
                insert into data_issue (company_number, issue, suggested_fix, created_by, check_key)
                select company_number, issue, fix, 'automatic check', %s || ':' || period_end from found
                on conflict (company_number, check_key) where check_key is not null do nothing""", (key,))
        out[key] = r.rowcount
    conn.commit()
    return out
