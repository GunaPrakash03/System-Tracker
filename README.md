# System-Tracker

A self-hosted activity- and process-tracking setup for developer workstations,
built on **Ever Gauzy** (organisation layer) and **ActivityWatch** (capture layer),
with custom additions for what neither tool captures on Linux out of the box.

## Goal

Track, per employee, on Ubuntu:

- Active vs idle time, keyboard/mouse activity
- Focused application and window titles
- **Background / headless processes** — dev servers, databases, `node`, `docker`,
  and dev tools (VS Code, Postman, Antigravity) even when not focused
- Browser usage including **YouTube / Spotify** (site + audible state)

…while trimming the Gauzy UI down to only the features we use.

## Platform reality (Ubuntu + Wayland)

Findings from a working trial on this hardware — these drive the design:

| Capability | Gauzy agent (Linux) | ActivityWatch | This project |
|---|---|---|---|
| Focused app + window title | ✅ | ✅ | use existing |
| Idle / keyboard-mouse activity | ✅ | ✅ | use existing |
| Browser tab URL | ❌ macOS-only in code | ✅ via extension | use ActivityWatch |
| Browser audible flag (YouTube/Spotify in bg) | ❌ | ✅ | use ActivityWatch |
| Background / headless processes | ❌ | ❌ | **custom `/proc` tracker** |
| Screenshots | ❌ on Wayland | ❌ | out of scope |
| Org layer (employees, approvals, reports) | ✅ | ❌ | use Gauzy |

**Consequence:** capture is strongest when Gauzy + ActivityWatch + a custom
process tracker are combined, each doing what it does best.

## Scope

1. **Trim Gauzy** — disable unused modules (Projects, Accounting, Sales, Goals,
   Contacts, Jobs) via Gauzy's built-in feature toggles. No source changes.
2. **Background/backend process tracker** — a `/proc`-based watcher that records
   which processes (GUI and headless) are running per interval, and for how long.
   Works on Wayland, unlike window-enumeration approaches.
3. **Media categorisation** — classify browser activity (YouTube, Spotify, etc.)
   from ActivityWatch's `url` + `audible` data, distinguishing *actively watching*
   from *background music*.

See [`docs/feasibility.md`](docs/feasibility.md) for the full assessment,
including what is and isn't possible on Linux/Wayland and why.

## Status

Early — feasibility complete, implementation starting. This repo will hold the
custom tracker code and the deployment/configuration docs.

## Licence note

Ever Gauzy is AGPL-3.0. Configuration (feature toggles) creates no obligation.
Any modified Gauzy exposed to users outside the company triggers AGPL §13
(source-offer) and requires rebranding off the "Ever"/"Gauzy" marks. Custom code
in this repo is separate and can carry its own licence.
