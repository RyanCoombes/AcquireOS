-- The owners register (PSC) as the Companies House API returned it, which
-- is fresher than the monthly bulk snapshot. Null until fetched.
alter table ch_fetch add column if not exists psc jsonb;
