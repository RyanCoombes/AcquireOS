-- Locations for the map, SIC code descriptions, and owner addresses.

-- Postcode -> coordinates cache. precision: postcode (exact), outcode
-- (district centroid, used when a postcode has been retired) or none
-- (looked up, not found; retried after 90 days).
create table postcode_geo (
    postcode     text primary key,
    lat          double precision,
    lon          double precision,
    precision    text not null,
    looked_up_at timestamptz not null default now()
);

create table sic_code (
    code        text primary key,
    description text not null,
    source      text not null default 'seed'
);

-- Registered address of corporate owners (from the PSC data), so parent
-- companies outside your list can still be placed on the map.
alter table person add column address text;
alter table person add column postcode text;

-- AI or researched enrichment, one row per company. Kept apart from both the
-- Companies House data and your own judgement. Every field written here also
-- gets a sourced row in research.
create table enrichment (
    company_number    text primary key references company on delete cascade,
    website           text,
    business_type     text,     -- software | saas | data | msp | it_consultancy | field_service | agency | reseller | other
    recurring_revenue text,     -- yes | partly | no | unknown
    field_service     text,     -- yes | partly | no | unknown
    summary           text,
    confidence        text,     -- high | medium | low
    updated_at        timestamptz not null default now(),
    updated_by        text
);

-- Problems found while auditing the data (wrong SIC, wrong owner link,
-- misleading address and so on), for you to review.
create table data_issue (
    id             bigserial primary key,
    company_number text references company on delete cascade,
    issue          text not null,
    detail         text,
    suggested_fix  text,
    status         text not null default 'open',   -- open | resolved | dismissed
    created_by     text,
    created_at     timestamptz not null default now(),
    resolved_at    timestamptz,
    resolution     text
);
create index data_issue_open_idx on data_issue (status, created_at desc);

alter table research add column confidence text;
