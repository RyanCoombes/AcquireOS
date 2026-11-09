-- PDF reader: the full text it read (page by page) and the line each figure
-- came from, for checking a reading against the PDF on the Data page.
alter table pdf_read add column if not exists full_text text;
alter table pdf_read add column if not exists lines jsonb;
