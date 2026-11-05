-- Faster register loads: this full-text index on company names is no longer
-- used (search uses the trigram index), and maintaining it on 5.7 million
-- rows was a large part of each load.
drop index if exists company_name_idx;

-- Each company's best score across all buy boxes (and which box), so "all
-- companies" can be sorted and filtered by score without choosing a box.
create table company_best (
    company_number text primary key references company on delete cascade,
    buy_box_id     integer references buy_box on delete cascade,
    box_name       text,
    score          numeric,
    coverage       numeric,
    value_low      numeric,
    value_high     numeric,
    value_basis    text,
    boxes          text[] not null default '{}'
);
create index company_best_score_idx on company_best (score desc);

-- Fill it from the scores you already have, so nothing looks unscored after updating.
insert into company_best (company_number, buy_box_id, box_name, score, coverage, value_low, value_high, value_basis, boxes)
select distinct on (s.company_number) s.company_number, s.buy_box_id, b.name, s.score, s.coverage,
       s.value_low, s.value_high, s.value_basis,
       array(select b2.name from score s2 join buy_box b2 on b2.id = s2.buy_box_id
             where s2.company_number = s.company_number and not s2.excluded order by s2.score desc)
from score s join buy_box b on b.id = s.buy_box_id
where not s.excluded
order by s.company_number, s.score desc;
