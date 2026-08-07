#!/usr/bin/env python3
"""
System-Tracker — process + focus + browser-tab tracker for Ever Gauzy.

Per interval, for the logged-in employee, it captures:

  * PROCESSES (GUI + headless): every running app/backend from /proc — node,
    postgres, docker, nginx, dev tools (VS Code, Postman, terminals, editors).
  * FOREGROUND vs BACKGROUND: by sampling the focused window it measures how
    long each app was ON SCREEN (being watched) vs merely running in the
    background. Reported as the activity's "overall" seconds, so watched apps
    show high activity % and background-only apps ~0%.
  * BROWSER TABS: while a browser is focused, records the active tab (from the
    window title) as a URL activity, so Gauzy's "Visited Sites" is populated.
    No ActivityWatch, no browser extension — but this captures the ACTIVE tab's
    page TITLE only (not the full URL, and not background tabs). That is the
    hard ceiling for browser tracking without an extension or accessibility
    (AT-SPI) integration.

Pushes via POST /api/timesheet/time-slot (the desktop-agent API). Stdlib only.

Session backends, chosen automatically at runtime:

  X11      focused window via xprop (_NET_ACTIVE_WINDOW), idle time via the
           X server's XScreenSaver extension. Needs NO GNOME extension.
  Wayland  focused window via the 'Focused Window D-Bus' GNOME extension,
           idle time via GNOME Mutter's IdleMonitor.

The Wayland path is also the fallback if an X query returns nothing.
"""

import ctypes
import ctypes.util
import json
import os
import time
import re
import sys
import ssl
import subprocess
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

DEFAULT_CONFIG = {
    "server_url": "http://localhost:3000",
    "email": "admin@ever.co",
    "password": "admin",
    "interval_seconds": 60,
    # How often, inside each interval, to sample the focused window. Smaller =
    # more accurate watch time. 5s over a 60s interval = 12 samples.
    "focus_sample_seconds": 5,
    # wm_class substrings treated as browsers (their focused title => a tab).
    "browsers": ["chrome", "chromium", "firefox", "edge", "brave", "opera"],
    "watchlist": [
        "code", "postman", "antigravity", "sublime", "idea", "pycharm",
        "gnome-terminal", "konsole", "xterm", "kitty", "alacritty",
        "tilix", "terminator", "terminal",
        "^bash$", "^zsh$", "^fish$", "tmux", "screen$",
        "vim", "nvim", "nano", "emacs", "htop", "ssh",
        "node", "postgres", "docker", "dockerd", "containerd",
        "nginx", "python", "php", "redis", "mysql", "mariadb",
        "java", "ruby", "go$",
        "chrome", "firefox", "spotify",
    ],
    "exclude": [
        "sandbox", "crashpad", "crash.?handler", "-helper",
        "gpu.?process", "utility", "zygote", "broker",
    ],
    "cpu_min_percent": 1.0,
    "max_processes": 40,
    "verbose": True,

    # ----- Timer / continuous tracking ------------------------------------- #
    # Keep a tracking timer running for the tracker's lifetime, so posted slots
    # attach to a same-day TimeLog and actually appear in the dashboard's
    # activity/screenshot views. The official desktop agent does the same.
    "maintain_timer": True,
    "timer_source": "DESKTOP",
    # Continuous, non-stoppable tracking: re-assert the timer every interval, so
    # if it is stopped/paused from the dashboard it resumes within one interval;
    # and do NOT stop it when the tracker exits, so a service restart leaves
    # tracking running. Together these make tracking start at login and run
    # unbroken until the machine is shut down.
    "enforce_timer": True,
    "stop_timer_on_exit": False,

    # ----- Timestamps ------------------------------------------------------- #
    # Store UTC (the correct, standard choice) and let Gauzy convert for display.
    # To make the dashboard show the machine's wall-clock time, set the ORG
    # timezone to match the machine (Settings -> Organizations -> Edit ->
    # timezone, e.g. Asia/Kolkata) — do NOT fake local time into the timestamp,
    # which breaks once the org timezone differs from the machine. Set true only
    # if you deliberately want naive local timestamps regardless of the org tz.
    "use_local_time": False,

    # ----- Active vs idle time --------------------------------------------- #
    # The system counts as ACTIVE for a moment if EITHER the user gave input
    # recently (keyboard/mouse) OR audio/video is playing. If neither is true
    # for `idle_threshold_seconds`, that moment counts as IDLE.
    #
    #   active  = keyboard/mouse used within idle_threshold_seconds
    #             OR audio/video currently playing (when count_audio_as_active)
    #   idle    = none of the above
    #
    # Idle detection uses GNOME's Mutter IdleMonitor (works on Wayland & X11);
    # audio detection reads /proc/asound stream state (no external tools).
    "idle_threshold_seconds": 180,      # 3 min of no input & no audio => idle
    # Whether media alone is enough to count as active. TRUE (the default) means
    # background video/music keeps the machine active. Set FALSE — or override it
    # per employee — and media playing with no keyboard/mouse counts as IDLE,
    # which is what an admin wants for staff who leave Spotify or YouTube running
    # while away from the desk. Real input always wins either way; this decides
    # only whether *media on its own* is enough.
    "count_audio_as_active": True,

    # ----- Per-employee overrides ------------------------------------------- #
    # Settings the super admin sets PER EMPLOYEE rather than in this file.
    # Gauzy has no per-employee field for either of the settings below — its
    # screenshotFrequency is organisation-wide — so the values come from a
    # settings surface outside the employee record.
    #   "gauzy"  : read them from GAUZY ITSELF, out of the employee's own
    #              `employee_setting` record (Settings -> Tracker Settings in
    #              the dashboard writes them there). Default. No extra service
    #              to run, no extra port, and the settings live beside the
    #              employee they describe.
    #   "config" : no remote lookup at all; every value comes from this file.
    #   "url"    : legacy. GET `settings_url` for the same JSON. Retained for
    #              anyone pointing at their own service.
    "settings_source": "gauzy",
    "settings_url": "",
    "settings_refresh_seconds": 60,     # how fast an admin's change takes effect

    # ----- Screenshots ------------------------------------------------------ #
    # Off by default: capturing someone's screen is a policy decision, not a
    # default. When on, one screenshot per interval is taken and attached to
    # that interval's time slot.
    "capture_screenshots": False,
    "screenshot_timeout_seconds": 20,   # give up if capture does not answer
    # How often to capture, independent of the process-scan interval. 0 keeps
    # the old behaviour of one shot per interval. Overridable per employee, so
    # one user can be on 1 min and another on 5. Rounded UP to a whole number of
    # scan intervals — see the cadence note in main() for why it cannot be
    # faster than, or out of step with, the slot interval.
    "screenshot_interval_seconds": 0,
    # Where the screenshot on/off switch lives:
    #   "dashboard" : the employee's "Allow Screen Capture" toggle in Gauzy
    #                 (Employees -> employee -> Edit -> Settings) is the live
    #                 control. An admin turns capture on/off there, no config
    #                 edit or restart needed. `capture_screenshots` is then just
    #                 a master enable that must also be true.
    #   "config"    : ignore the dashboard flag; `capture_screenshots` alone
    #                 decides (old behaviour).
    "screenshot_gate": "dashboard",
    # How often to re-read the dashboard toggle, so a change there takes effect
    # within this many seconds.
    "screenshot_gate_refresh_seconds": 30,
    # How to capture (all Wayland-native, no Xorg). Two silent routes and one
    # that flashes:
    #   "auto"      : extension -> gnome -> portal. Prefers the durable silent
    #                 route, then the no-setup silent route, flashing only if
    #                 neither is available. Recommended default.
    #   "extension" : in-process GNOME Shell extension only — SILENT and most
    #                 durable; needs a one-time install + logout. Skips the shot
    #                 rather than flash if the extension is not loaded.
    #   "gnome"     : DeskTime-style — own org.gnome.Screenshot, call
    #                 Shell.Screenshot(flash=false). SILENT, no install/logout;
    #                 relies on GNOME's sender allowlist.
    #   "portal"    : xdg-desktop-portal only — needs nothing, but FLASHES.
    "screenshot_method": "auto",
}


