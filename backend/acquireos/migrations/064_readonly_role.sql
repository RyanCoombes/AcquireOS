-- The AI's query tool runs as this role: it can read the tables and nothing else (no server
-- files, no password hashes, no ending other sessions), whatever the query says.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'acquireos_ro') then
    create role acquireos_ro nologin;
  end if;
  execute format('grant acquireos_ro to %I', current_user);
  grant usage on schema public to acquireos_ro;
  grant select on all tables in schema public to acquireos_ro;
  revoke all on app_user from acquireos_ro;
  alter default privileges in schema public grant select on tables to acquireos_ro;
exception when insufficient_privilege then
  raise notice 'acquireos_ro not set up: the database user may not create roles';
end $$;
