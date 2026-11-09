-- Deals found by research (acquisitions, sales, mergers, investment, EOT, MBO...), each sourced.
alter table enrichment add column if not exists deals jsonb;
