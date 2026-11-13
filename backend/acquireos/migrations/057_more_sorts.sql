-- Sorting the whole company list by value, profit, cash or bank debt pages
-- through these indexes instead of sorting millions of rows.
create index if not exists company_best_value_idx on company_best (value_high desc nulls last, company_number);
create index if not exists company_latest_profit_idx on company_latest (operating_profit desc nulls last, company_number);
create index if not exists company_latest_cash_idx on company_latest (cash desc nulls last, company_number);
create index if not exists company_latest_debt_idx on company_latest (bank_debt desc nulls last, company_number);
