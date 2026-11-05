-- Regions become an exclusion like everything else in the Exclusions
-- section: a ticked region is left out. The old "regions only" list was
-- ticked by its one user as regions to exclude, so it carries over as that.
update buy_box
set criteria = jsonb_set(
        jsonb_set(criteria, '{exclude}', coalesce(criteria -> 'exclude', '{}'::jsonb), true),
        '{exclude,regions}', coalesce(criteria -> 'regions', '[]'::jsonb), true) - 'regions'
where criteria ? 'regions';
