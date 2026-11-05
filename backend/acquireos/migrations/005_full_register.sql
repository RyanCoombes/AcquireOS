-- Scale to the whole UK register (millions of companies).

create extension if not exists pg_trgm;
create index if not exists company_name_trgm_idx on company using gin (name gin_trgm_ops);
create index if not exists company_postcode_idx on company (postcode);
create index if not exists company_status_idx on company (status);

-- Which filing supplied each figure: an older filing never overwrites a
-- newer one, whatever order files are loaded in.
alter table financial_period add column source_balance_date date;
update financial_period set source_balance_date = case
    when period_inferred then period_end + interval '1 year' else period_end end;

-- Date of the Companies House register snapshot the company row came from,
-- so an older snapshot cannot roll back a newer status or name.
alter table company add column register_date date;

-- Latest filed figures per company, kept up to date after each load so lists
-- do not have to scan every period.
create table company_latest (
    company_number   text primary key references company on delete cascade,
    period_end       date,
    employees        integer,
    turnover         numeric,
    operating_profit numeric,
    net_assets       numeric,
    cash             numeric,
    net_assets_prev  numeric,
    staff_trend      integer[]
);

create index if not exists person_reg_idx on person (registration_number) where registration_number is not null;
create index if not exists parent_psc_parent_idx on parent_psc (parent_number);
create index if not exists company_person_active_idx on company_person (company_number) where ceased_on is null;
create index if not exists company_change_kind_idx on company_change (kind, detected_at desc);
create index if not exists financial_period_company_idx on financial_period (company_number, period_end desc);
create index if not exists company_link_a_idx on company_link (a);

-- Same rules as normalise.address_key in Python.
create or replace function ao_address_key(addr text) returns text language sql immutable as $$
    select nullif(trim(regexp_replace(regexp_replace(
        regexp_replace(upper(coalesce(addr, '')),
            '\m(UNITED KINGDOM|UK|ENGLAND|WALES|SCOTLAND|GREAT BRITAIN)\M', ' ', 'g'),
        '[^A-Z0-9]+', ' ', 'g'), '\s+', ' ', 'g')), '')
$$;

create or replace function ao_region(pc text) returns text language sql immutable as $$
    select case
        when pc is null or pc = '' then null
        when substring(upper(pc) from '^([A-Z]{1,2})[0-9]') in ('CF','SA','NP','LL','LD') then 'Wales'
        when substring(upper(pc) from '^([A-Z]{1,2})[0-9]') in ('AB','DD','DG','EH','FK','G','HS','IV','KA','KW','KY','ML','PA','PH','TD','ZE') then 'Scotland'
        when substring(upper(pc) from '^([A-Z]{1,2})[0-9]') = 'BT' then 'Northern Ireland'
        when substring(upper(pc) from '^([A-Z]{1,2})[0-9]') is not null then 'England'
    end
$$;

-- Same rules as normalise.company_name_key in Python.
create or replace function ao_company_name_key(n text) returns text language sql immutable as $$
    select trim(regexp_replace(regexp_replace(regexp_replace(
        replace(upper(coalesce(n, '')), '&', ' AND '),
        '\m(LIMITED|LTD|PLC|LLP|HOLDINGS?|GROUP|COMPANY|CO)\M\.?', ' ', 'g'),
        '[^A-Z0-9 ]+', ' ', 'g'), '\s+', ' ', 'g'))
$$;
