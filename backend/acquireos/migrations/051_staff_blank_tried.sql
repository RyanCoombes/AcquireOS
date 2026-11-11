-- Latest years with no staff figure at companies in a buy box, read again from
-- the filing once (staff given only by category is now added up).
create table if not exists staff_blank_tried (
    company_number text not null references company on delete cascade,
    period_end     date not null,
    tried_at       timestamptz not null default now(),
    primary key (company_number, period_end)
);
