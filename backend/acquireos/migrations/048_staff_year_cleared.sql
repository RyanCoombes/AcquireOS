-- Staff counts cleared because they were the year heading: kept so the real
-- figure can be read again later (from the filing) and filled in.
create table if not exists staff_year_cleared (
    company_number text not null references company on delete cascade,
    period_end     date not null,
    cleared_at     timestamptz not null default now(),
    primary key (company_number, period_end)
);
