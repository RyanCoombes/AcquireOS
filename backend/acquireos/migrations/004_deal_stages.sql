-- Deal progress: a log of stage moves and a checklist per stage. User-owned.

create table stage_event (
    id             bigserial primary key,
    user_id        integer not null references app_user,
    company_number text not null references company on delete restrict,
    from_status    text,
    to_status      text not null,
    note           text,
    created_at     timestamptz not null default now()
);
create index stage_event_company_idx on stage_event (user_id, company_number, created_at);

create table deal_task (
    user_id        integer not null references app_user,
    company_number text not null references company on delete restrict,
    stage          text not null,
    item_key       text not null,
    label          text not null,
    custom         boolean not null default false,
    done           boolean not null default false,
    done_at        timestamptz,
    note           text,
    primary key (user_id, company_number, stage, item_key)
);

-- Start the history for companies that already have a status.
insert into stage_event (user_id, company_number, from_status, to_status, note, created_at)
select user_id, company_number, null, status, 'Status before stage history was recorded', updated_at
from user_company where status <> 'new';