def load_config(path):
    cfg = dict(DEFAULT_CONFIG)
    if path and os.path.exists(path):
        with open(path) as fh:
            cfg.update(json.load(fh))
    cfg["server_url"] = os.environ.get("GAUZY_URL", cfg["server_url"])
    cfg["email"] = os.environ.get("GAUZY_EMAIL", cfg["email"])
    cfg["password"] = os.environ.get("GAUZY_PASSWORD", cfg["password"])
    return cfg


def log(cfg, *args):
    if cfg.get("verbose"):
        print(f"[{datetime.now():%H:%M:%S}]", *args, flush=True)


# --------------------------------------------------------------------------- #
# Per-employee settings
#
# Some settings belong to the employee, not to the machine: how often to
# screenshot them, and whether background media counts as idle for them. Gauzy
# stores neither per employee, so they come from a settings surface of the
# organisation's choosing.
#
# Deliberately indifferent to WHICH surface that is. Point `settings_url` at a
# field added to a Gauzy fork, or at a small separate admin app, and the tracker
# behaves the same — the choice between those is a deployment decision, and
# hard-coding either one here would make it expensive to change later. Left at
# "config" the tracker never makes the call at all.
# --------------------------------------------------------------------------- #

_settings_cache = None      # (dict, monotonic_time)


