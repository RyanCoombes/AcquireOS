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
