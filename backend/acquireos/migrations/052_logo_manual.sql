-- A logo you chose (from a URL) or marked wrong: never replaced automatically.
alter table company_logo add column if not exists manual boolean not null default false;
