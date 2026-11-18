-- each statement in its own transaction
-- Sorting the whole register by these columns pages through an index instead of sorting
-- millions of rows (api.SIDE_SORTS). The three on the large tables take a few minutes each
-- to build on a Raspberry Pi, once, at the first start after the update. Saved one at a
-- time (see db.STEPWISE): only one table is ever locked, so nothing can deadlock with it.
create index if not exists enrichment_work_idx on enrichment (work_model, company_number) where work_model is not null;
create index if not exists enrichment_website_idx on enrichment (website, company_number) where website is not null;
create index if not exists enrichment_btype_idx on enrichment (business_type) where business_type is not null;
create index if not exists company_sic1_idx on company ((sic_codes[1]), company_number) where sic_codes[1] is not null;
create index if not exists company_inc_idx on company (incorporation_date, company_number) where incorporation_date is not null;
create index if not exists company_ownership_type_idx on company_ownership (ownership_type, company_number);
