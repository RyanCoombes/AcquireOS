-- Why a staff count was cleared (misread, or an outlier against the years
-- either side) and what it was, so a re-read giving the same value isn't
-- put straight back.
alter table staff_year_cleared add column if not exists reason text not null default 'misread';
alter table staff_year_cleared add column if not exists old_value integer;
