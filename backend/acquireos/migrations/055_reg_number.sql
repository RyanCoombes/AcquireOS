-- A company registration number as written in an owner record ("1234567",
-- "01234567", "Company No. SC123456", "oe012345") in the form the register
-- uses ("01234567", "SC123456", "OE012345"), so holding companies link up.
create or replace function ao_reg_number(t text) returns text language sql immutable as $$
  select case
    when x is null then null
    when x ~ '^[0-9]{1,8}$' then lpad(x, 8, '0')
    when x ~ '^[A-Z]{2}[0-9]{1,6}$' then substr(x, 1, 2) || lpad(substr(x, 3), 6, '0')
    else x end
  from (select coalesce(
          substring(upper(regexp_replace(coalesce(t, ''), '[^A-Za-z0-9]', '', 'g'))
                    from '((?:SC|NI|OC|SO|NC|OE|FC|LP|SL|NL|SE|GE|R0|IP|SP|RS|CE|CS)[0-9]{1,6})$'),
          substring(upper(regexp_replace(coalesce(t, ''), '[^A-Za-z0-9]', '', 'g')) from '([0-9]{1,8})$')) as x) s
$$;
