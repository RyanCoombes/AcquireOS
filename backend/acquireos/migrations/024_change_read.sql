-- Changes you have marked as read one by one ("mark all as read" moves the
-- changes_seen_at time in app_setting instead).
create table if not exists change_read (
    change_id bigint primary key references company_change on delete cascade,
    read_at   timestamptz not null default now()
);
