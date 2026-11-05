-- Free enrichment from files AcquireOS already downloads.

-- From the register file: size of accounts filed, filing deadlines,
-- charges (mortgages and debentures) and previous names.
alter table company add column if not exists accounts_category text;
alter table company add column if not exists accounts_next_due date;
alter table company add column if not exists confirmation_next_due date;
alter table company add column if not exists charges_total integer;
alter table company add column if not exists charges_outstanding integer;
alter table company add column if not exists charges_part_satisfied integer;
alter table company add column if not exists charges_satisfied integer;
alter table company add column if not exists previous_names jsonb;

-- From the accounts files: balance sheet and cost figures.
alter table financial_period add column if not exists fixed_assets numeric;
alter table financial_period add column if not exists intangible_assets numeric;
alter table financial_period add column if not exists current_assets numeric;
alter table financial_period add column if not exists net_current_assets numeric;
alter table financial_period add column if not exists total_assets_less_cl numeric;
alter table financial_period add column if not exists gross_profit numeric;
alter table financial_period add column if not exists director_pay numeric;
alter table financial_period add column if not exists staff_costs numeric;

-- Which version of a loader read each file, so files read before a loader
-- learned new fields can be read again.
alter table import_run add column if not exists loader_version integer not null default 1;
