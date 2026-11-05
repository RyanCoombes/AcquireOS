-- A company's score in each buy box (company pages, best-score rebuilds).
create index if not exists score_company_idx on score (company_number);
-- Sorting the directory by best score.
create index if not exists company_best_score_nl_idx on company_best (score desc nulls last, company_number);
-- Industry filter: "has any of these SIC codes" with an index.
create index if not exists company_sic_gin_idx on company using gin (sic_codes);
