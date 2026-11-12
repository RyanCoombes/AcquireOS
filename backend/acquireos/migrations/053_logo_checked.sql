-- When the website was last looked at for the logo (fetched_at stays the time
-- the stored image last changed, which is its version for the browser).
alter table company_logo add column if not exists checked_at timestamptz;
update company_logo set checked_at = fetched_at where checked_at is null;
