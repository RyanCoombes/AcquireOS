-- Register-wide summaries that take seconds to compute on millions of rows
-- (SIC code counts, coverage): worked out once after each data load and read
-- from here by the pages, instead of recomputed on a timer.
create table if not exists stats (
    key        text primary key,
    value      jsonb not null,
    updated_at timestamptz not null default now()
);

-- Planner's row estimate for a big table: instant, within a percent or so
-- after ANALYZE, instead of count(*) over millions of rows.
create or replace function ao_rowcount(t text) returns bigint language sql stable as $$
    select greatest(reltuples, 0)::bigint from pg_class where oid = t::regclass
$$;
