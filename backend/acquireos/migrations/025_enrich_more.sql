-- More researched facts per company: every office or site (not only the
-- registered office), key facts each with its own source, and contact links.
alter table enrichment add column if not exists locations jsonb not null default '[]';
alter table enrichment add column if not exists facts jsonb not null default '[]';
alter table enrichment add column if not exists linkedin text;
alter table enrichment add column if not exists phone text;
