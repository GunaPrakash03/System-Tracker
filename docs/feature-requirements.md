# System-Tracker — Phase 2 Feature Requirements

**Status:** partly built. The **tracker half of features 1 and 2 is implemented
and running** (2026-08-07); everything else still needs the decisions at the
foot of this document. What is done:

| Piece | State |
|---|---|
| Per-employee settings resolver (`fetch_employee_settings` / `setting`) | **Built** |
| #1 screenshot interval, per employee | **Built** — cadence snaps to the slot grid |
| #2 media-as-idle, per employee | **Built** — media with no input counts idle |
| Admin surface (`admin/settings_app.py`) | **Built** — separate app, decision 6 = option B |
| #3 departments + app categories | **Built** — matched by process name, applied at report time |
| #4 Manager/HR roles | **Written** — run `config/roles-manager-hr.sql` |
| #5 website URLs | **Closed** — page titles only, no work needed |

The tracker defaults are unchanged, so a box with no settings service behaves
exactly as before. Point `settings_url` at a service returning
`{"screenshot_interval_seconds": 300, "count_audio_as_active": false}` and the
per-employee behaviour switches on with no restart.
**Legend for "Where":** `Tracker` = the Python agent · `Gauzy-config` = existing
Gauzy feature, just configured · `Gauzy-source` = needs modifying the Gauzy
Angular/NestJS source (a fork, rebuild) · `New` = new build (data model + UI).

---

## Summary

| # | Feature | Where | Effort |
|---|---|---|---|
| 1 | Super-admin sets screenshot interval, **per user** | Tracker + Gauzy-source | Medium |
| 2 | Idle-time tracking; per-user select; background media (Spotify/YouTube) counts as **idle** | Tracker + Gauzy-source | Medium |
| 3 | **Department** tab; apps grouped Productive / Neutral / Unproductive, per department; pick department when creating an employee | New + Gauzy-source | **Large** |
| 4 | Super-admin creates **roles** (Manager, Employee, HR); only super-admin may create them | Gauzy-config | Small |
| 5 | Capture **website URLs** and show them in reports | Tracker (+ browser extension) | Medium–Large |

---

## 1. Admin-defined screenshot interval, per user

**Request:** The super admin decides how often screenshots are taken, and the
interval can differ from one user to another (e.g. user A every 1 min, user B
every 5 min).

**Approach**
- The tracker already reads the per-employee **Allow Screen Capture** toggle
  live from Gauzy. Extend that: also read a per-employee **screenshot interval**.
- Gauzy has an org-level `screenshotFrequency` (allowed values 1/3/5/10 min) but
  **not per-employee**. So we add a per-employee interval — either a new field on
  the employee, or a small admin-managed settings table the tracker reads.
- Tracker fetches its user's interval each cycle (cached), and captures on that
  cadence, independent of the process-scan interval.

**Notes / decisions**
- Allowed interval values? (Gauzy uses 1/3/5/10 min — keep that set, or free
  choice in seconds?)
- Where the super admin sets it: on the **Employees → Edit** page (needs a
  Gauzy-source field) or a dedicated settings screen.

---

## 2. Idle-time tracking, per-user, with media-as-idle

**Request:**
- Track idle time, with a **select list to choose users one by one**.
- If a user is only running a **background app like Spotify or YouTube** while
  otherwise idle (no keyboard/mouse), that time should count as **IDLE**, not
  active.

**Approach**
- The tracker already computes active vs idle from keyboard/mouse + audio. Today
  `count_audio_as_active = true` makes background media count as **active**. This
  request is the **opposite** for these users — so make it a per-user setting the
  admin controls: *"count background media as idle."*
- Per-user selection = the same admin settings source as #1, chosen per employee.
- Idle report = a view/filter where the admin selects a user and sees their
  active vs idle breakdown (Gauzy already has activity %; we surface an explicit
  idle column and the media-driven idle).

