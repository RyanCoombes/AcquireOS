-- AcquireOS initial schema.
--
-- Two kinds of data live here and must never be mixed:
--   1. Shared, computed data (company, financial_period, estimate, person,
--      company_person, company_link, company_ownership, research, score).
--      Imports and refreshes may rewrite these freely.
--   2. User-owned data (app_user, buy_box, user_company, user_note, outreach).
--      Nothing an import or refresh does may overwrite or delete these.

create table company (
    company_number    text primary key,
    name              text not null,
    status            text,
    company_type      text,
    company_subtype   text,
    incorporation_date date,
    sic_codes         text[] not null default '{}',
    nature_of_business text,
    registered_address text,
    postcode          text,
    address_key       text,
    address_flag      text,            -- ch_default | formation_agent | mass_address
    region            text,
    review_tier       text,
    extra             jsonb not null default '{}',
    source            text,
    first_seen_at     timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);
create index company_name_idx on company using gin (to_tsvector('simple', name));
create index company_address_key_idx on company (address_key);
create index company_region_idx on company (region);

create table financial_period (
    company_number   text not null references company on delete cascade,
    period_end       date not null,
    period_inferred  boolean not null default false,
    employees        integer,
    turnover         numeric,
    profit_loss      numeric,
    operating_profit numeric,
    net_assets       numeric,
    cash             numeric,
    debtors          numeric,
    dividends        numeric,
    source           text,
    primary key (company_number, period_end)
);

create table estimate (
    company_number text primary key references company on delete cascade,
    revenue_low    numeric,
    revenue_high   numeric,
    basis          text not null,     -- filed | estimated
    method         text not null,
    updated_at     timestamptz not null default now()
);

create table person (
    id                  bigserial primary key,
    person_key          text not null unique,
    kind                text not null,  -- individual | corporate | legal | other
    name                text not null,
    birth_year          integer,
    birth_month         integer,
    registration_number text,
    country_registered  text,
    legal_form          text
);

create table company_person (
    id             bigserial primary key,
    row_key        text not null unique,
    company_number text not null references company on delete cascade,
    person_id      bigint not null references person on delete cascade,
    role           text not null,       -- psc | officer
    natures        text[] not null default '{}',
    notified_on    date,
    ceased_on      date,
    source         text
);
create index company_person_company_idx on company_person (company_number);
create index company_person_person_idx on company_person (person_id);

-- Links between companies. "b" may be a company outside this database
-- (for example a parent company), so it has no foreign key.
create table company_link (
    id          bigserial primary key,
    a           text not null references company on delete cascade,
    b           text not null,
    b_name      text,
    kind        text not null,      -- owned_by | shared_owner | shared_address
    via         text not null default '',
    confidence  text not null,      -- confirmed | likely | possible
    evidence    text,
    created_at  timestamptz not null default now(),
    unique (a, b, kind, via)
);
create index company_link_b_idx on company_link (b);

-- Owners of parent companies that are not in the company list themselves,
-- kept so ownership can be traced through holding companies.
create table parent_psc (
    parent_number text not null,
    person_id     bigint not null references person on delete cascade,
    natures       text[] not null default '{}',
    ceased_on     date,
    primary key (parent_number, person_id)
);

create table company_ownership (
    company_number     text primary key references company on delete cascade,
    ownership_type     text not null,   -- owner_held | group_owned | investor_backed | eot | trust | foreign_owned | unknown
    flags              text[] not null default '{}',
    owner_count        integer not null default 0,
    oldest_birth_year  integer,
    ultimate_owners    jsonb not null default '[]',
    explanation        text,
    updated_at         timestamptz not null default now()
);

create table research (
    id             bigserial primary key,
    company_number text not null references company on delete cascade,
    kind           text not null,      -- summary | classification | website | other
    content        text not null,
    source_url     text,
    source_label   text,
    retrieved_at   timestamptz not null default now(),
    created_by     text
);
create index research_company_idx on research (company_number);

create table import_run (
    id           bigserial primary key,
    kind         text not null,
    filename     text,
    rows_in      integer not null default 0,
    rows_ok      integer not null default 0,
    rows_skipped integer not null default 0,
    messages     jsonb not null default '[]',
    started_at   timestamptz not null default now(),
    finished_at  timestamptz
);

-- ---------------------------------------------------------------- user-owned

create table app_user (
    id         serial primary key,
    name       text not null,
    created_at timestamptz not null default now()
);
insert into app_user (name) values ('Me');

create table buy_box (
    id         serial primary key,
    user_id    integer not null references app_user,
    name       text not null,
    criteria   jsonb not null,
    is_active  boolean not null default true,
    updated_at timestamptz not null default now()
);

create table score (
    buy_box_id     integer not null references buy_box on delete cascade,
    company_number text not null references company on delete cascade,
    score          numeric not null,
    coverage       numeric not null,
    excluded       boolean not null default false,
    exclusion      text,
    reasons        jsonb not null default '[]',
    computed_at    timestamptz not null default now(),
    primary key (buy_box_id, company_number)
);
create index score_rank_idx on score (buy_box_id, excluded, score desc);

-- Deliberately ON DELETE RESTRICT: removing a company must never silently
-- take my decisions with it.
create table user_company (
    user_id        integer not null references app_user,
    company_number text not null references company on delete restrict,
    status         text not null default 'new',
    rating         smallint check (rating between 1 and 5),
    tags           text[] not null default '{}',
    next_action    text,
    next_action_on date,
    updated_at     timestamptz not null default now(),
    primary key (user_id, company_number)
);

-- Append-only. Edits create a new row; nothing is updated in place.
create table user_note (
    id             bigserial primary key,
    user_id        integer not null references app_user,
    company_number text not null references company on delete restrict,
    body           text not null,
    source         text not null default 'app',
    content_hash   text not null,
    created_at     timestamptz not null default now(),
    unique (user_id, company_number, content_hash)
);
create index user_note_company_idx on user_note (company_number, created_at desc);

create table outreach (
    id             bigserial primary key,
    user_id        integer not null references app_user,
    company_number text references company on delete restrict,
    contact_name   text not null,
    contact_role   text not null default 'owner',   -- owner | adviser | investor | broker | other
    channel        text,
    summary        text,
    happened_on    date not null default current_date,
    next_action    text,
    next_action_on date,
    created_at     timestamptz not null default now()
);

create table schema_migration (
    name       text primary key,
    applied_at timestamptz not null default now()
);
