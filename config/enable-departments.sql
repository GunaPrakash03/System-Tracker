-- Put Departments back in the sidebar.
--
-- The sidebar trim in minimal-tracking-features.sql disables every feature
-- outside a small tracking whitelist, and Departments was not on it. That was
-- correct when the trim was written — nothing needed departments then. It is
-- not correct now: Settings -> Tracker Settings assigns each employee to a
-- department, and app productivity categories are held per department, so
-- without this there is no way to create the departments the tracker needs.
--
-- minimal-tracking-features.sql has been updated to keep these enabled too, so
-- re-running the trim no longer undoes this. Run this file if the trim has
-- already been applied.
--
-- Run:
--   docker exec -i db psql -U postgres -d gauzy < config/enable-departments.sql
--
-- IMPORTANT: afterwards, LOG OUT and LOG BACK IN completely. A refresh is not
-- enough — the app caches the feature list in localStorage ('_gauzyStore') and
-- only re-reads it at login.

BEGIN;

-- FEATURE_ORGANIZATION is the parent menu; the Departments entry is invisible
-- without it even when the department feature itself is enabled.
UPDATE feature_organization SET "isEnabled" = true
WHERE "featureId" IN (
    SELECT id FROM feature
    WHERE code IN ('FEATURE_ORGANIZATION', 'FEATURE_ORGANIZATION_DEPARTMENT')
);

-- Optional, and off by default: restores Settings -> Features, the page for
-- toggling all of this from the UI. The trim disabled it, which is why this
-- file exists rather than being two clicks. Uncomment if you would rather
-- manage features in the dashboard than in SQL.
-- UPDATE feature_organization SET "isEnabled" = true
-- WHERE "featureId" IN (SELECT id FROM feature WHERE code = 'FEATURE_SETTING');

COMMIT;

-- Verify — both should read t.
SELECT f.code, fo."isEnabled"
FROM feature f
JOIN feature_organization fo ON fo."featureId" = f.id
WHERE f.code IN ('FEATURE_ORGANIZATION', 'FEATURE_ORGANIZATION_DEPARTMENT')
ORDER BY f.code;