def fetch_employee_settings(cfg, employee_id, client=None):
    """This employee's admin-set overrides, or {} when none are configured.

    With the default `settings_source` of "gauzy" the values come from the
    employee's own record in Gauzy, fetched through the client the tracker is
    already authenticated with. That is what removes the need for a second
    service: the dashboard writes the setting onto the employee, and the tracker
    reads it back from the same place, over the connection it already has.

    Cached for `settings_refresh_seconds` so an admin's change lands within that
    window with no restart — the same live-control pattern the screenshot toggle
    already uses. A failed fetch returns the LAST KNOWN values rather than {}:
    dropping back to the config defaults would silently re-enable screenshots or
    flip someone's idle rule the moment the settings service hiccuped, which is
    a worse failure than briefly stale settings."""
    global _settings_cache
    source = (cfg.get("settings_source") or "gauzy").lower()
    if source == "config":
        return {}
    ttl = max(1, int(cfg.get("settings_refresh_seconds", 60)))
    now = time.monotonic()
    if _settings_cache and (now - _settings_cache[1]) < ttl:
        return _settings_cache[0]

    if source == "gauzy":
        if client is None:
            return _settings_cache[0] if _settings_cache else {}
        data = client.employee_settings()
        if data is None:                      # request failed
            return _settings_cache[0] if _settings_cache else {}
        _settings_cache = (data, now)
        return data

    url = (cfg.get("settings_url") or "").strip()
    if not url:
        return {}
    sep = "&" if "?" in url else "?"
    try:
        req = urllib.request.Request(
            f"{url}{sep}employeeId={urllib.parse.quote(str(employee_id))}",
            headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except Exception:
        return _settings_cache[0] if _settings_cache else {}
    if not isinstance(data, dict):
        return _settings_cache[0] if _settings_cache else {}
    _settings_cache = (data, now)
    return data


def setting(cfg, overrides, key, default=None):
    """Resolve one setting: the per-employee override wins, then config.json,
    then `default`. A null in the override means "no opinion, use the config" —
    so an admin form can leave a field blank without it reading as False."""
    if isinstance(overrides, dict) and overrides.get(key) is not None:
        return overrides[key]
    return cfg.get(key, default)


def now_ts(cfg):
    """The timestamp the tracker records with. Default: the system's local
    wall-clock time (naive), so the dashboard matches the machine's clock. With
    use_local_time false, UTC instead. Returned naive either way — the value is
    sent as-is, so the dashboard shows exactly this time, no re-offsetting."""
    if cfg.get("use_local_time", True):
        return datetime.now()                        # local wall clock
    return datetime.now(timezone.utc).replace(tzinfo=None)


def tokens(s):
    return {t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if len(t) >= 4}


# --------------------------------------------------------------------------- #
# /proc scanner
# --------------------------------------------------------------------------- #

_CLK_TCK = os.sysconf("SC_CLK_TCK")


def _read(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except (OSError, IOError):
        return None


def _boot_time():
    """Epoch seconds at which the system booted (from /proc/stat btime)."""
    data = _read("/proc/stat")
    if data:
        for line in data.decode("utf-8", "replace").splitlines():
            if line.startswith("btime "):
                return int(line.split()[1])
    return 0


_BTIME = _boot_time()


def fmt_duration(seconds):
    """Human 'Xh Ym' / 'Ym Zs' string for a running time."""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def scan_proc():
    out = {}
    now = time.time()
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = entry
        cmdline_raw = _read(f"/proc/{pid}/cmdline")
        if not cmdline_raw:  # kernel thread
            continue
        stat = _read(f"/proc/{pid}/stat")
        if not stat:
            continue
        try:
            s = stat.decode("utf-8", "replace")
            rparen = s.rfind(")")
            comm = s[s.find("(") + 1:rparen]
            rest = s[rparen + 2:].split()
            utime = int(rest[11])
            stime = int(rest[12])
            starttime = int(rest[19])          # ticks since boot
        except (ValueError, IndexError):
            continue
        cmdline = cmdline_raw.replace(b"\x00", b" ").decode("utf-8", "replace").strip()
        name = comm
        if cmdline:
            base = os.path.basename(cmdline.split(" ")[0])
            if base and not base.startswith("["):
                name = base or comm
        uptime = max(0, now - (_BTIME + starttime / _CLK_TCK)) if _BTIME else 0
        out[pid] = {"name": name, "cpu_ticks": utime + stime, "uptime": uptime}
    return out


def compile_patterns(patterns):
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def match(name, compiled):
    return any(rx.search(name) for rx in compiled)


# --------------------------------------------------------------------------- #
# Focused window (GNOME D-Bus) — foreground time + active browser tab
# --------------------------------------------------------------------------- #

ON_X11 = bool(os.environ.get("DISPLAY")) and \
    os.environ.get("XDG_SESSION_TYPE", "").lower() != "wayland"


def _xprop(args):
    """Run xprop and return stdout, or None if it failed / isn't installed."""
    try:
        r = subprocess.run(["xprop"] + args, capture_output=True, text=True, timeout=4)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _unquote(line):
    """Pull the first "..."-quoted value out of an xprop output line."""
    m = re.search(r'"((?:[^"\\]|\\.)*)"', line or "")
    if not m:
        return None
    return m.group(1).replace('\\"', '"').replace("\\\\", "\\") or None


def _window_props(win_id):
    """(wm_class, title, pid, win_type) for one X window id."""
    out = _xprop(["-id", win_id, "-notype", "WM_CLASS", "_NET_WM_NAME",
                  "WM_NAME", "_NET_WM_PID", "_NET_WM_WINDOW_TYPE"])
    if not out:
        return (None, None, None, None)
    wm_class = title = pid = win_type = None
    for line in out.splitlines():
        if line.startswith("WM_CLASS"):
            # WM_CLASS = "instance", "Class" — the class is what we key on.
            vals = re.findall(r'"((?:[^"\\]|\\.)*)"', line)
            if vals:
                wm_class = vals[-1].lower() or None
        elif line.startswith("_NET_WM_NAME"):
            title = _unquote(line) or title
        elif line.startswith("WM_NAME") and title is None:
            title = _unquote(line)
        elif line.startswith("_NET_WM_PID"):
            m = re.search(r"=\s*(\d+)", line)
            if m:
                pid = m.group(1)
        elif line.startswith("_NET_WM_WINDOW_TYPE"):
            win_type = line.split("=", 1)[-1].strip()
    return (wm_class, title, pid, win_type)


def get_focused_x11():
    """Focused (wm_class, title, pid) straight from the X server — no GNOME
    extension required. _NET_ACTIVE_WINDOW on the root window gives the
    focused window id; its properties give the app, title and owning PID."""
    out = _xprop(["-root", "-notype", "_NET_ACTIVE_WINDOW"])
    if not out:
        return (None, None, None)
    m = re.search(r"(0x[0-9a-fA-F]+)", out)
    if not m or int(m.group(1), 16) == 0:
        return (None, None, None)
    wm_class, title, pid, _ = _window_props(m.group(1))
    return (wm_class, title, pid)


# Window types that are part of the desktop shell, not apps the user "uses".
_SKIP_WINDOW_TYPES = ("_NET_WM_WINDOW_TYPE_DESKTOP", "_NET_WM_WINDOW_TYPE_DOCK")


def list_windows():
    """Every open window on the X session: [{wm_class, title, pid}].

    This is the capability an Xorg session unlocks — Wayland forbids one app
    from seeing another app's windows, so there we only ever get the FOCUSED
    window. Here _NET_CLIENT_LIST enumerates them all, which means background
    windows (a second browser window, a minimised editor) are visible too,
    each with its own title. Returns [] on Wayland or if xprop is missing."""
    if not ON_X11:
        return []
    out = _xprop(["-root", "-notype", "_NET_CLIENT_LIST"])
    if not out:
        return []
    windows = []
    for win_id in re.findall(r"0x[0-9a-fA-F]+", out):
        wm_class, title, pid, win_type = _window_props(win_id)
        if not wm_class or (win_type and win_type in _SKIP_WINDOW_TYPES):
            continue
        windows.append({"wm_class": wm_class, "title": title, "pid": pid})
    return windows


def get_focused():
    """Return (wm_class, title, pid) of the focused window, or (None, None, None).

    On X11 this reads the X server directly (no extra software). Otherwise —
    and if the X query comes up empty — it falls back to the 'Focused Window
    D-Bus' GNOME extension, which is the only route that works on Wayland.

    Uses busctl's --json mode: the plain output escapes non-ASCII title bytes
    as octal (\\NNN), which is not valid JSON. --json=short returns the D-Bus
    string (itself a JSON document) as properly-escaped, UTF-8-safe data."""
    if ON_X11:
        wm, title, pid = get_focused_x11()
        if wm:
            return (wm, title, pid)
    try:
        r = subprocess.run(
            ["busctl", "--json=short", "--user", "call", "org.gnome.Shell",
             "/org/gnome/shell/extensions/FocusedWindow",
             "org.gnome.shell.extensions.FocusedWindow", "Get"],
            capture_output=True, text=True, timeout=4,
        )
        outer = json.loads(r.stdout)          # {"type":"s","data":["{...json...}"]}
        payload = outer.get("data")
        if isinstance(payload, list):
            payload = payload[0]
        data = json.loads(payload)            # the actual window object
        pid = data.get("pid")
        return ((data.get("wm_class") or "").lower() or None,
                data.get("title") or None,
                str(pid) if pid else None)
    except Exception:
        return (None, None, None)


def clean_tab_title(title, browsers):
    """Strip the trailing ' - Google Chrome' / ' — Mozilla Firefox' suffix so we
    keep just the page/tab name."""
    if not title:
        return None
    t = re.sub(r"\s*[-–—]\s*(Google Chrome|Chromium|Mozilla Firefox|Microsoft Edge"
               r"|Brave|Opera)\s*$", "", title).strip()
    return t or None


# --------------------------------------------------------------------------- #
# Activity signals — idle time (keyboard/mouse) and media playback
# --------------------------------------------------------------------------- #

class _XScreenSaverInfo(ctypes.Structure):
    _fields_ = [("window", ctypes.c_ulong), ("state", ctypes.c_int),
                ("kind", ctypes.c_int), ("til_or_since", ctypes.c_ulong),
                ("idle", ctypes.c_ulong), ("eventMask", ctypes.c_ulong)]


_xss_state = None      # (libX11, libXss, display, info) once initialised; False if N/A


def _xss_init():
    """Open the X display and the XScreenSaver extension once, lazily."""
    global _xss_state
    if _xss_state is not None:
        return _xss_state
    _xss_state = False
    if not ON_X11:
        return _xss_state
    try:
        x11 = ctypes.CDLL(ctypes.util.find_library("X11"))
        xss = ctypes.CDLL(ctypes.util.find_library("Xss"))
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XDefaultRootWindow.restype = ctypes.c_ulong
        x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(_XScreenSaverInfo)
        xss.XScreenSaverQueryInfo.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                              ctypes.POINTER(_XScreenSaverInfo)]
        display = x11.XOpenDisplay(None)
        if not display:
            return _xss_state
        info = xss.XScreenSaverAllocInfo()
        _xss_state = (x11, xss, display, info)
    except (OSError, AttributeError, TypeError):
        _xss_state = False
    return _xss_state


def get_idle_seconds_x11():
    """Seconds since last input from the X server's XScreenSaver extension.
    Needs no GNOME session and no external binary. None if unavailable."""
    state = _xss_init()
    if not state:
        return None
    x11, xss, display, info = state
    try:
        if not xss.XScreenSaverQueryInfo(display, x11.XDefaultRootWindow(display), info):
            return None
        return info.contents.idle / 1000.0
    except Exception:
        return None


def get_idle_seconds():
    """Seconds since the last keyboard/mouse input. Prefers the X server's own
    XScreenSaver counter on X11, falling back to GNOME Mutter's IdleMonitor
    (the only option on Wayland). None if neither is available."""
    if ON_X11:
        idle = get_idle_seconds_x11()
        if idle is not None:
            return idle
    try:
        r = subprocess.run(
            ["busctl", "--user", "call",
             "org.gnome.Mutter.IdleMonitor", "/org/gnome/Mutter/IdleMonitor/Core",
             "org.gnome.Mutter.IdleMonitor", "GetIdletime"],
            capture_output=True, text=True, timeout=4)
        parts = r.stdout.split()          # output: "t <milliseconds>"
        if len(parts) >= 2 and parts[0] == "t":
            return int(parts[1]) / 1000.0
    except Exception:
        pass
    return None


def is_audio_playing():
    """True if any sound-card stream is actively RUNNING (audio/video playing).
    Reads the kernel's /proc/asound status files — no external tools needed."""
    import glob
    for status in glob.glob("/proc/asound/card*/pcm*/sub*/status"):
        try:
            with open(status) as fh:
                if "RUNNING" in fh.readline():
                    return True
        except OSError:
            continue
    return False


def is_active_now(cfg, overrides=None):
    """Decide if this instant is active: recent input OR audio playing.

    `count_audio_as_active` is resolved per employee, so the same build can
    treat background media as active for one user and as IDLE for another. When
    it is off, media playing with nobody at the keyboard counts as idle — the
    Spotify-left-running case. Real input still wins regardless.

    `media_playing` is reported separately from `audio` on purpose: `audio` is
    "media counted towards active", which goes into the posted payload, while
    `media_playing` is the raw fact. With media-as-idle enabled the two diverge,
    and the log needs the raw fact to explain WHY an interval reads idle while
    music is audible."""
    idle = get_idle_seconds()
    recent_input = (idle is not None) and (idle < cfg["idle_threshold_seconds"])
    playing = is_audio_playing()
    audio = bool(setting(cfg, overrides, "count_audio_as_active", True)) and playing
    return recent_input or audio, {"idle_s": idle, "audio": audio,
                                   "media_playing": playing,
                                   "recent_input": recent_input}


# --------------------------------------------------------------------------- #
# Screenshots — silent capture on Wayland (no Xorg anywhere)
#
# X11 capture is dead on this Wayland session (XGetImage on XWayland's
# unredirected root -> BadMatch), so all routes are Wayland-native GNOME:
#
#   gnome     : own the allowlisted org.gnome.Screenshot bus name, then call
#               Shell.Screenshot(cursor=false, FLASH=false, path). This is
#               exactly what DeskTime does on Wayland+GNOME. SILENT, and needs
#               no install and no logout — but leans on GNOME's sender
#               allowlist, which GNOME may tighten in a future release.
#   extension : the in-process Shell extension calls Shell.Screenshot directly,
#               not subject to the allowlist. SILENT and the most durable, but
#               needs a one-time install + logout to load.
#   portal    : xdg-desktop-portal. Works with nothing installed, but GNOME's
#               portal always FLASHES the screen. Not silent — last resort.
#
# 'auto' prefers the durable extension, then falls back to the DeskTime-style
# gnome trick (so capture is silent and immediate before the extension is
# installed), and never silently falls back to the flashing portal.
# --------------------------------------------------------------------------- #

_portal_state = None      # (Gio, GLib, bus) once initialised; False if N/A
_portal_seq = 0           # unique handle_token per request
_gnome_name_owned = None  # bus-name owner id once org.gnome.Screenshot is held


def _portal_init():
    """Open the session bus once, lazily. False if python3-gi is unavailable.

    python3-gi is a system package (preinstalled on Ubuntu GNOME), not a pip
    dependency — it is the one non-stdlib import in this file, and it is
    imported here rather than at module scope so the tracker still runs, minus
    screenshots, on a box without it."""
    global _portal_state
    if _portal_state is not None:
        return _portal_state
    _portal_state = False
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except Exception:
        return _portal_state
    _portal_state = (Gio, GLib, bus)
    return _portal_state


_GNOME_NAME = "org.gnome.Screenshot"


def _own_gnome_name():
    """Acquire the org.gnome.Screenshot bus name and hold it for the process
    lifetime. GNOME Shell's Screenshot service only accepts callers that own a
    name on its allowlist, and org.gnome.Screenshot is on it — this is the same
    identity DeskTime's bundled gnome-screenshot fork registers under. Returns
    True if the name is (being) held. Best-effort and idempotent."""
    global _gnome_name_owned
    if _gnome_name_owned is not None:
        return True
    state = _portal_init()
    if not state:
        return False
    Gio, GLib, bus = state
    try:
        # NONE (not REPLACE): if gnome-screenshot/DeskTime already own the name,
        # we do not fight them — capture just falls back to another route.
        _gnome_name_owned = Gio.bus_own_name_on_connection(
            bus, _GNOME_NAME, Gio.BusNameOwnerFlags.NONE, None, None)
        return True
    except Exception:
        _gnome_name_owned = None
        return False


def _capture_via_gnome(cfg):
    """PNG bytes via the DeskTime-style route — SILENT. Owns the allowlisted
    org.gnome.Screenshot name, then calls Shell.Screenshot with flash=false so
    there is no flash, no shutter sound, and no notification. None if the call
    is refused (e.g. a future GNOME drops the name from its allowlist) or the
    capture fails."""
    if not _own_gnome_name():
        return None
    global _portal_seq
    Gio, GLib, bus = _portal_state
    _portal_seq += 1
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    path = os.path.join(runtime, f"st-gshot-{os.getpid()}-{_portal_seq}.png")
    timeout_ms = max(1, int(cfg.get("screenshot_timeout_seconds", 20))) * 1000
    try:
        reply = bus.call_sync(
            "org.gnome.Shell.Screenshot", "/org/gnome/Shell/Screenshot",
            "org.gnome.Shell.Screenshot", "Screenshot",
            GLib.Variant("(bbs)", (False, False, path)),  # include_cursor, FLASH, file
            GLib.VariantType("(bs)"), Gio.DBusCallFlags.NONE, timeout_ms, None)
        ok = reply.unpack()[0]
    except Exception:
        return None
    data = None
    if ok:
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            data = None
    try:
        os.unlink(path)
    except OSError:
        pass
    return data or None


def gnome_capture_available():
    """True if the DeskTime-style route can actually capture — verified by a
    real (silent) test shot, since owning the name does not guarantee the Shell
    still honours it. The probe image is discarded."""
    return _capture_via_gnome({"screenshot_timeout_seconds": 5}) is not None


_EXT_OBJECT = "/org/gnome/Shell/Extensions/SystemTrackerShot"
_EXT_IFACE = "org.gnome.Shell.Extensions.SystemTrackerShot"


def extension_available():
    """True if the System-Tracker Shell extension is loaded and answering.

    Introspecting its object path is cheap and, unlike calling CaptureToFile,
    does not take a screenshot just to probe."""
    state = _portal_init()
    if not state:
        return False
    Gio, GLib, bus = state
    try:
        # gnome-shell answers Introspect for ANY path under org.gnome.Shell
        # with an empty node, so success alone is not proof — the XML must
        # actually declare our interface for the object to really be exported.
        reply = bus.call_sync("org.gnome.Shell", _EXT_OBJECT,
                              "org.freedesktop.DBus.Introspectable", "Introspect",
                              None, GLib.VariantType("(s)"),
                              Gio.DBusCallFlags.NONE, 3000, None)
        return _EXT_IFACE in reply.unpack()[0]
    except Exception:
        return False


def _capture_via_extension(cfg):
    """PNG bytes via the in-process GNOME Shell extension — fully SILENT.

    The extension calls Shell.Screenshot inside the shell, so there is no
    flash, no shutter sound, and no notification. We hand it a path to write,
    then read and delete that file. None if the extension is not loaded or the
    capture fails."""
    global _portal_seq
    state = _portal_init()
    if not state:
        return None
    Gio, GLib, bus = state
    _portal_seq += 1
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    path = os.path.join(runtime, f"st-shot-{os.getpid()}-{_portal_seq}.png")
    timeout_ms = max(1, int(cfg.get("screenshot_timeout_seconds", 20))) * 1000
    try:
        reply = bus.call_sync("org.gnome.Shell", _EXT_OBJECT, _EXT_IFACE,
                              "CaptureToFile", GLib.Variant("(s)", (path,)),
                              GLib.VariantType("(b)"), Gio.DBusCallFlags.NONE,
                              timeout_ms, None)
        ok = reply.unpack()[0]
    except Exception:
        return None
    data = None
    if ok:
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            data = None
    try:
        os.unlink(path)
    except OSError:
        pass
    return data or None


def capture_screenshot(cfg):
    """PNG bytes of the whole screen, or None if capture is unavailable.

    Route is chosen by `screenshot_method` (see the section banner above):
      * extension — in-process Shell extension. Silent, most durable.
      * gnome     — DeskTime-style org.gnome.Screenshot trick. Silent, no setup.
      * portal    — xdg-desktop-portal. Works everywhere but FLASHES.
      * auto      — extension -> gnome -> portal, preferring the durable silent
                    route, then the no-setup silent route, and only flashing if
                    neither is available.

    A fixed method uses that route only; the two silent methods never fall back
    to the flashing portal, so 'silent' stays a guarantee, not a preference."""
    method = (cfg.get("screenshot_method") or "auto").lower()

    if method == "portal":
        return _capture_via_portal(cfg)
    if method == "extension":
        return _capture_via_extension(cfg)          # silent or nothing
    if method == "gnome":
        return _capture_via_gnome(cfg)              # silent or nothing

    # auto: prefer the durable silent route, then the no-setup silent route,
    # and only then the flashing portal.
    data = _capture_via_extension(cfg)
    if data is not None:
        return data
    data = _capture_via_gnome(cfg)
    if data is not None:
        return data
    return _capture_via_portal(cfg)


def _capture_via_portal(cfg):
    """PNG bytes via xdg-desktop-portal's Screenshot interface. NOT silent on
    GNOME — the portal flashes the screen. `interactive: false` is answered
    without a consent dialog on GNOME 46; the portal picks its own output path,
    which we read and then delete so nothing accumulates in ~/Pictures."""
    global _portal_seq
    state = _portal_init()
    if not state:
        return None
    Gio, GLib, bus = state
    _portal_seq += 1
    token = f"system_tracker_{os.getpid()}_{_portal_seq}"
    sender = bus.get_unique_name()[1:].replace(".", "_")
    handle = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"

    loop = GLib.MainLoop()
    result = {}
    subs = []
    timer = None

    def on_response(_conn, _sender, _path, _iface, _signal, params):
        code, res = params.unpack()
        result["code"] = code
        result["uri"] = res.get("uri")
        loop.quit()

    def subscribe(path):
        subs.append(bus.signal_subscribe(
            "org.freedesktop.portal.Desktop", "org.freedesktop.portal.Request",
            "Response", path, None, Gio.DBusSignalFlags.NONE, on_response))

    # Subscribe BEFORE calling: the portal may answer before the call returns.
    subscribe(handle)
    try:
        opts = GLib.Variant("a{sv}", {
            "handle_token": GLib.Variant("s", token),
            "interactive": GLib.Variant("b", False),
        })
        reply = bus.call_sync(
            "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Screenshot", "Screenshot",
            GLib.Variant.new_tuple(GLib.Variant.new_string(""), opts), None,
            Gio.DBusCallFlags.NONE, 10000, None)
        actual = reply.unpack()[0]
        if actual != handle:        # older portals hand back a different path
            subscribe(actual)
        timer = GLib.timeout_add_seconds(
            max(1, int(cfg.get("screenshot_timeout_seconds", 20))),
            lambda: (result.setdefault("code", -1), loop.quit())[1])
        loop.run()
    except Exception:
        return None
    finally:
        # The timer outlives the loop when the response arrives first. Left
        # registered, it would fire inside the NEXT capture's main loop and
        # quit it before the portal answers, so every second shot would fail.
        if timer is not None:
            try:
                GLib.source_remove(timer)   # already gone if it was the timer that fired
            except Exception:
                pass
        for sub in subs:
            bus.signal_unsubscribe(sub)

    if result.get("code") != 0 or not result.get("uri"):
        return None
    path = _uri_to_path(result["uri"])
    if not path:
        return None
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    try:
        os.unlink(path)
    except OSError:
        pass                        # not ours to insist on; the bytes are what matter
    return data or None


def _uri_to_path(uri):
    """'file:///home/x/Screenshot.png' -> '/home/x/Screenshot.png'."""
    if not uri or not uri.startswith("file://"):
        return None
    return urllib.parse.unquote(uri[len("file://"):])


def _multipart_body(fields, file_field, filename, mimetype, content):
    """Encode a multipart/form-data body by hand — returns (bytes, content_type).

    Stdlib has no multipart encoder, and this is the only place we need one."""
    boundary = "----SystemTracker" + os.urandom(12).hex()
    parts = []
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'
            f"{value}\r\n".encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
        f'filename="{filename}"\r\nContent-Type: {mimetype}\r\n\r\n'.encode())
    parts.append(content)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


