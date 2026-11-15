-- How staff work: remote | hybrid | on_site | unknown. From research (website, job adverts) or entered by hand.
alter table enrichment add column if not exists work_model text;
