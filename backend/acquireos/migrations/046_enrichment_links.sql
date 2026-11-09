-- News articles and data pages about a company, shown on its overview.
alter table enrichment add column if not exists links jsonb;
