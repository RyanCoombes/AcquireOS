-- Companies House Streaming API: companies we hold API details for (or are
-- pursuing) that the stream says have changed, waiting for a re-fetch.
create table if not exists ch_dirty (
    company_number text primary key,
    first_at       timestamptz not null default now(),
    last_at        timestamptz not null default now(),
    kinds          text[] not null default '{}'
);
create index if not exists ch_dirty_first_idx on ch_dirty (first_at);
