-- Your own priority order within a pipeline stage (1 = top). Null = after the ranked ones.
alter table user_company add column if not exists priority integer;