# --------------------------------------------------------------------------- #
# Build the per-interval report
# --------------------------------------------------------------------------- #

def build_process_rows(prev, curr, interval, cfg, compiled, excluded, fg_seconds,
                       fg_by_pid=None, windows=None):
    """[{name, cpu_percent, foreground_seconds, window_titles}] for reportable
    processes.

    fg_seconds: focused-wm_class -> seconds on screen this interval.
    fg_by_pid:  focused-PID -> seconds on screen. Preferred when available
                (X11 gives the focused window's PID), because matching the
                owning process by PID is exact, where wm_class-to-process-name
                matching is only a guess.
    windows:    every open window (X11 only) -> attached per app, so a row can
                show the titles of windows that were never focused."""
    fg_by_pid = fg_by_pid or {}
    windows = windows or []
    agg = {}       # name -> cpu_ticks delta
    uptime = {}    # name -> longest-running instance's uptime (seconds)
    for pid, info in curr.items():
        name = info["name"]
        prev_ticks = prev.get(pid, {}).get("cpu_ticks", info["cpu_ticks"])
        agg.setdefault(name, 0)
        agg[name] += max(0, info["cpu_ticks"] - prev_ticks)
        uptime[name] = max(uptime.get(name, 0), info.get("uptime", 0))

    # Resolve focused PIDs to process names — exact, no token guessing.
    fg_by_name = {}
    for pid, secs in fg_by_pid.items():
        info = curr.get(pid) or prev.get(pid)
        if info:
            fg_by_name[info["name"]] = fg_by_name.get(info["name"], 0) + secs

    rows = []
    for name, ticks in agg.items():
        if excluded and match(name, excluded):
            continue
        cpu = (ticks / _CLK_TCK) / interval * 100.0
        if compiled:
            if not match(name, compiled):
                continue
        elif cpu < cfg["cpu_min_percent"]:
            continue
        name_tokens = tokens(name)
        if name in fg_by_name:
            fg = fg_by_name[name]
        else:
            fg = sum(secs for wm, secs in fg_seconds.items() if name_tokens & tokens(wm))
        titles = []
        for w in windows:
            owner = curr.get(w["pid"], {}).get("name") if w["pid"] else None
            hit = (owner == name) if owner else bool(name_tokens & tokens(w["wm_class"]))
            if hit and w["title"] and w["title"] not in titles:
                titles.append(w["title"])
        rows.append({"name": name, "cpu_percent": round(cpu, 1),
                     "foreground_seconds": min(interval, fg),
                     "running_seconds": int(uptime.get(name, 0)),
                     "window_titles": titles})
    rows.sort(key=lambda r: (r["foreground_seconds"], len(r["window_titles"]),
                             r["cpu_percent"]), reverse=True)
    return rows[: cfg["max_processes"]]


