# Manager role and per-page visibility

**Status: implemented (2026-08-10).** Section 8 records the decisions taken at
review and the one assumption still standing; section 10 records what shipped
and how it was verified.

The goal is a middle tier between "sees everything" and "sees only themselves".
A manager should see the tracking data of the employees assigned to them, and
nobody else's. Employees keep a small self-service view. Everything else stays
with the super admin and admin.

## 1. What Gauzy already provides

Most of this exists; the work is configuration plus one backend filter, not a
new subsystem.

| Building block | State today | Where |
|---|---|---|
| `MANAGER` role | Exists in `RolesEnum`, seeded per tenant, **0 users** | `packages/contracts/src/lib/role.model.ts:24` |
| Manager's permissions | 13, all strategic-initiative and plugin — nothing about employees or tracking | `role_permission` table |
| Role editing UI | Settings → Roles & Permissions | `/pages/settings/roles-permissions` |
| Employee → manager link | `organization_team_employee.roleId` — a team member can hold the MANAGER role *within a team* | `organization_team` tables |
| "See only my own data" | Already enforced server-side | `statistic.service.ts:2655` |

That last row matters more than it looks. The API already contains:

```ts
if (user.employeeId && (isOnlyMeSelected || !hasChangeSelectedEmployeePermission)) {
    employeeIds = [user.employeeId];
}
```

So visibility is currently **binary**: hold `CHANGE_SELECTED_EMPLOYEE` and see
everyone, or lack it and see only yourself. The manager tier is a third case
inserted at exactly this point — see §5.

There is no `employee.managerId` column, and none should be added. Gauzy models
this relationship through teams, and reusing that keeps the admin UI, the API
and the seed data working as-is.

## 2. Creating the manager role in the dashboard

The role already exists, so nothing is *created*. It is configured:

1. **Settings → Roles & Permissions**, pick **Manager** from the role dropdown.
2. Enable the permissions in the table below.
3. Log the manager out and back in. Permissions are cached in `localStorage`
   (`_gauzyStore`) and only refresh on a fresh login — the same caching that
   applies to feature toggles.

Permissions to enable for MANAGER:

| Permission | Why |
|---|---|
| `TIME_TRACKING_DASHBOARD` | Reach the tracking pages at all |
| `ORG_EMPLOYEES_VIEW` | Read employee records (names, departments) |
| `SELECT_EMPLOYEE` | Show the employee selector in the header |
| `CHANGE_SELECTED_EMPLOYEE` | **See §5 — this is the one that needs care** |

`CHANGE_SELECTED_EMPLOYEE` is the crux. Granted as-is it means *any* employee,
which is precisely what we are trying to prevent. It cannot simply be switched
on; the backend filter in §5 must land first, so that the permission means "may
change the selected employee **within the set I manage**".

Deliberately **not** granted: `ORG_EMPLOYEES_EDIT`, `ORG_EMPLOYEES_DELETE`,
`CAN_APPROVE_TIMESHEET`, `TIMESHEET_EDIT_TIME`. A manager reads; they do not
edit people or rewrite time.

## 3. Assigning employees to a manager

Recommended: **Organization Teams**, because it is native and needs no schema
change.

1. Organization → Teams → **Add Team** (e.g. "Night Shift").
2. Add the employees as members.
3. Add the manager as a member and set their team role to **Manager**.

One manager, one team is the simplest arrangement. An employee may sit in
several teams, which means several managers can see them — intentional, and it
falls out of the model for free.

The alternative — a `managerId` column on `employee` — is simpler to query but
means new migrations, new admin UI, and a second concept that duplicates teams.
Not recommended unless review says a strict one-manager-per-employee rule must
be enforced by the database.

## 4. Visibility matrix

An employee gets **one page**, "My work", showing their own data only.

**Revised after review (2026-08-10):** the employee sees **Productivity alone**.
Apps & URLs and App usage were built as tabs there, then restricted to admins
and managers on request. Employees also lost the Dashboards menu, which reports
across people and projects.

| Tab | Route | Employee sees it? |
|---|---|---|
| Productivity | `/pages/employees/my-work/productivity` | ✅ |
| Apps & URLs | `/pages/employees/my-work/apps-urls` | ❌ admin/manager |
| App usage | `/pages/employees/my-work/app-usage` | ❌ admin/manager |

| Data / page | Employee | Manager | Admin | Super admin |
|---|---|---|---|---|
| Productivity, own data | ✅ | ✅ | ✅ | ✅ |
| Productivity, another employee's data | ❌ | ✅ *managed only* | ✅ all | ✅ all |
| Apps & URLs, App usage | ❌ | ✅ *managed only* | ✅ all | ✅ all |
| Dashboards (organisation-wide) | ❌ | ✅ | ✅ | ✅ |
| Timesheets, Time & Activity, other reports | ❌ | ✅ *managed only* | ✅ all | ✅ all |
| **Screenshots** | ❌ | ✅ *managed only* | ✅ all | ✅ all |
| Employee list | ❌ | ✅ *managed only* | ✅ all | ✅ all |
| Settings, Tracker Settings, roles | ❌ | ❌ | ✅ | ✅ |

