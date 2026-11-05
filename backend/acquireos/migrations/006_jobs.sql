-- Long-running jobs (Companies House downloads), with live progress that
-- every page can show, whether started from the app or by the scheduler.
create table job (
    id               bigserial primary key,
    kind             text not null,           -- refresh | scheduled | geocode
    status           text not null default 'running',   -- running | done | failed | cancelled
    stage            text,
    stage_index      integer not null default 0,
    stage_total      integer not null default 1,
    stage_pct        numeric not null default 0,
    pct              numeric not null default 0,
    detail           text,
    eta_seconds      integer,
    stages           jsonb not null default '[]',
    log              jsonb not null default '[]',
    result           jsonb,
    error            text,
    cancel_requested boolean not null default false,
    started_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    finished_at      timestamptz
);
create index job_recent_idx on job (started_at desc);
