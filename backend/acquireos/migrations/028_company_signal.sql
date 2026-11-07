-- Register signals stored for every company, so lists and the map can filter
-- on them quickly (worked out again after each data load and re-score).
create table if not exists company_signal (
    company_number text primary key references company on delete cascade,
    signals        text[] not null default '{}',
    sold_on        date,     -- when a company became the owner (recently sold)
    sold_to        text,     -- that company's name, or what research found
    updated_at     timestamptz not null default now()
);
create index if not exists company_signal_gin on company_signal using gin (signals);

create or replace function ao_refresh_company_signals() returns int language plpgsql as $$
declare n int;
begin
  drop table if exists cs_new;
  create temp table cs_new on commit drop as
  with sold_reg as (
    -- a company became the owner in the last 3 years as the previous owners
    -- left, and the new owner does not trace back to them
    select distinct on (a.company_number) a.company_number, a.notified_on as sold_on, pa.name as sold_to
    from company_person a join person pa on pa.id = a.person_id
    where a.ceased_on is null and pa.kind <> 'individual' and a.notified_on > current_date - 1095
      and exists (select 1 from company_person b where b.company_number = a.company_number
                  and b.ceased_on between a.notified_on - 120 and a.notified_on + 120)
      and coalesce((select o.ownership_type from company_ownership o where o.company_number = a.company_number), 'unknown') <> 'owner_held'
    order by a.company_number, a.notified_on desc),
  sold_research as (
    -- research says it belongs to a group now (wins over the register)
    select e.company_number, null::date as sold_on, coalesce(e.ownership_note, 'Group-owned (research)') as sold_to
    from enrichment e where e.ownership in ('group_owned', 'foreign_owned')),
  sold as (
    select * from sold_research
    union all
    select r.* from sold_reg r where not exists (select 1 from enrichment e where e.company_number = r.company_number
                                                 and e.ownership is not null)),
  buyer as (
    select distinct p.registration_number as company_number
    from person p join company_person cp on cp.person_id = p.id join company s on s.company_number = cp.company_number
    where p.registration_number is not null and cp.company_number <> p.registration_number and cp.ceased_on is null
      and cp.notified_on > current_date - 1095 and s.incorporation_date < cp.notified_on - 180),
  many as (select company_number from shareholder group by 1 having count(*) >= 10),
  allc as (select company_number from sold union select company_number from buyer union select company_number from many)
  select x.company_number,
         array_remove(array[case when s.company_number is not null then 'recently_sold' end,
                            case when b.company_number is not null then 'possible_buyer' end,
                            case when m.company_number is not null then 'many_shareholders' end], null) as signals,
         s.sold_on, s.sold_to
  from allc x join company c on c.company_number = x.company_number
  left join sold s on s.company_number = x.company_number
  left join buyer b on b.company_number = x.company_number
  left join many m on m.company_number = x.company_number;
  delete from company_signal cs where not exists (select 1 from cs_new n where n.company_number = cs.company_number);
  insert into company_signal (company_number, signals, sold_on, sold_to)
  select company_number, signals, sold_on, sold_to from cs_new
  on conflict (company_number) do update set signals = excluded.signals, sold_on = excluded.sold_on,
    sold_to = excluded.sold_to, updated_at = now()
  where (company_signal.signals, company_signal.sold_on, company_signal.sold_to)
        is distinct from (excluded.signals, excluded.sold_on, excluded.sold_to);
  select count(*) into n from company_signal;
  return n;
end $$;
