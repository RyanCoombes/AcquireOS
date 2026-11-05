-- Fast "starts with" search on names and postcodes, whatever the database's
-- collation (plain indexes only serve LIKE 'abc%' under the C collation).
create index if not exists company_name_prefix_idx on company (name text_pattern_ops);
create index if not exists company_postcode_prefix_idx on company (postcode text_pattern_ops);
