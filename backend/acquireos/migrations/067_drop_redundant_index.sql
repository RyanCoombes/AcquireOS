-- Covered by company_change_time_id_idx (detected_at desc, id desc). In a file of its own:
-- 066 first had it after the index builds, where it deadlocked with the change stream.
drop index if exists company_change_time_idx;
