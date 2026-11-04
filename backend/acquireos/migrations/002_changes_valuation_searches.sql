-- Change tracking, valuation and saved searches.

-- What changed for a company between imports. Computed data: rebuilt only by
-- imports, never edited by hand.
create table company_change (
    id             bigserial primary key,
    company_number text not null references company on delete cascade,
    import_run_id  bigint references import_run on delete set null,
    kind           text not null,   -- new_company | status | name | address | sic | accounts | staff | owner
    field          text,
    old_value      text,
    new_value      text,
    detected_at    timestamptz not null default now()
);
create index company_change_company_idx on company_change (company_number, detected_at desc);
create index company_change_time_idx on company_change (detected_at desc);

alter table company add column dissolution_date date;
alter table company add column status_changed_at timestamptz;
alter table company add column last_accounts_date date;

-- Valuation results per buy box (assumptions live in buy_box.criteria).
alter table score add column ebitda_low numeric;
alter table score add column ebitda_high numeric;
alter table score add column value_low numeric;
alter table score add column value_high numeric;
alter table score add column value_basis text;

-- User-owned: my own valuation assumptions for one company.
alter table user_company add column valuation jsonb not null default '{}';

-- User-owned: saved filter sets for the targets list.
create table saved_search (
    id         serial primary key,
    user_id    integer not null references app_user,
    name       text not null,
    params     jsonb not null,
    created_at timestamptz not null default now(),
    unique (user_id, name)
);