# --------------------------------------------------------------------------- #
# Gauzy API client
# --------------------------------------------------------------------------- #

class GauzyClient:
    def __init__(self, cfg):
        self.base = cfg["server_url"].rstrip("/")
        self.cfg = cfg
        self.token = None
        self.employee_id = self.organization_id = self.tenant_id = None
        self.time_log_id = None
        self._ctx = ssl.create_default_context()

    def _request(self, method, path, body=None, auth=True, raw=None, content_type=None):
        """raw/content_type bypass the JSON encoding — used for file uploads."""
        url = f"{self.base}{path}"
        if raw is not None:
            data = raw
        else:
            data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", content_type or "application/json")
        req.add_header("Accept", "application/json")
        if auth and self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
            if self.tenant_id:
                req.add_header("Tenant-Id", self.tenant_id)
        try:
            with urllib.request.urlopen(req, timeout=30, context=self._ctx) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, {"message": raw.decode("utf-8", "replace")[:200]}
        except urllib.error.URLError as e:
            return 0, {"message": str(e)}

    def login(self):
        status, data = self._request(
            "POST", "/api/auth/login",
            {"email": self.cfg["email"], "password": self.cfg["password"]}, auth=False)
        if status != 200 or not data.get("token"):
            raise RuntimeError(f"login failed (HTTP {status}): {data.get('message', data)}")
        self.token = data["token"]
        emp = (data.get("user", {}).get("employee") or {})
        self.employee_id = emp.get("id")
        self.organization_id = emp.get("organizationId")
        self.tenant_id = emp.get("tenantId") or data.get("user", {}).get("tenantId")
        if not (self.employee_id and self.organization_id and self.tenant_id):
            raise RuntimeError("account has no employee/org/tenant; use an Employee account")

    _shot_flag_cache = None      # (value, monotonic_time) for the dashboard toggle

    def screenshots_enabled(self):
        """Whether screenshots are turned on for this employee IN THE DASHBOARD
        — the `allowScreenshotCapture` flag that Employees -> employee -> Edit ->
        Settings -> 'Allow Screen Capture' writes. This is the live on/off
        switch: an admin flips it in Gauzy and the tracker obeys, no restart.

        Cached for `screenshot_gate_refresh_seconds` so we do not GET the
        employee every capture. On a read failure we keep the last known value
        (fail-safe to whatever it was), or default to False if never read."""
        ttl = max(1, int(self.cfg.get("screenshot_gate_refresh_seconds", 30)))
        now = time.monotonic()
        cache = GauzyClient._shot_flag_cache
        if cache and (now - cache[1]) < ttl:
            return cache[0]
        status, data = self._request("GET", f"/api/employee/{self.employee_id}")
        if status in (200, 201) and isinstance(data, dict) and "allowScreenshotCapture" in data:
            val = bool(data["allowScreenshotCapture"])
            GauzyClient._shot_flag_cache = (val, now)
            return val
        # Could not read — keep the last known value rather than flapping.
        return cache[0] if cache else False

    def employee_settings(self):
        """This employee's System-Tracker overrides, stored on their own Gauzy
        record. Returns a dict, or None if the request failed (so the caller can
        keep the last known values rather than reverting to defaults).

        Stored in Gauzy's generic `employee_setting` table — a per-employee row
        with a jsonb `data` column — which is why no separate settings service
        is needed. Settings -> Tracker Settings in the dashboard writes here.

        The query MUST carry all three of employeeId, tenantId and
        organizationId. Gauzy rejects a bare list with "where should not be
        empty", and an employeeId alone with "where.organization must be an
        object"; only the fully scoped form returns rows."""
        path = (f"/api/employee-settings?where[employeeId]={self.employee_id}"
                f"&where[tenantId]={self.tenant_id}"
                f"&where[organizationId]={self.organization_id}")
        status, data = self._request("GET", path)
        if status not in (200, 201):
            return None
        items = data if isinstance(data, list) else (
            data.get("items", []) if isinstance(data, dict) else [])
        # Newest wins: the dashboard writes a fresh row rather than mutating the
        # old one, so an employee accumulates history and only the last entry
        # reflects what the admin currently intends.
        out = {}
        for it in items:
            if isinstance(it, dict) and isinstance(it.get("data"), dict):
                out = it["data"]
        return out

    def start_timer(self):
        """Start a tracking timer, creating a running TimeLog the posted slots
        attach to. Without this, slots exist but the dashboard's activity and
        screenshot views — which are scoped to a same-day TimeLog — never show
        them. This is what the official desktop agent does at timer start.

        Idempotent-ish: if a timer is already running for this employee, Gauzy
        returns the existing running log rather than erroring."""
        status, data = self._request("POST", "/api/timesheet/timer/start", {
            "organizationId": self.organization_id, "tenantId": self.tenant_id,
            "source": self.cfg.get("timer_source", "DESKTOP"),
            "logType": "TRACKED", "isBillable": True})
        if status in (200, 201) and isinstance(data, dict):
            self.time_log_id = data.get("id")
            return True
        # Already running (or transient) — fall back to the current status.
        s2, d2 = self._request("GET", "/api/timesheet/timer/status")
        if s2 in (200, 201) and isinstance(d2, dict):
            self.time_log_id = (d2.get("lastLog") or {}).get("id") or d2.get("id")
            return bool(self.time_log_id)
        return False

    def stop_timer(self):
        """Stop the tracking timer (best effort — never raises)."""
        try:
            self._request("POST", "/api/timesheet/timer/stop", {
                "organizationId": self.organization_id, "tenantId": self.tenant_id,
                "source": self.cfg.get("timer_source", "DESKTOP"),
                "logType": "TRACKED"})
        except Exception:
            pass

    def timer_running(self):
        """True if a timer is currently running for this employee, per the
        server. None if the status could not be read."""
        src = self.cfg.get("timer_source", "DESKTOP")
        path = (f"/api/timesheet/timer/status?source={src}"
                f"&organizationId={self.organization_id}"
                f"&tenantId={self.tenant_id}")
        status, data = self._request("GET", path)
        if status in (200, 201) and isinstance(data, dict):
            return bool(data.get("running"))
        return None

    def ensure_timer(self):
        """Guarantee a timer is running — restart it if it was stopped or paused
        (e.g. from the dashboard). This is what makes tracking non-stoppable:
        any stop is undone on the next interval. Returns True if running.

        Only acts when the status says NOT running, so a healthy timer is left
        untouched and no duplicate logs are created."""
        running = self.timer_running()
        if running:
            return True
        # running is False (stopped from the dashboard) or None (status
        # unreadable) — (re)start to be safe. start_timer reuses an existing
        # running log if there is one, so this cannot double-start.
        return self.start_timer()

    def post_time_slot(self, proc_rows, tabs, started_at, duration,
                        active_seconds, audio_seconds):
        """tabs: {title -> seconds_watched}. active_seconds: how long this slot
        was active (input or audio); audio_seconds: how long audio played."""
        date = started_at.strftime("%Y-%m-%d")
        tm = started_at.strftime("%H:%M:%S")
        recorded = started_at.isoformat()
        base = {"projectId": None, "date": date, "time": tm, "recordedAt": recorded,
                "organizationId": self.organization_id, "employeeId": self.employee_id}
        acts = []
        for r in proc_rows:
            running = r.get("running_seconds", 0)
            titles = r.get("window_titles") or []
            desc = f"Running for {fmt_duration(running)}"
            if titles:
                desc += " — " + "; ".join(titles[:3])
            acts.append({**base, "title": r["name"], "duration": duration, "type": "APP",
                         "description": desc,
                         "metaData": [{"source": "system-tracker",
                                       "cpuPercent": r["cpu_percent"],
                                       "foregroundSeconds": r["foreground_seconds"],
                                       "runningSeconds": running,
                                       # Open windows and their titles — X11 only.
                                       "windowCount": len(titles),
                                       "windowTitles": titles,
                                       "mode": "foreground" if r["foreground_seconds"] > 0 else "background"}]})
        for title, secs in tabs.items():
            acts.append({**base, "title": title, "duration": max(1, int(secs)), "type": "URL",
                         "metaData": [{"source": "system-tracker", "watchedSeconds": secs}]})
        # "overall" (active seconds) drives Gauzy's activity %: active time /
        # slot duration. Active = keyboard/mouse used OR audio/video playing.
        overall = max(0, min(duration, int(active_seconds)))
        payload = {
            "tenantId": self.tenant_id, "organizationId": self.organization_id,
            "employeeId": self.employee_id, "duration": duration,
            # keyboard/mouse are shown as "1" when there was real input activity
            # this slot, else 0 — so the dashboard distinguishes active vs idle.
            "keyboard": 1 if active_seconds > audio_seconds else 0,
            "mouse": 1 if active_seconds > audio_seconds else 0,
            "overall": overall,
            "startedAt": recorded, "recordedAt": recorded, "activities": acts,
        }
        return self._request("POST", "/api/timesheet/time-slot", payload)

    def post_screenshot(self, png, recorded_at, time_slot_id=None):
        """Upload one screenshot and attach it to a time slot.

        The file field MUST be named `file` — the server's upload interceptor
        looks for exactly that and silently returns nothing otherwise. The
        server derives userId from the token and builds the thumbnail itself.

        `timeSlotId` is what binds the image to a slot; the column is nullable,
        so without it the upload still succeeds but the screenshot sits
        unattached and does not appear against the slot in
        Employees -> Activity -> Screenshots."""
        fields = {
            "organizationId": self.organization_id,
            "tenantId": self.tenant_id,
            "recordedAt": recorded_at.isoformat(),
            "timeSlotId": time_slot_id,
        }
        body, content_type = _multipart_body(fields, "file", "screenshot.png",
                                             "image/png", png)
        return self._request("POST", "/api/timesheet/screenshot",
                             raw=body, content_type=content_type)


