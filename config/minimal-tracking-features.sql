-- Strip the Gauzy sidebar down to TRACKING + EMPLOYEES only.
--
-- Keeps: Dashboards, Employees (add employee/admin), Time Tracking,
--        Time & Activity, Timesheets.
-- Hides: Accounting, Sales, Tasks, Jobs, Contacts, Goals, and all the
--        Organization sub-items (Equipment, Inventory, Tags, Vendors,
--        Projects, Departments, Teams, …).
--
-- Mechanism: Gauzy's built-in feature toggles (feature_organization rows).
-- Every sidebar item has a `featureKey`; the web app reads the tenant-level
-- toggles (organizationId IS NULL) AT LOGIN. No code change, no rebuild,
-- fully reversible.
--
-- Run:  docker exec db psql -U postgres -d gauzy -f - < minimal-tracking-features.sql
--   (or docker exec -i db psql -U postgres -d gauzy < minimal-tracking-features.sql)
--
-- IMPORTANT: after running, users must FULLY LOG OUT and LOG BACK IN.
-- A plain refresh is NOT enough — the app persists the old feature list to
-- localStorage ('_gauzyStore'); only a fresh login re-fetches and overwrites it.

BEGIN;

-- 1. Disable everything except the tracking/employee essentials.
UPDATE feature_organization SET "isEnabled" = false
WHERE "featureId" IN (
  SELECT id FROM feature WHERE code NOT IN (
    'FEATURE_DASHBOARD',
    'FEATURE_EMPLOYEES',
    'FEATURE_TIME_TRACKING',
    'FEATURE_EMPLOYEE_TIME_ACTIVITY',
    'FEATURE_EMPLOYEE_TIMESHEETS',
    -- Departments are part of the tracking workflow now: Settings -> Tracker
    -- Settings assigns each employee to one, and app productivity categories
    -- are held per department. Without these two the Organization menu has no
    -- Departments entry and there is no way to create one.
    'FEATURE_ORGANIZATION',
    'FEATURE_ORGANIZATION_DEPARTMENT'
  )
);

-- 2. Make sure the essentials are on.
UPDATE feature_organization SET "isEnabled" = true
WHERE "featureId" IN (
  SELECT id FROM feature WHERE code IN (
    'FEATURE_DASHBOARD',
    'FEATURE_EMPLOYEES',
    'FEATURE_TIME_TRACKING',
    'FEATURE_EMPLOYEE_TIME_ACTIVITY',
    'FEATURE_EMPLOYEE_TIMESHEETS',
    -- Departments are part of the tracking workflow now: Settings -> Tracker
    -- Settings assigns each employee to one, and app productivity categories
    -- are held per department. Without these two the Organization menu has no
    -- Departments entry and there is no way to create one.
    'FEATURE_ORGANIZATION',
    'FEATURE_ORGANIZATION_DEPARTMENT'
  )
);

COMMIT;

-- Verify what stays enabled:
SELECT DISTINCT f.code
FROM feature_organization fo JOIN feature f ON f.id = fo."featureId"
WHERE fo."isEnabled" = true
ORDER BY f.code;

-- ---------------------------------------------------------------------------
-- To RESTORE all modules (undo): enable every feature again.
--   UPDATE feature_organization SET "isEnabled" = true;
-- ---------------------------------------------------------------------------
