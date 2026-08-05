# Gauzy Customization — Feasibility Assessment

**Date:** 5 August 2026
**Source examined:** `/home/sys0041/ever-gauzy` (cloned Ever Gauzy source, AGPL-3.0)
**Question:** Can we (1) remove unneeded modules and (2) add background-app tracking?

> **Update — the Wayland question below is now resolved.** The machine has since
> been configured to log in on **Xorg**, which takes **Option A** (see
> *Options for background-window capture*) off the table as a hypothetical and
> makes it real. `tracker/proc_tracker.py` now enumerates every open window with
> its title via `_NET_CLIENT_LIST`, matches the focused window to its process by
> `_NET_WM_PID`, and reads idle time from the X server — so the GNOME "Focused
> Window D-Bus" extension is no longer required. What did **not** change: browser
> **tabs** are still not OS windows, so per-tab and per-URL tracking remains
> extension-only. Everything below is the original assessment, kept as written.

---

## Verdict at a glance

| Request | Possible? | Needs code changes? | Effort |
|---|---|---|---|
| Remove **Projects, Accounting, Goals, Contacts, Jobs, Sales** | ✅ Yes | ❌ **No** — built-in feature toggles | ~1 hour |
| Track **background apps** (VS Code, Postman, Antigravity — not just focused) | ⚠️ Yes, with caveats | ✅ Yes — modify the desktop agent | Days |
| Track **individual browser tabs** in the background | ❌ Not realistically | — | Not recommended |

**Bottom line:** Request 1 is trivial and needs no code. Request 2 is real development work, and on your current **Wayland** session it hits the same wall we already found — so it likely needs either an Xorg session or a different capture method I'd have to build.

---

## Request 1 — Remove unneeded modules ✅ EASY

**You do not need to modify code for this.** Gauzy ships a **feature-toggle system**, and every module you listed is already a defined feature. Found in `packages/contracts/src/lib/feature.model.ts`:

| Module you want gone | Feature flag(s) to turn off |
|---|---|
| Projects | `FEATURE_ORGANIZATION_PROJECT` |
| Accounting | `FEATURE_INVOICE`, `FEATURE_INVOICE_RECURRING`, `FEATURE_INVOICE_RECEIVED`, `FEATURE_INCOME`, `FEATURE_EXPENSE`, `FEATURE_PAYMENT`, `FEATURE_ESTIMATE`, `FEATURE_ESTIMATE_RECEIVED` |
| Sales | `FEATURE_PROPOSAL`, `FEATURE_PROPOSAL_TEMPLATE`, `FEATURE_PIPELINE`, `FEATURE_PIPELINE_DEAL` |
| Goals | `FEATURE_GOAL`, `FEATURE_GOAL_REPORT`, `FEATURE_GOAL_SETTING` |
| Contacts | `FEATURE_CONTACT` |
| Jobs | `FEATURE_JOB` |

**How to turn them off — two ways, no rebuild:**

1. **In the web UI (easiest).** Sign in as SUPER_ADMIN → **Settings → Features** (backed by `feature-toggle.controller.ts`). Flip each feature off. The sidebar items disappear immediately.
2. **At the database/seed level.** The `feature` / `feature_organization` tables hold the on/off state per tenant; a single SQL update disables them for your tenant.

**What "off" actually does:** hides the menu item and blocks the routes/API for that feature. The backend code still *exists* in the image (it's a monorepo — you can't cheaply delete a NestJS module without breaking build-time dependencies), but users never see it and can't reach it. For your purpose — a clean, focused UI — that is exactly the right outcome and costs nothing.

> **Recommendation:** Do NOT delete these modules from source. Toggling them off gives you the clean product you want while keeping the codebase buildable and upgradeable. Deleting them means fighting cross-module dependencies and re-fixing them on every upstream update.

---

## Request 2 — Track background apps ⚠️ POSSIBLE, WITH A REAL CATCH

### What the agent does today

`packages/desktop-activity/src/lib/activity-window.ts` calls **`getActiveWindow()`** — the single *focused* window, once per interval. Everything unfocused is invisible. That is the limitation we already confirmed by observation.

### The good news