**Notes / decisions**
- Confirm the intent: *background media with no input = **idle*** (this reverses
  today's default). Correct?
- "Actively watching" YouTube (fullscreen/focused) vs "background Spotify" — do
  we distinguish, or is any media-without-input idle? (Simplest: media without
  input = idle. Distinguishing needs the focused-window + audible checks.)

---

## 3. Departments & app productivity categories

**Request:**
- A new **Department** tab.
- Within a department, every app is categorised into **3 types**:
  **Productive**, **Neutral**, **Unproductive**.
- The categorisation **differs by department** — e.g. an app productive for a
  Developer may be unproductive for Sales. Departments include Developer,
  Tester, Accounts, Sales, … and **new departments can be added**.
- **Apps can be added** to the lists.
- When **creating an employee**, choose their department.

**Approach** (this is the biggest item)
- Gauzy already has **Departments** (`organization_department`) and employees can
  belong to one — so "assign department on employee create" is mostly
  Gauzy-config, but the create form may need the field surfaced (Gauzy-source).
- The **productive/neutral/unproductive per-department app mapping does NOT exist
  in Gauzy** — it is new:
  - New data model: `(department, appName) -> category`.
  - New admin UI (the "Department" tab) to manage departments, apps, and the
    category of each app per department.
  - The tracker (or a server-side job) tags each captured app with its category
    based on the employee's department, feeding productivity into reports.
- Report: per-employee/department **Productive vs Neutral vs Unproductive** time,
  from the apps the tracker already captures.

**Notes / decisions**
- Is category assigned **per department** (same app can be productive in one,
  unproductive in another) — confirmed from the request, yes.
- Default category for an app not yet classified? (suggest **Neutral**.)
- Match apps by process name (what the tracker reports) and/or window title?

---

## 4. Roles & permissions (super-admin managed)

**Request:** The super admin can create roles — **Manager, Employee, HR** — and
**only the super admin** may create roles.

**Approach**
- Gauzy **already has** a full role + permission system (`role`,
  `role_permission`) with SUPER_ADMIN, ADMIN, EMPLOYEE, etc., and a **Roles &
  Permissions** admin screen. Custom roles can be added and permissions toggled.
- So this is mostly **configuration**: create Manager / HR roles, set their
  permissions, and ensure the "manage roles" permission is granted to
  SUPER_ADMIN only (it already is by default).

**Notes / decisions**
- List the exact permissions each role should have (what can Manager / HR see or
  do?). That drives the permission toggles.

---

## 5. Website URL capture in reports

**Request:** Capture the **website URL** the user is on and include it in the
reports.

**Approach & the hard limit**
- The tracker already records the **active browser tab's page title** as a `URL`
  activity → shows in Gauzy's **Visited Sites**.
- **Full URLs are not available from the OS** — window titles never contain the
  URL, and other tabs are invisible. Getting the actual `https://…` needs one of:
  - a **browser extension** (most reliable; per-browser), or
  - **AT-SPI accessibility** integration (Chrome started with
    `--force-renderer-accessibility`; heavier).
- Both were previously **out of scope by request**. If URLs (not just titles)
  are now required, we pick one of those; otherwise reports show page **titles +
  domain** parsed from the title where possible.

**Notes / decisions**
- Do you need the **full URL**, or is the **site/domain + page title** enough?
  (Domain-only can often be derived from the title/tab; full path needs an
  extension.)

---

## Cross-cutting: where the admin controls live

Features 1, 2, and part of 3 need **per-employee settings the super admin edits
in the dashboard**. Two ways to provide that surface:

- **A. Extend Gauzy** (source change + rebuild) — add the fields to the
  Employees screens. Most integrated, but a fork + rebuild (same cost as the
  dashboard changes already in `dashboard-mods/`).
- **B. A small separate admin page** (outside Gauzy) writing to a settings table
  the tracker reads. No Gauzy fork; another small app to host.

Recommendation: **B** for the custom bits (intervals, media-idle, department app
categories) to avoid growing the Gauzy fork; **Gauzy-config** for roles and
departments that already exist there.

---

## Open questions to confirm before building

1. Screenshot interval: fixed set (1/3/5/10 min) or free seconds? Set where?
2. Media-as-idle: confirm background media **without input = idle**. Distinguish
   actively-watched video from background audio, or not?
3. Departments: default category for unclassified apps = Neutral, ok? Match by
   process name, window title, or both?
4. Roles: exact permissions for Manager / HR / Employee.
5. URLs: full URL (needs a browser extension) or domain + title is enough?
6. Admin surface: extend Gauzy (fork/rebuild) or a separate lightweight admin
   page (option B)?

Once you confirm these, this becomes the build plan.
