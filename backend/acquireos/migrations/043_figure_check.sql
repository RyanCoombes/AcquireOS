-- Figures read from PDFs that you or Claude have checked and confirmed, so
-- they stop showing in the "worth checking" list.
create table if not exists figure_check (
    company_number text not null references company on delete cascade,
    period_end     date not null,
    checked_at     timestamptz not null default now(),
    primary key (company_number, period_end)
);
