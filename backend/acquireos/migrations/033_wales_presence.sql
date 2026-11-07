-- Presence in Wales.
-- 1. Region from the postcode: Welsh postcode districts in the mostly-English
--    SY and CH areas (Newtown, Welshpool, Aberystwyth; Deeside, Flint, Mold,
--    Holywell) were counted as England. For districts that straddle the
--    border, the exact country from the postcode lookup (postcode_geo.country)
--    is applied after each lookup run.
alter table postcode_geo add column if not exists country text;

create or replace function ao_region(pc text) returns text language sql immutable as $$
    select case
        when pc is null or pc = '' then null
        when substring(upper(pc) from '^([A-Z]{1,2})[0-9]') in ('CF','SA','NP','LL','LD') then 'Wales'
        when upper(pc) ~ '^(CH[5-8]|SY(1[5-9]|2[0-5]))(\s|$)' then 'Wales'
        when substring(upper(pc) from '^([A-Z]{1,2})[0-9]') in ('AB','DD','DG','EH','FK','G','HS','IV','KA','KW','KY','ML','PA','PH','TD','ZE') then 'Scotland'
        when substring(upper(pc) from '^([A-Z]{1,2})[0-9]') = 'BT' then 'Northern Ireland'
        when substring(upper(pc) from '^([A-Z]{1,2})[0-9]') is not null then 'England'
    end
$$;

update company set region = 'Wales'
where region is distinct from 'Wales'
  and (postcode like 'CH5 %' or postcode like 'CH6 %' or postcode like 'CH7 %' or postcode like 'CH8 %'
       or postcode like 'SY15 %' or postcode like 'SY16 %' or postcode like 'SY17 %' or postcode like 'SY18 %'
       or postcode like 'SY19 %' or postcode like 'SY20 %' or postcode like 'SY21 %' or postcode like 'SY22 %'
       or postcode like 'SY23 %' or postcode like 'SY24 %' or postcode like 'SY25 %');

-- Is a postcode in Wales: the exact country when looked up, else the district rule.
create or replace function ao_is_wales(pc text) returns boolean language sql stable as $$
    select coalesce((select g.country = 'Wales' from postcode_geo g
                     where g.postcode = upper(trim(pc)) and g.country is not null),
                    ao_region(pc) = 'Wales')
$$;

create or replace function ao_welsh_funders() returns text language sql immutable as $$
    select '(development bank of wales|banc datblygu|finance wales|dbw investments|welsh ministers|welsh government|welsh development agency)'
$$;

-- 2. Signals, with three for Wales:
--   wales_office    an office or site in Wales (research or the company's website)
--   wales_funding   lending or investment from Welsh public funders (DBW, Finance
--                   Wales, Welsh Government), who only fund businesses in Wales
--   wales_director  a current director gives Wales as their country (a hint only)
create or replace function ao_signals(num text) returns text[] language sql stable as $$
  select array_remove(array[
    case when exists (select 1 from enrichment e where e.company_number = num and e.ownership in ('group_owned', 'foreign_owned'))
           or (not exists (select 1 from enrichment e where e.company_number = num and e.ownership is not null)
               and exists (
                 select 1 from company_person a join person pa on pa.id = a.person_id
                 where a.company_number = num and a.ceased_on is null and pa.kind <> 'individual'
                   and a.notified_on > current_date - 1095
                   and exists (select 1 from company_person b where b.company_number = num
                               and b.ceased_on between a.notified_on - 120 and a.notified_on + 120))
               and coalesce((select ownership_type from company_ownership where company_number = num), 'unknown') <> 'owner_held')
      then 'recently_sold' end,
    case when exists (
          select 1 from person p join company_person cp on cp.person_id = p.id
          join company s on s.company_number = cp.company_number
          where p.registration_number = num and cp.company_number <> num and cp.ceased_on is null
            and cp.notified_on > current_date - 1095
            and s.incorporation_date < cp.notified_on - 180)
      then 'possible_buyer' end,
    case when (select count(*) from shareholder sh where sh.company_number = num) >= 10
      then 'many_shareholders' end,
    case when exists (select 1 from enrichment e, jsonb_array_elements(e.locations) l
                      where e.company_number = num and ao_is_wales(l->>'postcode'))
      then 'wales_office' end,
    case when exists (select 1 from charge ch, unnest(ch.holders) h where ch.company_number = num and ch.status <> 'fully-satisfied'
                      and h ~* ao_welsh_funders())
           or exists (select 1 from shareholder sh where sh.company_number = num and sh.name ~* ao_welsh_funders())
           or exists (select 1 from company_person cp join person p on p.id = cp.person_id
                      where cp.company_number = num and cp.ceased_on is null and p.name ~* ao_welsh_funders())
      then 'wales_funding' end,
    case when exists (select 1 from officer o where o.company_number = num and o.resigned_on is null
                      and o.residence ~* '^\s*wales\s*$')
      then 'wales_director' end
  ], null)
$$;

create or replace function ao_refresh_company_signals() returns int language plpgsql as $$
declare n int;
begin
  drop table if exists cs_new;
  create temp table cs_new on commit drop as
  with sold_reg as (
    select distinct on (a.company_number) a.company_number, a.notified_on as sold_on, pa.name as sold_to
    from company_person a join person pa on pa.id = a.person_id
    where a.ceased_on is null and pa.kind <> 'individual' and a.notified_on > current_date - 1095
      and exists (select 1 from company_person b where b.company_number = a.company_number
                  and b.ceased_on between a.notified_on - 120 and a.notified_on + 120)
      and coalesce((select o.ownership_type from company_ownership o where o.company_number = a.company_number), 'unknown') <> 'owner_held'
    order by a.company_number, a.notified_on desc),
  sold_research as (
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
  w_office as (select distinct e.company_number from enrichment e, jsonb_array_elements(e.locations) l
               where ao_is_wales(l->>'postcode')),
  w_funding as (
    select ch.company_number from charge ch, unnest(ch.holders) h
    where ch.status <> 'fully-satisfied' and h ~* ao_welsh_funders()
    union select sh.company_number from shareholder sh where sh.name ~* ao_welsh_funders()
    union select cp.company_number from company_person cp join person p on p.id = cp.person_id
          where cp.ceased_on is null and p.kind <> 'individual' and p.name ~* ao_welsh_funders()),
  w_director as (select distinct o.company_number from officer o
                 where o.resigned_on is null and o.residence ~* '^\s*wales\s*$'),
  allc as (select company_number from sold union select company_number from buyer union select company_number from many
           union select company_number from w_office union select company_number from w_funding
           union select company_number from w_director)
  select x.company_number,
         array_remove(array[case when s.company_number is not null then 'recently_sold' end,
                            case when b.company_number is not null then 'possible_buyer' end,
                            case when m.company_number is not null then 'many_shareholders' end,
                            case when wo.company_number is not null then 'wales_office' end,
                            case when wf.company_number is not null then 'wales_funding' end,
                            case when wd.company_number is not null then 'wales_director' end], null) as signals,
         s.sold_on, s.sold_to
  from allc x join company c on c.company_number = x.company_number
  left join sold s on s.company_number = x.company_number
  left join buyer b on b.company_number = x.company_number
  left join many m on m.company_number = x.company_number
  left join w_office wo on wo.company_number = x.company_number
  left join (select distinct company_number from w_funding) wf on wf.company_number = x.company_number
  left join w_director wd on wd.company_number = x.company_number;
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
