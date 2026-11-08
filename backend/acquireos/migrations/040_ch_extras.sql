-- Disqualified directors (from the API search and the disqualified-officers
-- stream), which directors have been checked, and more from each company's
-- record: PSC exemptions and UK establishments of overseas companies.
create table if not exists disqualified_officer (
    id            text primary key,          -- Companies House's id, e.g. natural/AbC123
    kind          text not null,             -- natural | corporate
    name          text not null,
    surname       text,
    forename      text,
    birth_date    date,
    disqualifications jsonb not null default '[]',
    source        text not null,             -- api | stream
    fetched_at    timestamptz not null default now()
);
create index if not exists disqualified_officer_match_idx on disqualified_officer (upper(surname), birth_date);

create table if not exists officer_disq_check (
    officer_key  text primary key,
    checked_at   timestamptz not null default now(),
    found        int not null default 0
);

alter table ch_fetch add column if not exists exemptions jsonb;
alter table ch_fetch add column if not exists uk_establishments jsonb;
alter table ch_fetch add column if not exists extras_version int not null default 0;
