-- A nightly copy of the accounts figures that can't be downloaded again: those saved by you
-- or Claude, and those read from PDFs. The nightly "your work" backup leaves out
-- financial_period (tens of GB of re-downloadable data) but includes this small table.
create table if not exists saved_figure (
    company_number text not null,
    period_end     date not null,
    data           jsonb not null,
    copied_at      timestamptz not null default now(),
    primary key (company_number, period_end)
);
