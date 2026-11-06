-- Background Companies House sync.
-- ch_rate: one shared request schedule, so the web app and the scheduler
-- together stay inside the API's limit (600 requests per 5 minutes).
create table if not exists ch_rate (id int primary key, next_at timestamptz not null default now());
insert into ch_rate values (1, now()) on conflict do nothing;

-- checked_at: last time we looked for changes (a light check or a full fetch).
alter table ch_fetch add column if not exists checked_at timestamptz;
alter table ch_fetch add column if not exists etag text;
update ch_fetch set checked_at = fetched_at where checked_at is null;
create index if not exists ch_fetch_checked_idx on ch_fetch (checked_at);

-- Where a change was seen: null for the bulk files, 'api' for Companies House API checks.
alter table company_change add column if not exists source text;

-- Small settings: sync paused, when changes were last looked at, sync heartbeat.
create table if not exists app_setting (
    key        text primary key,
    value      jsonb not null,
    updated_at timestamptz not null default now()
);
