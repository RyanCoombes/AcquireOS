-- More from the Companies House API (optional key), per company:
-- directors and secretaries, each director's other companies, shareholders
-- from confirmation statements, insolvency cases and owner statements.
create table if not exists officer (
    company_number  text not null references company on delete cascade,
    officer_key     text not null,   -- the officer's id at Companies House
    name            text not null,
    role            text,
    appointed_on    date,
    resigned_on     date,
    birth_year      int,
    birth_month     int,
    occupation      text,
    nationality     text,
    residence       text,
    primary key (company_number, officer_key, role)
);
create table if not exists officer_appointment (
    officer_key     text not null,
    company_number  text not null,   -- may be a company outside the register we hold
    company_name    text,
    company_status  text,
    role            text,
    appointed_on    date,
    resigned_on     date,
    primary key (officer_key, company_number, role)
);
create index if not exists officer_appointment_company_idx on officer_appointment (company_number);
create table if not exists shareholder (
    company_number  text not null references company on delete cascade,
    name            text not null,
    shares          numeric,
    share_class     text,
    as_at           date,
    source          text,           -- the filing it came from
    primary key (company_number, name, share_class)
);
alter table ch_fetch add column if not exists profile jsonb not null default '{}';
alter table ch_fetch add column if not exists insolvency jsonb not null default '[]';
alter table ch_fetch add column if not exists psc_statements jsonb not null default '[]';
alter table ch_fetch add column if not exists shareholders_from text;
