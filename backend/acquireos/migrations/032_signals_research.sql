-- ao_signals agrees with the stored company_signal: research that found the
-- company sold to a group counts as recently sold, and research ownership
-- wins over the register's sale signal.
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
$$;