The bundled `get-windows` library **also exports `openWindows()`** — which enumerates **every open window**, not just the focused one. It has a Linux backend (`get-windows/lib/linux.js` exports both `activeWindow` and `openWindows`). The agent simply never calls it.

So for windowed apps — **VS Code, Postman, Antigravity, browsers** — the capability to list them while unfocused *exists in code already*. This is an addition, not an invention.

### What building it requires

This is genuine development, not a toggle. The chain:

1. **Capture** — in `activity-window.ts`, add an `openWindows()` poll alongside the existing `getActiveWindow()`, producing a list of all open app windows per interval.
2. **Data model** — the `activity` table has no concept of "background apps." Add a field/table to store the list (a DB migration).
3. **Transport** — extend the agent→server sync (`push-activities`) and an API endpoint to accept it.
4. **UI** — a new view to show "apps open during this slot" (the existing Apps tab shows focused time only).

Roughly **2–4 engineer-days** for a working version, more to make it clean and upgrade-safe.

### The catch you must know before starting ⚠️

**On Wayland (your current session), `openWindows()` probably will not work — for the same reason focused-window capture needed a GNOME extension.**

Recall: on Wayland, apps are forbidden from seeing other apps' windows for security. We only got *focused-window* tracking working by installing the "Focused Window D-Bus" GNOME extension — and that extension exposes **only the focused window, not all of them**. There is no Wayland path for one app to enumerate every other app's windows.

That leaves three options for background tracking on this machine:

| Option | What it captures | Trade-off |
|---|---|---|
| **A. `openWindows()` on an Xorg session** | All windowed apps, with titles | Must log in via "Ubuntu on Xorg" (not Wayland); simplest code |
| **B. Process enumeration via `/proc`** (I'd write this) | Which apps are *running* (VS Code, Postman, node, etc.) — by process, not window | Works on Wayland AND Xorg; but no window titles, no per-window focus; coarser |
| **C. Per-app integrations** (browser extension, editor plugin) | Browser tabs, editor files | Most accurate; most work; one integration per app |

**Your examples matter here:** VS Code, Postman, Antigravity are all *running processes* — Option **B** would reliably tell you they are open, on Wayland, today, with code I can write. It just wouldn't give window titles or say which was in front. If "is this person running VS Code / Postman right now" is the real question, Option B answers it cross-platform.

### Browser *tabs* in the background — not realistic

"Another window tabs" (individual browser tabs) is the hardest case. Tabs are not OS windows — no `openWindows()` or `/proc` method sees them. Only a **browser extension** can, and it only reports the *active* tab, not background tabs. Chrome/Firefox deliberately don't expose all open tabs to native trackers. **Recommendation: drop this sub-requirement** — it's a lot of work for data the browser won't fully give up. (Note: ActivityWatch, already running here, gives you the *active* tab URL via its extension — that's the ceiling for browser data on Linux.)

---

## Recommended plan

1. **Do Request 1 now** — toggle off the six module groups via the Features admin page. Zero code, reversible, ~1 hour. I can do this against your running instance immediately.
2. **For Request 2, decide the real question first:**
   - *"Which apps is someone running?"* → **Option B** (`/proc` process tracker). Works on your Wayland setup. I can prototype it.
   - *"Which app window was in front, including titles, for all open windows?"* → **Option A** — requires switching your login to **Xorg**, then wiring up `openWindows()`.
3. **Drop background browser-tab tracking** — not feasible without per-browser extensions, and even then only the active tab.

## AGPL reminder

Any source modification you deploy to people outside your company triggers AGPL §13 (you must offer them the modified source), and an externally exposed fork must be rebranded off "Ever"/"Gauzy". Internal-only use with an internal repo is fine. Toggling features (Request 1) is configuration, not modification — no obligation at all.

---

## Open questions for you

- For background apps: is the real need **"which apps are running"** (Option B, works now) or **"full window detail"** (Option A, needs Xorg)?
- Are you willing to switch this machine's login session from Wayland to Xorg? It's a one-click choice at the login screen and would unlock the most capability with the least custom code.
- Confirm you want to **toggle** modules off (recommended) rather than **delete** them from source.
