-- Your funding assumptions for a deal (price, cash in, investor stake,
-- vendor loan, bank terms), kept per company.
alter table user_company add column if not exists funding jsonb not null default '{}';
