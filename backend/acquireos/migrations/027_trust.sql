-- Which data to trust: researched facts that override the register, and
-- signals worked out from the register itself.

-- Research findings that win over the register when newer and sourced:
-- ownership (e.g. sold to a group) and where the business really trades.
alter table enrichment add column if not exists ownership text;          -- an ownership type, as in company_ownership
alter table enrichment add column if not exists ownership_note text;
alter table enrichment add column if not exists trading_postcode text;
alter table enrichment add column if not exists trading_region text;

-- Two companies you treat as one business: the one merged keeps a pointer
-- to the one you are pursuing.
alter table user_company add column if not exists merged_into text;

-- Signals from the register for one company:
--   recently_sold     a company became the owner in the last 3 years as the
--                     previous owners left, and it does not trace back to them
--   possible_buyer    took control of an established company in the last 3 years
--   many_shareholders 10 or more shareholders on the latest statement
create or replace function ao_signals(num text) returns text[] language sql stable as $$
  select array_remove(array[
    case when exists (
          select 1 from company_person a join person pa on pa.id = a.person_id
          where a.company_number = num and a.ceased_on is null and pa.kind <> 'individual'
            and a.notified_on > current_date - 1095
            and exists (select 1 from company_person b where b.company_number = num
                        and b.ceased_on between a.notified_on - 120 and a.notified_on + 120))
         and coalesce((select ownership_type from company_ownership where company_number = num), 'unknown') <> 'owner_held'
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
$$;

-- Active companies that look like the same business: the same owner and the
-- same registered address, or a director in common at the same postcode.
create or replace function ao_same_business(num text) returns text[] language sql stable as $$
  select coalesce(array_agg(distinct x order by x), '{}') from (
    select case when l.a = num then l.b else l.a end as x from company_link l
    where (l.a = num or l.b = num) and l.kind = 'shared_owner'
      and exists (select 1 from company_link l2 where l2.kind = 'shared_address'
                  and ((l2.a = l.a and l2.b = l.b) or (l2.a = l.b and l2.b = l.a)))
    union
    select a.company_number from officer o
    join officer_appointment a on a.officer_key = o.officer_key and a.company_number <> num and a.resigned_on is null
    join company c1 on c1.company_number = num
    join company c2 on c2.company_number = a.company_number
    where o.company_number = num and o.resigned_on is null and c2.postcode = c1.postcode
    union
    -- the other way round: a director fetched for the other company also sits on this one
    select o.company_number from officer_appointment a
    join officer o on o.officer_key = a.officer_key and o.company_number <> num and o.resigned_on is null
    join company c1 on c1.company_number = num
    join company c2 on c2.company_number = o.company_number
    where a.company_number = num and a.resigned_on is null and c2.postcode = c1.postcode
  ) t join company c on c.company_number = t.x and c.status like 'active%'
$$;