"Managed only" means: employees sharing a team in which the user holds the
MANAGER role.

## 5. Backend enforcement

**This is the part that must not be skipped.** Hiding a menu item or guarding a
route only changes what the UI draws — the API still answers. Anyone can read a
token out of `localStorage` and call `/api/timesheet/statistics` directly. If
the filter is not server-side, the feature is decorative.

Introduce one helper that answers *whose data may the caller see*, and route
every tracking query through it:

```
resolveVisibleEmployeeIds(user) ->
  SUPER_ADMIN / ADMIN                  -> null            (no restriction)
  holds MANAGER role in >= 1 team      -> employee ids of those teams' members
  otherwise, has employeeId            -> [user.employeeId]
  otherwise                            -> []              (nothing)
```

Then replace the binary check at `statistic.service.ts:2655` with a call to it,
and intersect any client-supplied `employeeIds` against the result — never trust
the request's list. A manager asking for an employee outside their teams must
get an empty result, not an error, so the response shape stays uniform.

The same helper needs applying to every endpoint the three pages and the reports
use — statistics, activity, time slots, screenshots. Auditing that list is part
of the work; missing one endpoint is a data leak, not a cosmetic bug.

## 6. Frontend

Frontend changes are for usability, not security — §5 is the enforcement.

- **Menu**: the sidebar already hides items by `featureKey`
  (`base-nav-menu.component.ts:1303`). Role-based hiding uses the existing
  permission mechanism on the same items.
- **Route guards**: attach `PermissionsGuard` with the appropriate permission to
  the three routes, so a typed URL does not render a broken page.
- **Employee selector**: `employee.component.ts:395` already gates the "All
  Employees" option on `CHANGE_SELECTED_EMPLOYEE`. For a manager the dropdown
  must list only managed employees — the selector should take its list from the
  same server-side helper rather than fetching all employees.

## 7. Implementation order

Each phase is independently testable, and the risky one is first on purpose.

1. **Backend scoping helper** and its application to every tracking endpoint.
   Verify with direct API calls using a manager's token, not through the UI.
2. **Role configuration** — MANAGER permissions per §2.
3. **Team assignment** — create a team, assign a manager, confirm scoping via
   the API.
4. **Frontend** — guards, menu visibility, selector list.
5. **Screenshot restriction** once §8 is settled.

## 8. Decisions taken at review

1. **Screenshots are visible to managers**, scoped to the employees they manage
   — the same rule as every other data type. The screenshot endpoints therefore
   go through the §5 helper like the rest; they are not a special case.

2. **Employees get a single tabbed dashboard**, not three sidebar links. The
   three existing pages become tabs within it (§4). This also settles the
   landing-route problem: that dashboard is where an employee lands at login.

3. **Multiple managers per employee** is allowed, as it falls naturally out of
   team membership.

Still assumed, not confirmed: **a manager sees their own tracking data
alongside their team's**, on the grounds that a manager is normally also an
employee. This is one line in the §5 helper (`ids.add(user.employeeId)`) and is
trivial to reverse — but note it means team totals include the manager.

## 9. Risks

- **The API is the boundary.** Repeating §5 because it is the one way this
  feature fails silently: menu hiding is not access control.
- **`CHANGE_SELECTED_EMPLOYEE` is coarse.** It currently means "any employee".
  Granting it to managers before the backend filter exists opens full visibility
  to every manager. Order matters.
- **Permissions are cached client-side.** Any role change needs a full logout
  and login to take effect; a refresh is not enough.
- **`ever-gauzy` is a read-only reference** in this project's terms, yet §5 and
  §6 both modify it. That is a deliberate departure worth acknowledging — it
  follows the precedent already set by the tracker-settings and productivity
  pages, but it does mean carrying local patches against upstream.

## 10. What shipped, and the bug that nearly shipped with it

Backend (`ever-gauzy/packages/core`):

- `employee/managed-employee.service.ts` — gained an "any team" fallback so a
  manager is scoped on pages that filter by employee and date rather than by
  team, which is all three of the pages here. The unrestricted check moved from
  a *permission* test to a *role* test: a manager must hold
  `CHANGE_SELECTED_EMPLOYEE` for the selector to render, so keying admin bypass
  off that permission would have handed every manager the whole organisation.
  Roles other than a team manager keep their previous behaviour.
