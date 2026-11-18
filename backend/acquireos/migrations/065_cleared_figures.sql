-- Figures you blanked on purpose (a wrong number read from a PDF): no import refills them.
alter table financial_period add column if not exists cleared text[];
-- Open issues for one company (the company page and the data trust score).
create index if not exists data_issue_company_idx on data_issue (company_number, status);
