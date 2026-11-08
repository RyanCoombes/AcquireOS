-- Latest depreciation and amortisation (for EBITDA) and bank debt, beside
-- the other latest figures. Filled by the next refresh of company_latest.
alter table company_latest
    add column if not exists da numeric,
    add column if not exists bank_debt numeric;
