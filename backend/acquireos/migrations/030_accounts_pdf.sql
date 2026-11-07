-- Accounts years Companies House holds only as PDF (no figures to read),
-- from the API fetch: shown on the company page with a link.
alter table ch_fetch add column if not exists accounts_pdf jsonb not null default '[]';
