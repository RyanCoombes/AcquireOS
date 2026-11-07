-- Accounts read automatically from PDF (text layer or OCR): one row per
-- company and year end tried, so each is only read once.
create table if not exists pdf_read (
    company_number text not null references company on delete cascade,
    made_up        date not null,
    status         text not null,   -- done | nothing_found | failed
    method         text,            -- text | ocr
    figures        jsonb not null default '{}',
    note           text,
    read_at        timestamptz not null default now(),
    primary key (company_number, made_up)
);
