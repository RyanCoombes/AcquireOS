-- Searching owners by name (any words, any order) across every PSC record.
create index if not exists person_name_trgm_idx on person using gin (name gin_trgm_ops);
-- "Which companies does this person own through holding companies": the
-- traced owners are jsonb, indexed for containment.
create index if not exists company_ownership_owners_idx on company_ownership using gin (ultimate_owners jsonb_path_ops);
