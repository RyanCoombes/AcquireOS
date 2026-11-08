-- Network view: find a director's other records and an owner's directorships quickly.
create index if not exists officer_key_idx on officer (officer_key);
create index if not exists officer_birth_idx on officer (birth_year, birth_month);
create index if not exists person_birth_idx on person (birth_year, birth_month) where kind = 'individual';
