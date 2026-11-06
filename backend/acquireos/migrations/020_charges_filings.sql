-- Details fetched per company from the Companies House API (optional key):
-- charges (who lent money against the company's assets) and filings that
-- show new shares being issued (a sign of outside investment).
create table if not exists charge (
    company_number text not null references company on delete cascade,
    charge_id      text not null,
    status         text,            -- outstanding | fully-satisfied | part-satisfied
    classification text,
    holders        text[] not null default '{}',
    created_on     date,
    delivered_on   date,
    satisfied_on   date,
    particulars    text,
    primary key (company_number, charge_id)
);
create table if not exists filing (
    company_number text not null references company on delete cascade,
    transaction_id text not null,
    filed_on       date,
    type           text,
    category       text,
    description    text,
    detail         jsonb not null default '{}',
    primary key (company_number, transaction_id)
);
create index if not exists filing_company_idx on filing (company_number, filed_on desc);
create table if not exists ch_fetch (
    company_number text primary key references company on delete cascade,
    fetched_at     timestamptz not null default now(),
    error          text
);
