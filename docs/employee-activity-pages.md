# Employee list and activity pages — specification

**Status: specification, not built.** This describes a restructure of how an
admin or manager reaches one employee's tracking data. Three open questions at the
end need answers before implementation; the first removes a page with no
replacement, so it is not a detail.

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

The Employees group stops being a group. It becomes a **direct link** to the
employee list, with no children, and Screenshots sits beside it as its own entry.

| Item | Link | Change |
|---|---|---|
| **Employees** | `/pages/employees` | now a leaf — clicking it opens the list directly |
| **Screenshots** | `/pages/employees/activity/screenshots` | new, its own link after Employees |

Everything that used to hang under Employees is gone from the sidebar:

| Removed | Where it went |
|---|---|
| Manage | *is* Employees now — the link goes straight to the list |
| Time & Activity | the App and Visited sites tabs |
| Productivity | the Productivity tab |
| Timesheets | nowhere — see the open question below |

Screenshots keeps a link of its own because it is opened directly and
repeatedly. Everything else is reached by picking an employee from the list
first, which is the point of the restructure.

**This is a structural change to the menu, not a relabelling.** In
`base-nav-menu.component.ts` `_getEmployeesMenu()`, `employees` is currently a
section with an `items` array and no `link` of its own; it becomes an item with a
`link` and no `items`. The expand/collapse chevron disappears with the children.
Its `permissionKeys` (`ORG_EMPLOYEES_VIEW`) and `featureKey` move onto the leaf
so the same people see it and the SQL feature trim still governs it. Screenshots
takes the `featureKey` Time & Activity used, so
`config/minimal-tracking-features.sql` continues to control it.

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
| Actions | vertical 3-dot menu | **Edit** and **Delete** |

Removed: Income, Expenses, Bonus average, Tags — none of them are tracking data,
and they are the reason the table is too wide to read.

The last column is a **vertical 3-dot button** opening a menu with **Edit** and
**Delete**, not a bare Edit link. Two reasons: a delete needs somewhere to live
and should not sit in the row as a standing button next to Edit, and the menu
absorbs later actions without another column. Use Nebular's `nbContextMenu` with
a per-row `nbContextMenuTag`, the pattern already used by the timesheet and
invoice tables — the tag is what stops every row's menu opening at once.

Delete must confirm before acting, and it deletes the EMPLOYEE record, not the
tracked history. What happens to a deleted employee's time slots and screenshots
is a data-retention question this spec does not answer.

`apps/gauzy/src/app/pages/employees/employees.component.ts` builds these settings
around line 700.

## 3. Employee detail page — `/pages/employees/activity/:employeeId/…`

Clicking a name or ID opens the employee's own activity page. **The employee is
part of the URL**, not a dropdown selection, so the view is linkable and survives
a refresh.

**All seven are tabs on this one page** — a single tabset across the top, not
seven sidebar entries and not seven separate pages. The employee is chosen once,
from the list, and every tab then shows that same employee. Switching tabs
changes only the last path segment; the employee and the selected date persist
across the whole set.

| Tab | Route | Component | Comes from |
|---|---|---|---|
| Productivity | `productivity` | `ProductivityComponent` | My work |
| App categories | `app-categories` | `AppCategoriesComponent` | My work |
| Apps & URLs | `apps-urls` | `AppsUrlsReportModule` | My work |
| App usage | `app-usage` | `AppUsageComponent` | My work |
| App | `apps` | `AppUrlActivityComponent` | Time & Activity |
| Visited sites | `urls` | `AppUrlActivityComponent` | Time & Activity |
| Screenshots | `screenshots` | `ScreenshotModule` | Time & Activity |

Nothing here is new work beyond routing: all seven components exist and are in
use today. The change is where they are reached from.

All three of `apps`, `urls` and `apps-urls` are kept as tabs, decided
deliberately. `apps` and `urls` are the same component filtered two ways and
`apps-urls` is the combined report, so two of them are subsets of the third —
that redundancy is accepted because each answers a question people actually ask
("which applications", "which sites", "everything") without making anyone filter.

The header employee dropdown is **removed on this page**. It is redundant once
the employee is in the URL, and two sources of truth for the same selection is
the bug described above.

Every tab keeps the date-picker configuration its route already declares —
single-day for the activity tabs, week for Apps & URLs. Changing that silently
alters what each page shows.

## 4. My work — same tabs, same gates

`/pages/employees/my-work` gains the same seven tabs, scoped to the signed-in
employee. Registered in `MyWorkLayoutComponent.registerPageTabs()`; note that a
route without a matching tab registration is reachable by URL but invisible.

**An employee still sees Productivity and nothing else.** The existing
`ORG_EMPLOYEES_VIEW` gates stay on every other tab, so in practice the seven-tab
set is what an admin or manager sees when they open My work — the employee's own
view is unchanged. That was settled deliberately: how long you worked is a fact
about you, but the app classification, your URL history and the raw app list are
management views, and showing someone the rule being applied to them is a
different product decision from showing them their hours.

The gate belongs on both the tab registration and the route, as it is today:
hiding a tab is presentation, and only the route guard refuses a typed URL.

## Open questions

**1. Timesheets becomes unreachable.** It is on the sidebar today and is not in
the seven-tab list, so removing the sidebar entry leaves no route to it. Either
it is genuinely unwanted and should be dropped from the feature toggles too, or
it needs to be an eighth tab. It is Gauzy's own approvals-and-hours view, not
one of ours.

**2. Does the header employee dropdown disappear everywhere, or only here?**
Other pages (Timesheets, Time & Activity) still use it. Removing it globally is a
larger change; leaving it elsewhere means the header differs between pages.

**3. Employee ID in the table.** Gauzy IDs are UUIDs
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
