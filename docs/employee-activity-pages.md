# Employee list and activity pages — specification

**Status: specification, not built.** This describes a restructure of how an
admin or manager reaches one employee's tracking data. Four open questions at the
end need answers before implementation; two of them contradict decisions already
taken, so they are not details.

## The problem

Today an employee is chosen from a **dropdown in the page header**, and the page
below it changes. That has three costs:

- The selection is invisible in the URL, so a view cannot be linked or bookmarked
  and a refresh can land somewhere else.
- Header selector and page can disagree — the failure already recorded in
  `productivity.component.ts`, where a second in-page dropdown produced an empty
  report that read as a fault rather than a mismatch.
- There is no list. To answer "who is not tracking?" you open the dropdown and
  click through people one at a time.

The fix is the conventional one: a **list**, and a **detail page per employee**
with the employee in the URL.

## 1. Sidebar

Under **Employees**, add a direct entry for Screenshots:

| Item | Link |
|---|---|
| Manage | `/pages/employees` |
| Time & Activity | `/pages/employees/activity` |
| **Screenshots** *(new)* | `/pages/employees/activity/screenshots` |
| Productivity | `/pages/employees/productivity` |
| Timesheets | `/pages/employees/timesheets` |

Defined in `packages/ui-core/core/src/lib/components/base-nav-menu/base-nav-menu.component.ts`,
`_getEmployeesMenu()`. Screenshots takes the same `permissionKeys` and
`featureKey` as Time & Activity, so the trim in
`config/minimal-tracking-features.sql` keeps them together rather than leaving
one visible and the other hidden.

## 2. Employee list page — `/pages/employees`

Columns, replacing the current set:

| Column | Source | Note |
|---|---|---|
| Employee ID | `employee.id` | Short form; the full UUID is unreadable in a table |
| Employee Name | `user.name` | **Links to the detail page** |
| Email | `user.email` | |
| Role | `user.role.name` | Not currently shown |
| Department | organisation department | Not currently shown; drives app categorisation |
| Time Tracking | `employee.isTrackingEnabled` | Already present |
| Status | active / inactive | Already present |
| Screen Capture | `employee.allowScreenshotCapture` | Already present |
| Edit | link to the employee edit page | |

Removed: Income, Expenses, Bonus average, Tags — none of them are tracking data,
and they are the reason the table is too wide to read.

`apps/gauzy/src/app/pages/employees/employees.component.ts` builds these settings
around line 700.

## 3. Employee detail page — `/pages/employees/activity/:employeeId/…`

Clicking a name or ID opens the employee's own activity page. **The employee is
part of the URL**, not a dropdown selection, so the view is linkable and survives
a refresh.

Tabs:

| Tab | Route | Component |
|---|---|---|
| Productivity | `productivity` | `ProductivityComponent` |
| App categories | `app-categories` | `AppCategoriesComponent` |
| Apps & URLs | `apps-urls` | `AppsUrlsReportModule` |
| App usage | `app-usage` | `AppUsageComponent` |
| App | `apps` | `AppUrlActivityComponent` |
| Visited sites | `urls` | `AppUrlActivityComponent` |
| Screenshots | `screenshots` | `ScreenshotModule` |

The header employee dropdown is **removed on this page**. It is redundant once
the employee is in the URL, and two sources of truth for the same selection is
the bug described above.

Every tab keeps the date-picker configuration its route already declares —
single-day for the activity tabs, week for Apps & URLs. Changing that silently
alters what each page shows.

## 4. My work — same tabs

`/pages/employees/my-work` gains the same seven tabs, scoped to the signed-in
employee. Registered in `MyWorkLayoutComponent.registerPageTabs()`; note that a
route without a matching tab registration is reachable by URL but invisible.

## Open questions

**1. Who sees what on My work?** It was decided earlier that an employee sees
Productivity only, and that App categories, Apps & URLs and App usage carry
`ORG_EMPLOYEES_VIEW` so employees do not reach them. Adding all seven tabs to My
work either keeps those gates — in which case an employee still sees one tab and
nothing changes for them — or drops them, which reverses that decision and shows
every employee their own URL history and app classification. **These are
different products.** No default is safe here.

**2. "App" versus "Visited sites" versus "Apps & URLs".** Gauzy has three
overlapping views: `apps` and `urls` (both `AppUrlActivityComponent`, filtered)
and the combined `apps-urls` report. Listing all three gives two tabs that are
subsets of a third. Recommend either the combined report **or** the pair, not
both — but confirm which.

**3. Does the header employee dropdown disappear everywhere, or only here?**
Other pages (Timesheets, Time & Activity) still use it. Removing it globally is a
larger change; leaving it elsewhere means the header differs between pages.

**4. Employee ID in the table.** Gauzy IDs are UUIDs
(`f58e24df-e425-48c1-a2d3-298c10a78acc`). A column of those is unreadable and
unmemorable. Options: show the first segment, add a short sequential staff number
of our own, or drop the column and rely on name plus email. A staff number is
genuinely useful but is new data to store and maintain.

## Work estimate

Assuming the open questions are answered and no scope moves:

| Task | Hours |
|---|---|
| Sidebar entry for Screenshots | 1 |
| Employee list columns — add Role, Department, ID, Edit; remove four | 4 |
| Detail route with `:employeeId`, resolver, tab registration | 6 |
| Point the components at the route param rather than the header selector | 5 |
| Remove the dropdown on that page; keep it working elsewhere | 2 |
| My work tab set | 2 |
| Build, verify each tab against real data, fix what surfaces | 6 |
| **Total** | **26 h ≈ 3–4 days** |

The fourth row is the one that will move. Every one of these components currently
reads `store.selectedEmployee$`; switching them to a route parameter touches the
data-loading path of seven pages, and that is exactly where today's defects came
from.