- `time-tracking/time-slot.service.ts`, `time-tracking/activity.service.ts` —
  routed through the same filter; both previously used the own-or-everything
  check. Screenshots follow time slots, so they are covered by the former.
- `employee/employee.service.ts` — `findWorkingEmployees` and its count are now
  scoped. This is the endpoint behind the employee selector, and it was
  returning every employee in the organisation to a manager: the data was
  denied but the names were not.

Frontend (`ever-gauzy/apps/gauzy`, `packages/ui-core`):

- `pages/employees/my-work/` — the tabbed page, with `AppUsageComponent` lifted
  into its own module so two pages can host it.
- Screenshots route now carries `PermissionsGuard` with `ORG_EMPLOYEES_VIEW`,
  which employees lack — otherwise the page was reachable by typing the URL.
- "My work" added to the sidebar; `MENU.MY_WORK` added to `en.json`.

**The bug worth remembering.** The first working version leaked. When a manager
asked for an employee outside their team, the filter correctly narrowed the list
to empty — and every downstream query reads an empty employee list as *no
filter*, meaning all employees. "May see nobody" silently became "may see
everybody": the manager received all 118 slots. The fix is the
`NO_ACCESSIBLE_EMPLOYEES` sentinel — a uuid matching no row — so a denied caller
gets zero rows. Anything added later that resolves employee ids must go through
the same helper rather than returning a bare `[]`.

Verified against the live API, admin versus manager:

| Request | Admin | Manager |
|---|---|---|
| Time slots, unfiltered | 124 slots, 2 employees | 3 slots, 1 employee |
| Time slots, naming an employee outside the team | 115 slots | 0 slots |
| Activities, employee not in team | 30 | 0 |
| Same employee after joining the team | 30 | 30 |
| Employee list (selector) | 5 | 2 |

The fourth row is the one that proves it: access appeared purely from team
membership and matched the admin figure exactly, then disappeared when the
membership was removed.

Test fixtures left in the database: user `test-manager@example.com` (password
`admin`) managing `guna05026@gmail.com` through a team called "Scope Test Team".
Delete both when they are no longer wanted.

## 11. Sidebar gating (added 2026-08-10)

Blocking a page means two changes, always: hide the menu entry *and* guard the
route. A hidden link is presentation only — the page is still reachable by
typing its URL.

`ORG_EMPLOYEES_VIEW` is the single separator throughout. Employees do not hold
it; managers and admins do.

| Blocked for employees | Menu | Route guard |
|---|---|---|
| Dashboards | `permissionKeys` on the item | `pages.routes.ts`, redirects to My work |
| Apps & URLs, App usage | tab `permissions` | `my-work.module.ts`, redirects to Productivity |
| Screenshots | — | `activity.module.ts` |
| Employees, Organization | `permissionKeys` on the group | (children already guarded) |

**A parent with no visible children is now hidden too.** Most top-level groups —
Accounting, Tasks, Employees, Organization, Goals — carry no feature key or
permission of their own; only their children do. Trimming features therefore
emptied each group but still drew its header, leaving an employee with a sidebar
of sections that opened onto nothing. `mapMenuSection` now hides a group whose
children are all hidden, which fixed four groups at once and keeps working as
more features are trimmed.

Employees and Organization needed explicit gates anyway: each still had one
child an employee could legitimately reach (Timesheets via `TIME_TRACKER`,
Departments via its feature flag), so the empty-parent rule could not help.

Verified with Playwright, both roles, fresh sessions:

| | Employee | Admin |
|---|---|---|
| Lands on | `/my-work/productivity` | `/dashboard/time-tracking` |
| Sidebar | My work only | Dashboards, My work, Employees, Organization |
| My work tabs | Productivity | Productivity, Apps & URLs, App usage |

## 12. Creating people with a role

The Add Employee form now carries a **Role** field — Employee, Manager or Admin
— and it is required, so the role is a deliberate choice rather than a silent
default.

The dropdown already existed in `BasicInfoFormComponent`, hidden behind
`[isShowRole]="false"`. What was missing was the plumbing: the dialog never
passed the choice, and the API hardcoded `RolesEnum.EMPLOYEE`.

Granting a role is privilege-granting, so the server decides rather than
trusting the request (`employee.create.handler.ts`, `resolveRoleName`):

| Requested | Result |
|---|---|
| `MANAGER` | MANAGER |
| `ADMIN` by a super-admin or admin | ADMIN |
| `SUPER_ADMIN` | **EMPLOYEE** — never grantable this way |
| anything else, or omitted | EMPLOYEE |

`SUPER_ADMIN` is refused outright: it would let an admin mint an account
outranking their own. The `ADMIN` check is explicit rather than relying on
`ORG_EMPLOYEES_ADD`, which is grantable to a custom role.
