-- PDF accounts: what was read (for checking why a year couldn't be read), and
-- the reader version, so years that failed are tried again when it improves.
alter table pdf_read add column if not exists sample text;
alter table pdf_read add column if not exists version int not null default 1;
alter table pdf_read add column if not exists tries int not null default 1;
-- Accounts filings, for finding years with no figures.
create index if not exists filing_aa_idx on filing (company_number) where type = 'AA';
