-- Revenue per head learned from companies that file turnover, by industry (SIC division)
-- and staff band; '*' rows are the wider fallbacks. Used for staff-based estimates.
create table if not exists rph_benchmark (
    division   text not null,
    band       text not null,
    n          integer not null,
    p25        numeric not null,
    p50        numeric not null,
    p75        numeric not null,
    updated_at timestamptz not null default now(),
    primary key (division, band)
);

-- Automatic plausibility checks raise data issues once per company, check and year.
alter table data_issue add column if not exists check_key text;
create unique index if not exists data_issue_check_idx on data_issue (company_number, check_key) where check_key is not null;

-- How far a company's data can be relied on: points for filed figures, fresh accounts,
-- traced owners and research; less for open data issues.
create or replace function ao_data_trust(num text) returns jsonb language sql stable as $$
with l as (
    select period_end, turnover, employees from financial_period
    where company_number = num and not period_inferred order by period_end desc limit 1
), e as (select basis, method from estimate where company_number = num),
o as (select ownership_type from company_ownership where company_number = num),
en as (select website from enrichment where company_number = num),
iss as (select count(*) as n from data_issue where company_number = num and status = 'open'),
parts as (
    select 'revenue' as k, 30 as max,
           case when (select turnover from l) > 0 then 30
                when (select method from e) like '%own revenue per head%' or (select method from e) like 'Last filed%' then 20
                when (select basis from e) is not null then 8 else 0 end as pts,
           case when (select turnover from l) > 0 then 'Revenue as filed'
                when (select method from e) like '%own revenue per head%' or (select method from e) like 'Last filed%'
                     then 'Revenue estimated from its own past accounts'
                when (select basis from e) is not null then 'Revenue is an estimate' else 'No revenue figure' end as label
    union all
    select 'staff', 20,
           case when (select employees from l) is not null and (select period_end from l) > current_date - 730 then 20
                when (select employees from l) is not null then 10 else 0 end,
           case when (select employees from l) is not null and (select period_end from l) > current_date - 730 then 'Staff from recent accounts'
                when (select employees from l) is not null then 'Staff from older accounts' else 'No staff figure' end
    union all
    select 'accounts', 15,
           case when (select period_end from l) > current_date - 640 then 15 when (select period_end from l) is not null then 5 else 0 end,
           case when (select period_end from l) > current_date - 640 then 'Accounts up to date'
                when (select period_end from l) is not null then 'Accounts out of date' else 'No accounts held' end
    union all
    select 'owners', 15,
           case when coalesce((select ownership_type from o), 'unknown') <> 'unknown' then 15 else 0 end,
           case when coalesce((select ownership_type from o), 'unknown') <> 'unknown' then 'Owners traced' else 'Owners not traced' end
    union all
    select 'website', 10, case when (select website from en) is not null then 10 else 0 end,
           case when (select website from en) is not null then 'Website confirmed' else 'No website confirmed' end
    union all
    select 'research', 10,
           case when exists (select 1 from research r where r.company_number = num) then 10 else 0 end,
           case when exists (select 1 from research r where r.company_number = num) then 'Researched' else 'Not researched yet' end
    union all
    select 'issues', 0, -least(30, 10 * (select n from iss)::int),
           case when (select n from iss) > 0 then (select n from iss) || ' open data issue' || case when (select n from iss) > 1 then 's' else '' end
                else 'No open data issues' end
)
select jsonb_build_object('score', greatest(0, sum(pts)),
                          'parts', jsonb_agg(jsonb_build_object('key', k, 'label', label, 'points', pts, 'max', max)))
from parts
$$;
