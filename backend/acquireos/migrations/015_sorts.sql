-- Sorting the whole directory by staff, revenue, net assets or owner age:
-- page through the side table's own index instead of sorting millions.
create index if not exists company_latest_staff_idx on company_latest (employees desc nulls last, company_number);
create index if not exists company_latest_net_assets_idx on company_latest (net_assets desc nulls last, company_number);
create index if not exists estimate_revenue_idx on estimate (revenue_high desc nulls last, company_number);
create index if not exists company_ownership_age_idx on company_ownership (oldest_birth_year, company_number);
-- The Changes page lists newest first; a company's own history is by company.
create index if not exists company_change_time_id_idx on company_change (detected_at desc, id desc);
