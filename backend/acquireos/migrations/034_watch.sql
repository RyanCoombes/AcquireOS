-- Companies, owners and directors you watch. For owners and directors the
-- snapshot holds the companies they were involved in when last checked, so
-- new ones (and ones they leave) show up as changes.
create table if not exists watch (
    id          bigserial primary key,
    user_id     int not null default 1,
    kind        text not null check (kind in ('company', 'owner', 'director')),
    ref         text not null,      -- company number | person id | Companies House officer id
    label       text,
    snapshot    jsonb not null default '[]',
    created_at  timestamptz not null default now(),
    checked_at  timestamptz,
    fetched_at  timestamptz,        -- directors: appointments last fetched from Companies House
    unique (user_id, kind, ref)
);
