-- Several buy boxes, your own scoring criteria, saved searches per buy box.

-- Your scores (0-5) for your own criteria. They belong to the company, not to
-- a buy box: each buy box decides how much a criterion counts, so a company
-- is never scored twice for the same thing. User-owned.
create table manual_score (
    user_id        integer not null references app_user,
    company_number text not null references company on delete restrict,
    criterion_key  text not null,
    value          smallint not null check (value between 0 and 5),
    note           text,
    updated_at     timestamptz not null default now(),
    primary key (user_id, company_number, criterion_key)
);

alter table buy_box add column description text;
alter table buy_box add column template text;
alter table buy_box add column scored_at timestamptz;
alter table buy_box add column created_at timestamptz not null default now();

alter table saved_search add column buy_box_id integer references buy_box on delete set null;
alter table saved_search drop constraint if exists saved_search_user_id_name_key;
create unique index saved_search_name_idx on saved_search (user_id, coalesce(buy_box_id, 0), name);

-- Scores are now stored only for companies in a buy box's universe, plus your
-- pipeline and anything you have scored yourself.
update buy_box set scored_at = (select max(computed_at) from score where score.buy_box_id = buy_box.id);
