-- Incremental scoring: each score row remembers a hash of the facts it was
-- computed from, and each buy box the criteria it was last fully scored
-- with, so a monthly rescore only redoes companies whose facts changed.
alter table score add column if not exists facts_hash text;
alter table buy_box add column if not exists scored_hash text;
