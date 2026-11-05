-- The company directory lists every company A to Z; this index lets it page
-- through 5.7 million names without sorting them all each time.
create index if not exists company_name_sort_idx on company (name, company_number);