# --------------------------------------------------------------------------- #
# Main loop
# --------------------------------------------------------------------------- #

def _log_screenshot_mode(cfg, client=None):
    """One startup line stating exactly how screenshots will be taken, so
    'silent vs flashing' is never a surprise at runtime."""
    if not _portal_init():
        log(cfg, "screenshots: requested but unavailable (install python3-gi)")
        return
    if cfg.get("screenshot_gate", "dashboard").lower() == "dashboard" and client:
        on = client.screenshots_enabled()
        log(cfg, f"screenshots: controlled by the dashboard toggle "
                 f"(Allow Screen Capture) — currently {'ON' if on else 'OFF'}")
    method = (cfg.get("screenshot_method") or "auto").lower()

    if method == "portal":
        log(cfg, "screenshots: ON via portal — WARNING: the screen will FLASH")
        return
    if method == "extension":
        log(cfg, "screenshots: ON via Shell extension — silent"
                 if extension_available() else
                 "screenshots: method=extension but the extension is NOT loaded; "
                 "no shots will be taken (see tracker/gnome-extension/README.md)")
        return
    if method == "gnome":
        log(cfg, "screenshots: ON via org.gnome.Screenshot (DeskTime-style) — silent"
                 if gnome_capture_available() else
                 "screenshots: method=gnome but org.gnome.Screenshot capture was "
                 "refused; no shots will be taken")
        return

    # auto: report whichever silent route will actually serve, else the flash.
    if extension_available():
        log(cfg, "screenshots: ON via Shell extension — silent (auto)")
    elif gnome_capture_available():
        log(cfg, "screenshots: ON via org.gnome.Screenshot (DeskTime-style) — "
                 "silent (auto; install the extension for the more durable route)")
    else:
        log(cfg, "screenshots: no silent route available, falling back to portal "
                 "— WARNING: the screen will FLASH")


