-- More from the filed accounts: depreciation and amortisation (for EBITDA),
-- interest and tax, debt (creditors, bank loans), working capital (stock,
-- trade debtors and creditors), reserves, share capital and the principal
-- activity text. Months loaded before are read again by the catch-up.
alter table financial_period
    add column if not exists depreciation numeric,
    add column if not exists amortisation numeric,
    add column if not exists depreciation_amortisation numeric,
    add column if not exists interest_payable numeric,
    add column if not exists tax numeric,
    add column if not exists creditors_within numeric,
    add column if not exists creditors_after numeric,
    add column if not exists bank_loans numeric,
    add column if not exists bank_overdrafts numeric,
    add column if not exists stock numeric,
    add column if not exists trade_debtors numeric,
    add column if not exists trade_creditors numeric,
    add column if not exists retained_earnings numeric,
    add column if not exists share_capital numeric,
    add column if not exists principal_activity text;
