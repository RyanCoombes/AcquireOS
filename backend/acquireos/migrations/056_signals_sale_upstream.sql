-- Recently sold also when the sale happened one level up: a company's holding
-- company (linked by registration number) got a new corporate owner as its
-- owners left (e.g. BCC IT, whose parent Melyn Ltd was bought). And a new signal,
-- signs of a sale: two or more directors living abroad appointed in the last 18
-- months, plus a new loan charge, a year-end change or new articles in that time
-- (on the company or its holding company) - together, nearly always a completed
-- acquisition the owner records haven't caught up with.
create or replace function ao_refresh_company_signals() returns int language plpgsql as $$
declare n int;
begin
  drop table if exists cs_new;
  create temp table cs_new on commit drop as
  with changed as (
    -- a new corporate owner arriving as the previous owners left, in the last 3 years
    select distinct on (a.company_number) a.company_number, a.notified_on as sold_on, pa.name as sold_to
    from company_person a join person pa on pa.id = a.person_id
    where a.ceased_on is null and pa.kind <> 'individual' and a.notified_on > current_date - 1095
      and exists (select 1 from company_person b where b.company_number = a.company_number
                  and b.ceased_on between a.notified_on - 120 and a.notified_on + 120)
    order by a.company_number, a.notified_on desc),
  via_parent as (
    -- the same, at the holding company that owns it
    select distinct on (t.company_number) t.company_number, ch.sold_on,
           ch.sold_to || ' (bought ' || initcap(pp.name) || ', its holding company)' as sold_to
    from company_person t join person pp on pp.id = t.person_id and pp.kind <> 'individual'
    join changed ch on ch.company_number = ao_reg_number(pp.registration_number)
    where t.ceased_on is null and t.company_number <> ch.company_number
      and (coalesce(pp.country_registered, '') = '' or pp.country_registered ~* '(united kingdom|england|wales|scotland|northern ireland|\mUK\M|great britain)')
    order by t.company_number, ch.sold_on desc),
  sold_reg as (
    select * from (select * from changed union all select * from via_parent) u
    where coalesce((select o.ownership_type from company_ownership o where o.company_number = u.company_number), 'unknown') <> 'owner_held'),
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
      and cp.notified_on > current_date - 1095 and s.incorporation_date < cp.notified_on - 180
      -- A trust's own holding company (e.g. an employee ownership trust buying out
      -- the founders) isn't a buyer of other businesses.
      and coalesce((select o.ownership_type from company_ownership o where o.company_number = p.registration_number), '') not in ('eot', 'trust')
      and coalesce((select e.ownership from enrichment e where e.company_number = p.registration_number), '') not in ('eot', 'trust')),
  many as (select company_number from shareholder group by 1 having count(*) >= 10),
  pattern as (
    select o.company_number from officer o
    where o.appointed_on > current_date - 548 and o.resigned_on is null
      and coalesce(o.residence, '') <> ''
      and o.residence !~* '(united kingdom|england|wales|scotland|northern ireland|\mUK\M|great britain|britain|isle of man|jersey|guernsey)'
    group by o.company_number having count(distinct o.officer_key) >= 2
    intersect
    select company_number from (
      select company_number from charge where created_on > current_date - 548
      union select company_number from filing where filed_on > current_date - 548
        and (type in ('AA01', 'CC04', 'MA') or (coalesce(category, '') = 'resolution' and coalesce(description, '') ~* 'articles'))
    ) corroborated),
  acquired as (
    select company_number from pattern
    union  -- or its holding company shows the pattern
    select t.company_number from company_person t join person pp on pp.id = t.person_id and pp.kind <> 'individual'
    join pattern pa on pa.company_number = ao_reg_number(pp.registration_number)
    where t.ceased_on is null),
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
           union select company_number from places union select company_number from acquired)
  select x.company_number,
         array_remove(array[case when s.company_number is not null then 'recently_sold' end,
                            case when b.company_number is not null then 'possible_buyer' end,
                            case when m.company_number is not null then 'many_shareholders' end,
                            case when aq.company_number is not null and s.company_number is null then 'likely_acquired' end], null)
           || coalesce(pl.sigs, '{}') as signals,
         s.sold_on, s.sold_to
  from allc x join company c on c.company_number = x.company_number
  left join (select distinct on (company_number) * from sold order by company_number, sold_on desc nulls last) s
         on s.company_number = x.company_number
  left join buyer b on b.company_number = x.company_number
  left join many m on m.company_number = x.company_number
  left join (select distinct company_number from acquired) aq on aq.company_number = x.company_number
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