def _upload_screenshot(client, cfg, png, started, slot_resp):
    """Attach this interval's screenshot to the slot just created, and return a
    short note for the log line.

    Never raises: a screenshot that fails to capture or upload must not take
    process tracking down with it."""
    if not png:
        return " | no shot"
    slot_id = slot_resp.get("id") if isinstance(slot_resp, dict) else None
    try:
        status, resp = client.post_screenshot(png, started, slot_id)
    except Exception as exc:
        return f" | shot error: {str(exc)[:40]}"
    if status in (200, 201):
        return f" | shot {len(png) // 1024}KB" + ("" if slot_id else " (unattached)")
    return f" | shot HTTP {status}: {str(resp)[:60]}"


def main():
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config.json")
    cfg = load_config(cfg_path)
    compiled = compile_patterns(cfg["watchlist"])
    excluded = compile_patterns(cfg.get("exclude", []))
    interval = cfg["interval_seconds"]
    fsample = max(1, int(cfg.get("focus_sample_seconds", 5)))
    browsers = [b.lower() for b in cfg.get("browsers", [])]

    client = GauzyClient(cfg)
    log(cfg, f"Login {cfg['server_url']} as {cfg['email']} ...")
    client.login()
    log(cfg, f"OK. employee={client.employee_id[:8]} | interval {interval}s, "
             f"focus sample {fsample}s")
    # State the per-employee settings in force, so the log says what this
    # employee is actually configured for rather than what the file says.
    _boot = fetch_employee_settings(cfg, client.employee_id, client)
    if (cfg.get("settings_source") or "config").lower() == "url":
        log(cfg, f"per-employee settings: {cfg.get('settings_url')} "
                 f"({len(_boot)} override(s) in force)"
            if _boot else
            f"per-employee settings: {cfg.get('settings_url')} "
            f"— unreachable or empty, using config.json values")
    if not setting(cfg, _boot, "count_audio_as_active", True):
        log(cfg, "idle rule: background media alone counts as IDLE for this employee")
    if cfg.get("capture_screenshots"):
        _log_screenshot_mode(cfg, client)
        _every = int(setting(cfg, _boot, "screenshot_interval_seconds", 0) or 0)
        if _every > interval:
            log(cfg, f"screenshots: every {max(1, int(round(float(_every) / interval))) * interval}s "
                     f"(requested {_every}s, snapped to the {interval}s slot grid)")

    # Start a timer so posted slots attach to a running TimeLog — otherwise the
    # dashboard's activity/screenshot views (scoped to a same-day TimeLog) show
    # nothing, even though the slots and screenshots are stored correctly.
    if cfg.get("maintain_timer", True):
        log(cfg, "timer started, TimeLog=" + str(client.time_log_id)[:8]
                 if client.start_timer() else
                 "WARNING: could not start timer — dashboard may not show activity")

    prev = scan_proc()
    cycle = 0            # counts intervals, so screenshot cadence can be every Nth
    try:
        while True:
            started = now_ts(cfg)
            cycle += 1
            # Re-assert the timer so tracking cannot be paused/stopped from the
            # dashboard: if it was stopped, this restarts it before we post.
            if cfg.get("maintain_timer", True) and cfg.get("enforce_timer", True):
                if not client.ensure_timer():
                    log(cfg, "note: timer not running and could not be restarted")
            # This employee's admin-set overrides, re-resolved each cycle (the
            # fetch itself is cached) so a change in the dashboard takes effect
            # without a restart.
            overrides = fetch_employee_settings(cfg, client.employee_id, client)
            fg_seconds = {}       # wm_class -> seconds focused
            fg_by_pid = {}        # focused PID -> seconds focused (exact match)
            tabs = {}             # active browser tab title -> seconds watched
            active_seconds = 0    # seconds this slot was active (input or audio)
            audio_seconds = 0     # seconds audio counted TOWARDS active
            media_seconds = 0     # seconds media played, counted active or not
            deadline = time.monotonic() + interval
            while time.monotonic() < deadline:
                time.sleep(fsample)
                # activity sample: active if recent input OR audio playing
                active, sig = is_active_now(cfg, overrides)
                if active:
                    active_seconds += fsample
                if sig["audio"]:
                    audio_seconds += fsample
                if sig["media_playing"]:
                    media_seconds += fsample
                # focus / browser-tab sample
                wm, title, fpid = get_focused()
                if not wm:
                    continue
                fg_seconds[wm] = fg_seconds.get(wm, 0) + fsample
                if fpid:
                    fg_by_pid[fpid] = fg_by_pid.get(fpid, 0) + fsample
                if any(b in wm for b in browsers):
                    tab = clean_tab_title(title, browsers)
                    if tab:
                        tabs[tab] = tabs.get(tab, 0) + fsample
            # Capture at the close of the slot window, so the image belongs to
            # the interval we are about to post; it is uploaded afterwards,
            # once the slot POST has handed back the id to attach it to.
            # Gate: master switch AND (when gate=dashboard) the employee's live
            # "Allow Screen Capture" toggle in Gauzy.
            #
            # Cadence: the per-employee screenshot interval, expressed as a
            # whole number of scan intervals. It is snapped to the interval grid
            # rather than run on its own clock because a shot can only be
            # uploaded once THIS slot's POST hands back an id to attach it to,
            # and Gauzy's screenshot views are scoped to a same-day TimeLog — a
            # shot with no slot behind it is stored but never renders. Capturing
            # off-grid would manufacture exactly those invisible orphans, so a
            # requested cadence faster than the scan interval is honoured by
            # capturing every interval rather than by capturing off-grid.
            want_shot = cfg.get("capture_screenshots")
            if want_shot and cfg.get("screenshot_gate", "dashboard").lower() == "dashboard":
                want_shot = client.screenshots_enabled()
            shot_due = True
            shot_secs = int(setting(cfg, overrides, "screenshot_interval_seconds", 0) or 0)
            if want_shot and shot_secs > interval:
                every_n = max(1, int(round(float(shot_secs) / interval)))
                shot_due = (cycle % every_n == 0)
            shot = capture_screenshot(cfg) if (want_shot and shot_due) else None
            windows = list_windows()      # all open windows (X11 only; [] on Wayland)
            curr = scan_proc()
            rows = build_process_rows(prev, curr, interval, cfg, compiled, excluded,
                                      fg_seconds, fg_by_pid, windows)
            prev = curr
            if not rows and not tabs:
                log(cfg, "nothing to report this interval")
                continue
            status, resp = client.post_time_slot(rows, tabs, started, interval,
                                                 active_seconds, audio_seconds)
            if status in (200, 201):
                pct = int(active_seconds / interval * 100)
                state = "ACTIVE" if active_seconds > 0 else "IDLE"
                # Show media time whenever media played. When it counted towards
                # active this reads "audio Ns"; when the employee is on
                # media-as-idle it reads "media Ns, idle" — which is the line an
                # admin needs to see to trust that an idle-looking interval with
                # Spotify running was classified deliberately, not missed.
                if audio_seconds:
                    extra = f" (audio {audio_seconds}s)"
                elif media_seconds:
                    extra = f" (media {media_seconds}s, idle)"
                else:
                    extra = ""
                fg = [r for r in rows if r["foreground_seconds"] > 0]
                watching = ", ".join(f"{r['name']}" for r in fg[:3]) or "-"
                wins = f" | {len(windows)} windows" if windows else ""
                shot_note = ""
                if cfg.get("capture_screenshots"):
                    if not want_shot:
                        shot_note = " | shots OFF (dashboard)"
                    elif not shot_due:
                        # Say so rather than stay silent: an interval with no
                        # shot line otherwise looks like a capture failure.
                        shot_note = f" | no shot (every {shot_secs}s)"
                    else:
                        shot_note = _upload_screenshot(client, cfg, shot, started, resp)
                log(cfg, f"{state} {pct}% ({active_seconds}/{interval}s){extra} | "
                         f"{len(rows)} apps, on-screen: {watching} | "
                         f"{len(tabs)} tabs{wins}{shot_note}")
            elif status == 401:
                log(cfg, "token expired, re-login")
                client.login()
                if cfg.get("maintain_timer", True):
                    client.start_timer()   # the new session needs its timer too
            else:
                log(cfg, f"push failed HTTP {status}: {str(resp)[:150]}")
    except KeyboardInterrupt:
        log(cfg, "stopped")
    finally:
        # By default the timer is LEFT RUNNING on exit, so a service restart
        # keeps tracking continuous. Only stop it if explicitly asked to.
        if cfg.get("maintain_timer", True) and cfg.get("stop_timer_on_exit", False):
            client.stop_timer()


if __name__ == "__main__":
    main()
