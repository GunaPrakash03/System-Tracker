# Gauzy dashboard modifications — the proper (rebuilt) version

Changes applied to the **Gauzy source** and deployed by rebuilding (not a runtime
CSS/JS hack). This file is the build + deploy runbook.

**The source lives in this repo, under `gauzy/`.** The whole Gauzy tree is
vendored here via `git subtree`, so every file is ours to edit directly — there
is no patch to apply and nothing to keep in sync. The customisations are 36 files
of that tree, of which **7 are API files under `packages/core` and
`packages/contracts`**, not UI.

Upstream is still reachable. `git subtree pull --prefix=gauzy <upstream> master
--squash` merges security fixes from `ever-co/ever-gauzy` on top of our changes;
conflicts, when they come, are confined to the files listed below.

The API changes are the reason **Ever's published images cannot be deployed**:
`ghcr.io/ever-co/gauzy-api` does not contain them. Both the API and the webapp
image must be built from this branch. See `docs/railway-deployment.md`.

## What the changes do

| # | Change | File |
|---|---|---|
| 1 | **Remove the start/stop timer** from the dashboard (users can't start/stop tracking) | `packages/ui-core/shared/src/lib/time-tracker/time-tracker/time-tracker.component.html` |
| 2 | **"Worked today" ticks every second** (live), re-syncing to the server each refresh | `packages/plugins/dashboard-time-track-angular-ui/.../time-tracking.component.ts` + `.html` |
| 3 | **Auto-refresh every 60s** instead of 5 min, so the dashboard pulls fresh DB data promptly | same `.ts` (`setAutoRefresh`) |
| 4 | **Settings → Tracker Settings** page: per-employee screenshot interval, media-as-idle, and per-department app categories | `apps/gauzy/src/app/pages/settings/tracker-settings/` (new) |
| 5 | Route + menu entry + translation for #4 | `settings.routes.ts`, `base-nav-menu.component.ts`, `i18n/en.json` |
| 6 | **App usage** and **Productivity** pages under Employees → Activity | `apps/gauzy/src/app/pages/employees/{activity/app-usage,productivity}/` (new) |
| 7 | **My work** layout | `apps/gauzy/src/app/pages/employees/my-work/` (new) |
| 8 | **Manager scoping** — which employees a manager may see | `packages/core/.../employee/managed-employee.service.ts`, `employee.service.ts` |
| 9 | Time-slot and activity services adjusted for tracker-published data | `packages/core/.../time-tracking/{time-slot,activity}/` |
| 10 | Per-employee settings carried on the employee model | `packages/contracts/.../employee.model.ts`, employee DTO + create handler |

Rows 8–10 are **API-side**. They change `packages/core`, so the API image is a
custom build too — this is not a web-only patch set.

## Rebranding — what moved, and what deliberately did not

The product is **Young Globes Workspace**; the company is **Young Globes**.
Trademarks are not covered by the AGPL grant, so dropping the Ever/Gauzy marks
is permitted and expected once this is presented as our own tool. The licence is
a separate matter and does not change (`gauzy/LICENSE` stays).

Most of it is **configuration, not code**. Twenty-two branding values — company
name, site name, every social/download/privacy/TOS link, the logo paths — are
substituted into the already-built JS bundles at container start by
`replacements.sed`. They are pinned in `deploy/docker-compose.yml`; changing one
needs a restart, not a rebuild. Left unset they silently fall back to the
Ever/Gauzy defaults baked into the image, which is why they are all listed
explicitly rather than omitted.

Four code changes were needed, because these are compiled in:

| File | Change |
|---|---|
| `apps/gauzy/src/index.html` | `<title>`, author, description |
| `apps/gauzy/src/manifest.json` | `name`, `short_name` |
| `packages/ui-core/i18n/.../en.json` | theme names, "Workspace features", "Total Hours worked" |
| `deploy/docker-compose.yml` | `APP_NAME` / `APP_SIGNATURE` / `APP_LINK` on the API — without them, invitation and password-reset emails go out signed "Gauzy Team" linking to app.gauzy.co |

**The other 54 "Gauzy" strings in `en.json` were left alone on purpose.** They
divide into two kinds, neither of which should be renamed:

- **JSON keys** (`GAUZY_API_KEY`, `GAUZY_LIGHT`, `invite-gauzy-teams`). Code
  looks these up by name; renaming a key breaks the lookup and yields a blank
  label. Only the values were touched.
- **Names of Ever's actual external services** — Gauzy AI, Ever Gauzy Cloud, the
  Gauzy Desktop/Timer/Server apps, the plugin registry's `Gauzy` source type.
  These are real third-party products we integrate with or migrate to. Calling
  Ever's cloud "Young Globes Workspace Cloud" would be inaccurate, not rebranded.

A blanket find-and-replace would also collide with upstream on every future
`git subtree pull`. Most of these strings sit on pages the feature trim in
`config/minimal-tracking-features.sql` hides anyway.

### The artwork

The mark is the Young Globes **"Y."** — a white monogram on a full-bleed black
square. The original is kept at `dashboard-mods/brand/logo-source.avif` so the
assets can be regenerated; the derived files are:

| File | Size | Used by |
|---|---|---|
| `gauzy/apps/gauzy/src/assets/images/logos/logo_young_globes.png` | 128×128 | `PLATFORM_LOGO`, `NO_INTERNET_LOGO`, `APP_LOGO`, and the hardcoded fallbacks in `gauzy-logo.component.html` |
| `…/logo_young_globes_512x512.png` | 512×512 | `GAUZY_DESKTOP_LOGO_512X512` |
| `gauzy/apps/gauzy/src/favicon.ico` | 16/32/48/64 | browser tab |

Two things worth knowing about the source, since neither is fixable downstream:

- **It is 128×128.** That is ample for the header and the favicon, but the
  512×512 is a 4× upscale and will look soft next to a native-resolution icon.
  A larger original — or an SVG — would replace it cleanly; nothing but the
  files needs to change.
- **It has no transparency**, and the black is full-bleed to the corners. On the
  light theme it reads as a black tile, which is a normal look for a monogram
  mark; on the dark theme it blends into the background. If you would rather it
  adapt to the theme, supply a version with a transparent background — that is a
  design decision, so the mark was installed exactly as given.

The AVIF could not be converted by the usual means: Pillow 10.2 here has no AVIF
decoder and there is no `convert`, `ffmpeg` or `avifdec` on the box. It was
rendered through **headless Chrome** (`/opt/google/chrome/chrome --headless=new
--screenshot`), which is the same Chrome already used to drive Playwright checks.

The desktop, agent and server apps under `gauzy/apps/*/src/assets/icons/` still
carry Gauzy artwork. They are not built or deployed here — the screenshot agent
is the separately installed Gauzy Agent — so they were left alone.

Change #4 renders a page whose **data lives in `admin/settings_app.py`**, not in Gauzy —
Gauzy has no per-employee screenshot interval, no media-as-idle rule and no
per-department app productivity. The Angular page is a thin client over that
service, so adding a *setting* needs no Gauzy rebuild; only changing the *page*
does. The service verifies the caller's Gauzy token is a SUPER_ADMIN server-side;
the menu permission merely hides the link.

## Prerequisites (why this can't run on any machine)

- **~12 GB free RAM.** The Angular production build sets
  `--max-old-space-size=12288`. This box has 15 GB total but was showing ~4 GB
  free — **close other apps first** (Chrome, editors) or it will OOM/thrash.
- **~15 GB free disk** for `node_modules` + `dist`.
- **On mains power.** The build takes tens of minutes.
- **Node 24.17.0 — use the `.nvmrc` pin, not merely ">= 24".** `package.json`
  says `"engines": {"node": ">=24"}`, but that is not the binding constraint:
  a transitive dep (`@semantic-release/github`) demands
  `^22.14.0 || >= 24.10.0`, so Node 24.8.0 sits in the gap and fails just as
  hard as Node 22 does. Both failures read *"The engine node is incompatible"*.
  Match `.nvmrc` and the whole class of problem disappears. `yarn` is not installed globally and comes
  from `corepack`, whose shim is written into the **active Node version's** bin
  directory — so `corepack enable` must be re-run after switching Node, or
  `yarn` will be "command not found".

## Build + deploy

Run from `gauzy/` in this repo. Use `!` in the Claude prompt to run each
in-session, or a normal terminal.

```bash
cd ~/System-Tracker/gauzy

# 1. Select Node >= 24, THEN get yarn — corepack writes its shim into the
#    active version's bin dir, so this order matters.
source "$HOME/.nvm/nvm.sh" && nvm install 24.17.0 && nvm use 24.17.0
corepack enable && corepack prepare yarn@1.22.22 --activate

# 2. Install deps — large, one-time, ~10-20 min
yarn install

# 3. Production build of the web app — the heavy step (~12 GB RAM, tens of min)
NODE_OPTIONS=--max-old-space-size=12288 yarn build:gauzy:prod
#   output -> dist/apps/gauzy

# 4. Deploy: replace the served bundles in the running webapp container.
#    No image rebuild needed — nginx serves /srv/gauzy.
docker exec webapp sh -c 'rm -rf /srv/gauzy_old && cp -r /srv/gauzy /srv/gauzy_old'   # backup

# REPLACE the directory — do not copy over it. `docker cp` only overlays, so
# copying onto the live directory leaves every previous build's hashed chunks in
# place. A browser holding a cached index.html then loads the old runtime, which
# resolves to an old chunk that is still sitting there, and the dashboard shows
# the PREVIOUS build with no error at all — the deploy looks like it silently
# did nothing. Staging into a new directory and swapping avoids that entirely.
docker exec webapp sh -c 'rm -rf /srv/gauzy_new && mkdir -p /srv/gauzy_new'
docker cp dist/apps/gauzy/. webapp:/srv/gauzy_new/
docker exec webapp sh -c 'rm -rf /srv/gauzy && mv /srv/gauzy_new /srv/gauzy'

# 5. Hard-reload the browser (Ctrl+Shift+R). Done.
```

## Verify

- Header **start/stop timer widget is gone**.
- **"Worked today"** counts up every second.
- Data refreshes on its own within ~60s (no manual Refresh).

## Rollback

```bash
docker exec webapp sh -c 'rm -rf /srv/gauzy && mv /srv/gauzy_old /srv/gauzy'
# and to drop the source edits:
cd ~/System-Tracker/gauzy && git checkout -- \
  packages/ui-core/shared/src/lib/time-tracker/time-tracker/time-tracker.component.html \
  packages/plugins/dashboard-time-track-angular-ui/src/lib/components/time-tracking/time-tracking.component.ts \
  packages/plugins/dashboard-time-track-angular-ui/src/lib/components/time-tracking/time-tracking.component.html
```

## AGPL note

Ever Gauzy is AGPL-3.0. These are source modifications: if you expose this
modified Gauzy to users outside the company you must offer them the modified
source (AGPL §13) and rebrand off the "Ever"/"Gauzy" marks. Internal-only use is
fine. The changes are isolated to three component files and reverted cleanly by
`git checkout` above.
