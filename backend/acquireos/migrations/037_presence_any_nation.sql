-- Presence in any nation, not only Wales: signals are now office:<nation>,
-- funding:<nation> and director:<nation> (England, Scotland, Wales, Northern
-- Ireland), so the presence filter works for wherever you are looking.

-- The nation of a postcode: the exact country when looked up, else the district rule.
create or replace function ao_nation(pc text) returns text language sql stable as $$
    select coalesce((select g.country from postcode_geo g
                     where g.postcode = upper(trim(pc)) and g.country in ('England', 'Scotland', 'Wales', 'Northern Ireland')),
                    ao_region(pc))
$$;

-- A director's country of residence as a nation.
create or replace function ao_residence_nation(r text) returns text language sql immutable as $$
    select case
        when r ~* '^\s*wales\s*$' then 'Wales'
        when r ~* '^\s*scotland\s*$' then 'Scotland'
        when r ~* '^\s*northern ireland\s*$' then 'Northern Ireland'
        when r ~* '^\s*england\s*$' then 'England'
    end
$$;

-- Public funders that only back businesses in one nation.
create or replace function ao_regional_funders() returns table (nation text, pattern text) language sql immutable as $$
    values ('Wales', '(development bank of wales|banc datblygu|finance wales|dbw investments|welsh ministers|welsh government|welsh development agency)'),
           ('Scotland', '(scottish enterprise|scottish national investment bank|scottish investment bank|highlands and islands enterprise|scottish ministers)'),
           ('Northern Ireland', '(invest northern ireland|\minvest ni\M|northern ireland investment fund)'),
           ('England', '(northern powerhouse investment fund|\mnpif\M|midlands engine investment fund|\mmeif\M|south west investment fund|cornwall (and|&) isles of scilly investment fund|\mciosif\M|north east fund)')
$$;

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
      then 'many_shareholders' end
  ], null)
  || coalesce((select array_agg(distinct x order by x) from (
       select 'office:' || ao_nation(l->>'postcode') as x from enrichment e, jsonb_array_elements(e.locations) l
       where e.company_number = num and ao_nation(l->>'postcode') is not null
       union select 'funding:' || f.nation from ao_regional_funders() f
       where exists (select 1 from charge ch, unnest(ch.holders) h where ch.company_number = num and ch.status <> 'fully-satisfied' and h ~* f.pattern)
          or exists (select 1 from shareholder sh where sh.company_number = num and sh.name ~* f.pattern)
          or exists (select 1 from company_person cp join person p on p.id = cp.person_id
                     where cp.company_number = num and cp.ceased_on is null and p.name ~* f.pattern)
       union select 'director:' || ao_residence_nation(o.residence) from officer o
       where o.company_number = num and o.resigned_on is null and ao_residence_nation(o.residence) is not null) z), '{}')
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
  w_office as (select distinct e.company_number, 'office:' || ao_nation(l->>'postcode') as sig
               from enrichment e, jsonb_array_elements(e.locations) l where ao_nation(l->>'postcode') is not null),
  w_funding as (
    select ch.company_number, 'funding:' || f.nation as sig from charge ch, unnest(ch.holders) h, ao_regional_funders() f
    where ch.status <> 'fully-satisfied' and h ~* f.pattern
    union select sh.company_number, 'funding:' || f.nation from shareholder sh, ao_regional_funders() f where sh.name ~* f.pattern
    union select cp.company_number, 'funding:' || f.nation from company_person cp join person p on p.id = cp.person_id, ao_regional_funders() f
          where cp.ceased_on is null and p.kind <> 'individual' and p.name ~* f.pattern),
  w_director as (select distinct o.company_number, 'director:' || ao_residence_nation(o.residence) as sig from officer o
                 where o.resigned_on is null and ao_residence_nation(o.residence) is not null),
  places as (select company_number, array_agg(distinct sig order by sig) as sigs
             from (select * from w_office union all select * from w_funding union all select * from w_director) u group by 1),
  allc as (select company_number from sold union select company_number from buyer union select company_number from many
           union select company_number from places)
  select x.company_number,
         array_remove(array[case when s.company_number is not null then 'recently_sold' end,
                            case when b.company_number is not null then 'possible_buyer' end,
                            case when m.company_number is not null then 'many_shareholders' end], null)
           || coalesce(pl.sigs, '{}') as signals,
         s.sold_on, s.sold_to
  from allc x join company c on c.company_number = x.company_number
  left join sold s on s.company_number = x.company_number
  left join buyer b on b.company_number = x.company_number
  left join many m on m.company_number = x.company_number
  left join places pl on pl.company_number = x.company_number;
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

-- Rebuild the stored signals with the new names.
select ao_refresh_company_signals();
