-- Why no logo was found (site didn't answer, only a tiny icon, ...), for the Data page.
alter table company_logo add column if not exists note text;
