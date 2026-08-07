-- Feature 4 — roles the super admin manages.
--
--   "The super admin can create roles — Manager, Employee, HR — and only the
--    super admin may create roles."
--
-- Two of the three already exist. Gauzy ships MANAGER (26 permissions already
-- enabled) and EMPLOYEE as built-in roles, so nothing is created for them. What
-- is genuinely missing is HR, and the "only the super admin" half — ADMIN also
-- holds CHANGE_ROLES_PERMISSIONS by default, which the requirement rules out.
--
-- Roles are TENANT-SCOPED. That is why every built-in role appears twice in a
-- two-tenant instance; HR is created per tenant for the same reason.
--
-- Run:
--   docker exec -i db psql -U postgres -d gauzy < config/roles-manager-hr.sql
--
-- Afterwards users must FULLY LOG OUT and back in — a refresh is not enough,
-- the old permission list is cached in localStorage (`_gauzyStore`), exactly as
-- with the feature-toggle SQL.
--
-- Idempotent: every statement guards against re-inserting, so running it twice
-- changes nothing the second time.

BEGIN;

-- 1. The HR role, one per tenant.
INSERT INTO role (id, "createdAt", "updatedAt", name, "isSystem", "tenantId",
                  "isActive", "isArchived")
SELECT uuid_generate_v4(), now(), now(), 'HR', false, t.id, true, false
FROM tenant t
WHERE NOT EXISTS (
    SELECT 1 FROM role r WHERE r.name = 'HR' AND r."tenantId" = t.id
);

-- 2. What HR may do.
--
-- People administration and time-off, and enough of the tracking dashboard to
-- see attendance. Deliberately NOT granted:
--   ORG_EMPLOYEES_DELETE      — removing people should stay with an admin
--   CHANGE_ROLES_PERMISSIONS  — the whole point of this file
--   anything financial        — HR is not payroll here
--
-- Adjust in the dashboard under Settings -> Roles & Permissions rather than by
-- editing this file; the UI writes to the same rows.
INSERT INTO role_permission (id, "createdAt", "updatedAt", "tenantId", permission,
                             enabled, "roleId", "isActive", "isArchived")
SELECT uuid_generate_v4(), now(), now(), r."tenantId", p.perm, true, r.id, true, false
FROM role r
CROSS JOIN (VALUES
    ('ORG_EMPLOYEES_VIEW'),
    ('ORG_EMPLOYEES_EDIT'),
    ('ORG_EMPLOYEES_ADD'),
    ('ORG_CANDIDATES_VIEW'),
    ('ORG_CANDIDATES_EDIT'),
    ('TIME_OFF_VIEW'),
    ('TIME_OFF_ADD'),
    ('TIME_OFF_EDIT'),
    ('TIME_OFF_POLICY_VIEW'),
    ('REQUEST_APPROVAL_VIEW'),
    ('REQUEST_APPROVAL_EDIT'),
    ('APPROVALS_POLICY_VIEW'),
    ('TIME_TRACKING_DASHBOARD'),
    ('CHANGE_SELECTED_EMPLOYEE'),
    ('EMPLOYEE_AVAILABILITY_READ')
) AS p(perm)
WHERE r.name = 'HR'
  AND NOT EXISTS (
      SELECT 1 FROM role_permission rp
      WHERE rp."roleId" = r.id AND rp.permission = p.perm
  );

-- 3. Only the super admin may manage roles.
--
-- Out of the box both SUPER_ADMIN and ADMIN hold CHANGE_ROLES_PERMISSIONS. The
-- requirement is super-admin-only, so ADMIN's copy is disabled rather than
-- deleted — the row stays, so an admin can re-enable it in the UI if the policy
-- is ever relaxed.
UPDATE role_permission rp
SET enabled = false, "updatedAt" = now()
FROM role r
WHERE r.id = rp."roleId"
  AND r.name = 'ADMIN'
  AND rp.permission = 'CHANGE_ROLES_PERMISSIONS'
  AND rp.enabled = true;

COMMIT;

-- Verify.
SELECT r.name,
       count(*) FILTER (WHERE rp.enabled) AS enabled_permissions
FROM role r
LEFT JOIN role_permission rp ON rp."roleId" = r.id
WHERE r.name IN ('SUPER_ADMIN', 'ADMIN', 'MANAGER', 'HR', 'EMPLOYEE')
GROUP BY r.name
ORDER BY r.name;

-- Should list SUPER_ADMIN only.
SELECT r.name AS can_manage_roles
FROM role_permission rp
JOIN role r ON r.id = rp."roleId"
WHERE rp.permission = 'CHANGE_ROLES_PERMISSIONS' AND rp.enabled = true;
