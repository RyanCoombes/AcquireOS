-- Logos taken from each company's own website (its home-screen icon, a
-- "logo" image in the page, or its favicon), kept here so nothing is fetched
-- from a third party when a page is shown.
create table if not exists company_logo (
    company_number text primary key references company on delete cascade,
    website        text not null,          -- the site the logo came from; a new website means fetch again
    status         text not null,          -- found | none
    image          bytea,
    content_type   text,
    source_url     text,
    width          int,
    fetched_at     timestamptz not null default now()
);
