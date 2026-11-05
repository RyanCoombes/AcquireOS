-- Matching a parent company named on a PSC record (no number filed) to the
-- register by name. Keeps HOLDINGS/GROUP, so "ABC Holdings" is not "ABC".
create or replace function ao_company_name_exact(n text) returns text language sql immutable as $$
    select trim(regexp_replace(regexp_replace(regexp_replace(
        replace(upper(coalesce(n, '')), '&', ' AND '),
        '\m(LIMITED|LTD|PLC|LLP|CYF|CCC)\M\.?', ' ', 'g'),
        '[^A-Z0-9 ]+', ' ', 'g'), '\s+', ' ', 'g'))
$$;
create index if not exists company_name_exact_idx on company (ao_company_name_exact(name));
