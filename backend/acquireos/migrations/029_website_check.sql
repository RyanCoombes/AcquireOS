-- Which companies the website check has tried, so a long run can stop and
-- carry on, and companies are not checked again for six months.
create table if not exists website_check (
    company_number text primary key references company on delete cascade,
    checked_at     timestamptz not null default now(),
    result         text not null   -- confirmed | possible | none
);
