# Packaging & install

Easy install of the tracker + silent-screenshot GNOME extension on other
machines.

## Linux / GNOME (Ubuntu) — one archive, one command

The tracker is stdlib-only Python, so there is nothing to compile. Build a
single distributable archive:

```bash
./packaging/build-bundle.sh 2026-08-06        # -> dist/system-tracker-2026-08-06.tar.gz
```

Copy that **one file** to another Ubuntu/GNOME machine and:

```bash
tar xzf system-tracker-2026-08-06.tar.gz
cd system-tracker
GAUZY_URL=http://your-server:3000 GAUZY_EMAIL=you@co GAUZY_PASSWORD=secret ./install.sh
```

`install.sh` (per-user, no root) sets up:
- the tracker in `~/.local/share/system-tracker/`
- the **silent-screenshot GNOME extension** (enabled; log out/in once if needed)
- a **systemd user service** that auto-starts at login and keeps running

Remove it any time with `./uninstall.sh`.

**Requirements on the target:** Ubuntu with GNOME, `python3` (3.8+), and
`python3-gi` (`sudo apt install python3-gi`) for screenshots. No `pip`, no build.

### A .deb instead?

The tracker installs fine system-wide, but the GNOME extension and the systemd
**user** service are inherently per-user, so a `.deb` still needs a per-user
enable step. The tarball + `install.sh` is simpler and does everything in one
go; that is the recommended path. If you specifically need a `.deb` for fleet
tooling, it can wrap the same `install.sh` in a `postinst` — ask and it can be
added.

## Windows

**This tracker does not run on Windows, by design** — it depends on Linux-only
facilities: `/proc` (process scan), X11/Wayland + Mutter (idle/focus), and
`xdg-desktop-portal` / `org.gnome.Screenshot` (capture). None exist on Windows.
Repackaging it as a Windows installer would mean writing a whole new Windows
backend (process list via the Win32 API, capture via GDI/`ImageGrab`, idle via
`GetLastInputInfo`).

**You almost certainly don't need to.** This custom tracker exists only because
Gauzy's own screenshot capture fails on **Linux/Wayland**. On **Windows the
official Ever Gauzy Desktop Agent works** — its Electron `desktopCapturer`
captures screenshots there normally. So on Windows machines:

1. Install the **Ever Gauzy Desktop Agent** (the official Windows build).
2. Log in with the employee account; enable **Allow Screen Capture** for the
   employee in the dashboard (same toggle this tracker honors on Linux).
3. Screenshots and activity flow into the same Gauzy instance.

Net result: **Linux boxes → this tracker; Windows boxes → the official Gauzy
Agent.** Both report into one Gauzy, so the dashboard is unified. If you truly
need a single custom cross-platform binary, that is a separate development
effort (a Windows capture backend + PyInstaller `.exe`) — scope it out
separately.
