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
import email.utils
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
from datetime import datetime, timedelta, timezone

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
    # Take the time from the server rather than the workstation clock. The
    # server's `Date` header anchors a boottime-based clock, so a machine whose
    # time is wrong — or has been changed — still records correct timestamps,
    # and an outage does not disturb it. False falls back to the system clock.
    "use_network_time": True,
    # Log a warning when the system clock differs from the server's by more than
    # this many seconds. The tracker records correctly either way; this is what
    # makes a broken or tampered-with workstation clock visible instead of silent.
    "clock_skew_warn_seconds": 30,

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
    # How long without keyboard/mouse before a moment counts as idle. You remain
    # "active" for this long after your last keystroke, so short pauses for
    # reading or thinking do not register as idle. Overridable per employee.
    "idle_threshold_seconds": 180,
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
    # Blur captured screenshots past legibility before upload. Overridable per
    # employee, so privacy can be granted to some staff and not others. The blur
    # is applied HERE, before the image leaves the machine — a readable screen is
    # never transmitted or stored, which is the difference between privacy and a
    # dashboard that merely declines to show it.
    "blur_screenshots": False,
    # Downscale divisor. Higher blurs harder; 20 makes body text unreadable while
    # window shapes stay recognisable.
    "blur_strength": 20,
    # Scale captures down to at most this width before upload, keeping the aspect
    # ratio. 0 leaves them at native resolution. 800 halves a 1600x900 screen and
    # removes about 62% of the stored bytes while leaving 14px monospace text
    # readable; a third of native is where text stops being legible. Never
    # upscales, so a smaller screen is left alone.
    "screenshot_max_width": 800,
    # Encode as JPEG at this quality instead of PNG. 0 keeps PNG. 75 roughly
    # halves what scaling alone achieves — 800x450 is ~92 KB as PNG, ~52 KB here.
    # Screenshots are flat colour with text over it: PNG stores that faithfully,
    # JPEG approximates it, and the ringing around glyphs does not matter at
    # monitoring resolution.
    "screenshot_jpeg_quality": 75,
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


# --------------------------------------------------------------------------- #
# Network clock
#
# The workstation clock cannot be relied on for a record that is meant to be
# relied on. Anyone able to set the time on their own machine can shift their
# hours, or erase a span of the day by winding back and letting the server
# discard the resulting duplicate slots. Ordinary drift does the same thing
# accidentally on a machine whose NTP is broken.
#
# So the server's clock is the reference. Every API response carries a `Date`
# header, and the tracker is already making a request every interval, so this
# costs nothing extra.
#
# Two details make it robust rather than merely clever:
#
#   * The anchor is (server time, CLOCK_BOOTTIME), not an offset against the
#     wall clock. Boottime cannot be set, does not jump, and — unlike
#     CLOCK_MONOTONIC — keeps counting across a suspend. So once anchored, the
#     time we report is immune to anything done to the system clock afterwards.
#
#   * Losing the network does not lose the clock. Boottime keeps advancing, so
#     the last anchor stays usable for as long as the machine stays up; the
#     tracker keeps recording correct times through an outage and simply
#     re-anchors on the first response when the network returns.
#
# Only if the tracker has never reached the server does it fall back to the
# system clock, because at that point there is nothing else.
# --------------------------------------------------------------------------- #

_net_anchor = None          # (server_utc_naive, boottime_at_that_moment)
_net_skew = None            # seconds the system clock is behind the server


def _boottime():
    """Seconds since boot, including time spent suspended."""
    return time.clock_gettime(time.CLOCK_BOOTTIME)


def note_server_date(date_header):
    """Re-anchor the clock from an HTTP `Date` header. Never raises.

    Called on every response, including error responses — a 401 carries just as
    honest a clock as a 200.
    """
    global _net_anchor, _net_skew
    if not date_header:
        return
    try:
        server = email.utils.parsedate_to_datetime(date_header)
        if server is None:
            return
        if server.tzinfo is not None:
            server = server.astimezone(timezone.utc).replace(tzinfo=None)
        _net_anchor = (server, _boottime())
        _net_skew = (datetime.now(timezone.utc).replace(tzinfo=None) - server).total_seconds()
    except Exception:
        return


def clock_skew():
    """How far the system clock is from the server's, in seconds, or None.

    Positive means the machine is ahead. Reported rather than silently
    corrected: a large value means the workstation clock is broken or has been
    tampered with, and that is worth seeing.
    """
    return _net_skew


def network_now():
    """UTC now from the server's clock, or None if never anchored."""
    if _net_anchor is None:
        return None
    server, at = _net_anchor
    return server + timedelta(seconds=_boottime() - at)


def now_ts(cfg):
    """The timestamp the tracker records with, naive, sent as-is.

    Prefers the server's clock (see above). Falls back to the system clock only
    when the server has never been reached, or when network time is switched
    off — and to LOCAL system time in that case only if use_local_time is set,
    which it should not be against an API that stores naive UTC.
    """
    if cfg.get("use_network_time", True):
        net = network_now()
        if net is not None:
            return net
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
    # Per employee: how long without input before the moment counts as idle.
    # Deliberately generous by default — reading, thinking and watching are work,
    # and a short threshold punishes them — but roles differ, so an admin can
    # tighten it for staff whose work is continuous input.
    threshold = int(setting(cfg, overrides, "idle_threshold_seconds", 180) or 180)
    recent_input = (idle is not None) and (idle < threshold)
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
# 'auto' prefers the durable extension, then the DeskTime-style gnome trick (so
# capture is silent and immediate before the extension is installed), and only
# then the portal.
#
# NOTE: 'auto' DOES reach the portal, and the portal flashes. An earlier version
# of this comment claimed it never did, which was wrong and cost a round of
# "why is the screen flashing?" — the silent routes can succeed at the startup
# probe and fail later, and every such failure flashes. If silence must be a
# guarantee rather than a preference, set screenshot_method to "gnome" or
# "extension": a fixed method never falls back, so a failed capture is a missing
# screenshot rather than a flash.
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


def blur_png(png, strength):
    """PNG bytes blurred beyond legibility, or the original on any failure.

    Monitoring versus privacy: an admin needs to see THAT someone is working and
    roughly on what, not to read their messages, credentials or a customer's
    personal data. Blurring keeps the shape of the screen — which window, which
    layout, whether anything is happening — while destroying the text.

    Implemented as downscale-then-upscale rather than a convolution kernel:
    GdkPixbuf is already a dependency for capturing, it does the resampling in C,
    and a box blur written in pure Python over a few million pixels would cost
    more CPU each interval than the capture itself. Reducing to 1/strength and
    stretching back is irreversible — the detail is gone from the file, not
    merely hidden, so nothing can be recovered from the stored image.
    """
    if not png:
        return png
    try:
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf

        loader = GdkPixbuf.PixbufLoader.new_with_type("png")
        loader.write(png)
        loader.close()
        pb = loader.get_pixbuf()
        if pb is None:
            return png
        w, h = pb.get_width(), pb.get_height()
        f = max(2, int(strength or 20))
        small = pb.scale_simple(max(1, w // f), max(1, h // f),
                                GdkPixbuf.InterpType.BILINEAR)
        if small is None:
            return png
        big = small.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR)
        if big is None:
            return png
        ok, buf = big.save_to_bufferv("png", [], [])
        return bytes(buf) if ok else png
    except Exception:
        # Never fail the interval over a blur. But note the caller MUST treat a
        # failure as "do not upload" rather than "upload the sharp original" —
        # silently sending an unblurred screen would be the opposite of what the
        # admin asked for.
        return None


def downscale_png(png, max_width):
    """PNG bytes scaled so the width is at most max_width, original on failure.

    Storage is the only cost of a screenshot that grows without bound: at full
    resolution one workstation writes roughly 66 MB a day, so ten of them fill a
    45 GB volume in about three months. Halving the dimensions removes about 62%
    of that, and a monitoring capture needs to show which window was on screen
    rather than be a faithful reproduction of it.

    Scaling proportionally rather than to a fixed size means a fleet of mixed
    monitor resolutions all lands at a comparable cost per image.

    Unlike blur_png this returns the ORIGINAL on failure rather than None. A
    full-size screenshot is merely expensive; an unblurred one breaks a promise
    made to the employee. Cost may degrade silently, privacy may not.
    """
    if not png or not max_width:
        return png
    try:
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf

        loader = GdkPixbuf.PixbufLoader.new_with_type("png")
        loader.write(png)
        loader.close()
        pb = loader.get_pixbuf()
        if pb is None:
            return png
        w, h = pb.get_width(), pb.get_height()
        if w <= int(max_width):
            return png                       # already small enough; do not upscale
        nw = int(max_width)
        nh = max(1, round(h * nw / w))
        small = pb.scale_simple(nw, nh, GdkPixbuf.InterpType.BILINEAR)
        if small is None:
            return png
        ok, buf = small.save_to_bufferv("png", [], [])
        return bytes(buf) if ok else png
    except Exception:
        return png


def encode_jpeg(png, quality):
    """(bytes, filename, content_type) — JPEG if asked for, else the PNG as-is.

    Runs LAST, after any scaling and blurring, because both of those load and
    save PNG: handing them a JPEG would make the loader fail and the shot would
    be dropped or left unscaled.

    JPEG roughly halves what scaling alone achieves — 800x450 costs about 92 KB
    as PNG and 52 KB at quality 75 — because a screenshot is mostly flat colour
    with text over it, which PNG stores faithfully and JPEG approximates. The
    approximation shows as ringing around text, which at monitoring resolution
    is not a meaningful loss.

    The server derives the stored extension from the upload filename and builds
    its thumbnail from the bytes, so both must change together; sending JPEG
    bytes named .png stores a file no browser will render.
    """
    if not png or not quality:
        return png, "screenshot.png", "image/png"
    try:
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf

        loader = GdkPixbuf.PixbufLoader.new_with_type("png")
        loader.write(png)
        loader.close()
        pb = loader.get_pixbuf()
        if pb is None:
            return png, "screenshot.png", "image/png"
        ok, buf = pb.save_to_bufferv("jpeg", ["quality"], [str(int(quality))])
        if not ok:
            return png, "screenshot.png", "image/png"
        return bytes(buf), "screenshot.jpg", "image/jpeg"
    except Exception:
        return png, "screenshot.png", "image/png"


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
                # Re-anchor the clock on every response. This is the only place
                # the tracker learns the server's time, and it happens on traffic
                # it was sending anyway.
                note_server_date(resp.headers.get("Date"))
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            # An error response carries just as honest a clock as a success one.
            note_server_date(e.headers.get("Date") if e.headers else None)
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, {"message": raw.decode("utf-8", "replace")[:200]}
        except urllib.error.URLError as e:
            # No response, so no clock. The existing anchor stays valid — it
            # advances on boottime, not on anything the network provides.
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
        # There is exactly ONE settings row per employee: POST to this endpoint
        # is an upsert keyed on the employee, not an insert, and it replaces the
        # whole `data` object. Both the dashboard and this tracker therefore
        # read-merge-write that single row rather than writing their own.
        path = (f"/api/employee-settings?where[employeeId]={self.employee_id}"
                f"&where[tenantId]={self.tenant_id}"
                f"&where[organizationId]={self.organization_id}")
        status, data = self._request("GET", path)
        if status not in (200, 201):
            return None
        items = data if isinstance(data, list) else (
            data.get("items", []) if isinstance(data, dict) else [])
        # Newest wins among the admin's own rows: the dashboard writes a fresh
        # row rather than mutating the old one, so only the last entry reflects
        # what the admin currently intends.
        out = {}
        for it in items:
            if isinstance(it, dict) and isinstance(it.get("data"), dict):
                out = it["data"]
        return out

    # ---- daily usage summary -------------------------------------------- #
    #
    # Why the tracker publishes this at all: Gauzy's activity list endpoint is
    # hard-capped at 30 rows in its controller (`{ page: 0, limit: 30 }`, with a
    # whitelisting validation pipe that strips any limit you pass), so a
    # dashboard cannot read a day of per-app activity — it sees 30 of several
    # thousand rows and reports minutes where there were hours. The aggregating
    # `/activity/daily` endpoint returns complete totals but drops `metaData`,
    # which is where foreground seconds live. Neither endpoint alone can answer
    # "how long was this app actually on screen today".
    #
    # So the tracker, which has the numbers already, keeps a running daily total
    # in the employee's own record and the dashboard reads that instead.
    #
    # Written as settingType=Normal, in ONE row that this process created and
    # holds the id of. It never updates a row it did not create, and never
    # writes a Custom row — those belong to the admin.

    _usage_row_id = None
    _usage_date = None

    def _find_usage_row(self, day):
        """Id of this employee's usage row for `day`, or None."""
        path = (f"/api/employee-settings?where[employeeId]={self.employee_id}"
                f"&where[tenantId]={self.tenant_id}"
                f"&where[organizationId]={self.organization_id}"
                f"&where[settingType]=Normal")
        status, data = self._request("GET", path)
        if status not in (200, 201):
            return None, {}
        items = data if isinstance(data, list) else (
            data.get("items", []) if isinstance(data, dict) else [])
        for it in items:
            d = it.get("data") if isinstance(it, dict) else None
            if isinstance(d, dict) and d.get("date") == day:
                return it.get("id"), d
        return None, {}

    def usage_for(self, day):
        """Today's already-published totals, so a restart resumes the day rather
        than zeroing it.

        `marks` comes back too: without it a tracker restarted at lunch would
        report the day as starting at lunch, which is exactly the number an
        admin would read as the employee arriving late.

        Returns None when the settings could not be READ, which is emphatically
        not the same as a day with nothing in it. Treating the two alike loses
        real data: a tracker restarted while the API happens to be down resumes
        an empty day and, on its next publish, overwrites hours of recorded
        totals with a few minutes. The caller must retry rather than reset."""
        data = self.employee_settings()
        if data is None:
            return None
        u = data.get("usage")
        if isinstance(u, dict) and u.get("date") == day:
            return {"apps": u.get("apps") or {},
                    "hours": u.get("hours") or {},
                    "marks": u.get("marks") or {},
                    "segments": u.get("segments") or []}
        return {"apps": {}, "hours": {}, "marks": {}, "segments": []}

    def publish_usage(self, day, summary):
        """Publish today's per-app running and on-screen seconds.

        Why the tracker publishes this at all: Gauzy's activity list endpoint is
        hard-capped at 30 rows in its controller (`{ page: 0, limit: 30 }`, with
        a whitelisting pipe that strips any limit you pass), so a dashboard
        cannot read a day of per-app activity — it sees 30 rows of several
        thousand and reports minutes where there were hours. The aggregating
        `/activity/daily` endpoint is complete but drops `metaData`, which is
        where foreground seconds live. Neither can answer "how long was this app
        on screen today", so the tracker publishes the totals it already has.

        READ-MERGE-WRITE, and never a blind write. There is one settings row per
        employee and POST replaces its entire `data` object, so writing only the
        usage would destroy the admin's screenshot interval, media rule and blur
        setting — which is exactly what happens if you assume these are separate
        records. The row is re-read immediately before each write so the window
        in which a dashboard save could be lost is milliseconds rather than the
        settings cache lifetime.

        Never raises: a failed summary must not interrupt tracking."""
        try:
            current = self.employee_settings()
            if current is None:
                return False              # could not read: do NOT write blind
            merged = dict(current)
            merged["usage"] = {"date": day,
                               "apps": summary.get("apps") or {},
                               # Per-hour buckets, so the chart never has to read
                               # the capped activity or time-slot endpoints: they
                               # return ~30 rows of the several hundred a day
                               # produces, and almost none carry foreground
                               # seconds, so every hour collapsed to Neutral.
                               "hours": summary.get("hours") or {},
                               # Wall-clock marks the hour buckets cannot carry:
                               # when tracking began, when the current idle run
                               # began, and when work resumed after it. Summing
                               # into hour buckets discards the minute, so these
                               # are recorded at the moment the transition is
                               # observed instead of being derived later.
                               "marks": summary.get("marks") or {},
                               # The day as a sequence rather than a set of
                               # totals: {s, e, k, a} per episode, merged across
                               # consecutive like intervals. Gaps between one
                               # entry's end and the next entry's start are time
                               # the tracker was not running.
                               "segments": summary.get("segments") or [],
                               "source": "system-tracker"}
            status, _ = self._request("POST", "/api/employee-settings", {
                "employeeId": self.employee_id,
                "organizationId": self.organization_id,
                "tenantId": self.tenant_id,
                "entity": "Employee",
                "entityId": self.employee_id,
                "settingType": "Custom",
                "data": merged,
            })
            return status in (200, 201, 202)
        except Exception:
            return False

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

    def post_screenshot(self, data, recorded_at, time_slot_id=None,
                        filename="screenshot.png", image_type="image/png"):
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
        # filename and image_type travel together with the bytes: the server
        # derives the stored extension from the name, so JPEG bytes sent as .png
        # would store a file no browser will render.
        body, content_type = _multipart_body(fields, "file", filename,
                                             image_type, data)
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


def _upload_screenshot(client, cfg, png, started, slot_resp, quality=0):
    """Attach this interval's screenshot to the slot just created, and return a
    short note for the log line.

    Encoding happens here rather than inside post_screenshot so the log can
    report what was actually sent. Reporting the pre-encoding size would claim
    92KB for a 52KB upload, and this log is the first thing anyone reads when
    asking whether the storage change took effect.

    Never raises: a screenshot that fails to capture or upload must not take
    process tracking down with it."""
    if not png:
        return " | no shot"
    slot_id = slot_resp.get("id") if isinstance(slot_resp, dict) else None
    data, filename, image_type = encode_jpeg(png, quality)
    try:
        status, resp = client.post_screenshot(data, started, slot_id,
                                              filename, image_type)
    except Exception as exc:
        return f" | shot error: {str(exc)[:40]}"
    if status in (200, 201):
        kind = "jpg" if image_type == "image/jpeg" else "png"
        return (f" | shot {len(data) // 1024}KB {kind}"
                + ("" if slot_id else " (unattached)"))
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
    # Say which clock is in force, and complain if this machine's own is wrong.
    # login() has already made a request, so the anchor exists by now.
    _skew = clock_skew()
    if cfg.get("use_network_time", True) and network_now() is not None:
        log(cfg, f"clock: server time (system clock is {_skew:+.0f}s off)")
        if _skew is not None and abs(_skew) > float(cfg.get("clock_skew_warn_seconds", 30)):
            log(cfg, f"clock: WARNING this machine's clock is {_skew:+.0f}s from the "
                     "server. Tracking is unaffected — timestamps come from the "
                     "server — but the workstation clock needs fixing: "
                     "sudo timedatectl set-ntp true")
    else:
        log(cfg, "clock: system time (server clock unavailable)")
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
    _idle_after = int(setting(cfg, _boot, "idle_threshold_seconds", 180) or 180)
    if _idle_after != cfg.get("idle_threshold_seconds", 180):
        log(cfg, f"idle rule: idle after {_idle_after}s without input (per-employee)")
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
    # Per-day per-app totals published for the dashboard. Kept here rather than
    # recomputed from Gauzy because the API cannot return a full day of activity
    # rows — see GauzyClient.post_usage_summary for why.
    usage_day = None     # the date these totals belong to
    # {"apps": {name: {"r": running, "s": on_screen}},
    #  "hours": {"HH": {"wall": s, "active": s, "apps": {name: on_screen}}},
    #  "marks": {"started_at": "HH:MM", "last_idle_started_at": "HH:MM"|None,
    #            "last_active_resumed_at": "HH:MM"|None},
    #  "segments": [{"s": "HH:MM", "e": "HH:MM", "k": "active"|"idle",
    #                "a": on-screen app or None}]}
    usage = {"apps": {}, "hours": {}, "marks": {}, "segments": []}
    # Active/idle state of the previous interval, so a change of state can be
    # timed. None until the first interval: a restart must not invent an idle
    # transition that never happened.
    prev_active = None
    # Anchor for a drift-free schedule. Each cycle is credited a flat `interval`
    # of tracked time, so each cycle must actually OCCUPY an interval of wall
    # clock — no more. Timing the sampling window on its own does not achieve
    # that: the timer re-assertion, the settings fetch, the screenshot (up to
    # screenshot_timeout_seconds) and the POST all sit outside it, so a cycle ran
    # interval + overhead while crediting interval. The shortfall was small per
    # cycle and invisible in any single slot, but it accumulated all day and
    # surfaced on the dashboard as "unmonitored" time for someone who had never
    # stopped working.
    #
    # Deadlines are computed from this anchor rather than from "now" so the
    # error cannot compound: a slow cycle borrows from the next one instead of
    # pushing every subsequent cycle later.
    #
    # monotonic, not wall clock: it does not advance across a suspend, so time
    # the machine spent asleep is never credited as worked. That absence SHOULD
    # read as unmonitored — it is the honest answer.
    schedule_anchor = time.monotonic()
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
            # End of THIS cycle on the fixed schedule, so the work already done
            # above is absorbed by the sampling window rather than added to it.
            deadline = schedule_anchor + cycle * interval
            # If the overhead alone outran a whole interval — a long screenshot,
            # a slow API, a suspend — the schedule cannot be honoured without
            # sampling for a negative time. Re-anchor rather than sprint through
            # cycles trying to catch up, which would credit interval each time
            # for slots that never happened.
            behind = time.monotonic() - deadline
            if behind > 0:
                if behind > interval:
                    log(cfg, f"note: {int(behind)}s behind schedule, re-anchoring")
                    schedule_anchor = time.monotonic() - cycle * interval
                deadline = time.monotonic()
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
            # Scale FIRST, so the blur below resamples a smaller image — blurring
            # is itself a downscale-and-stretch, and doing it before scaling would
            # resample twice for no benefit.
            if shot:
                shot = downscale_png(shot, setting(cfg, overrides, "screenshot_max_width", 0))
            # Blur before the image goes anywhere. If blurring fails the shot is
            # DROPPED, never uploaded sharp — an employee promised a blurred
            # screen must not have a readable one sent because a library threw.
            blurred = False
            if shot and setting(cfg, overrides, "blur_screenshots", False):
                shot = blur_png(shot, setting(cfg, overrides, "blur_strength", 20))
                blurred = shot is not None
            windows = list_windows()      # all open windows (X11 only; [] on Wayland)
            curr = scan_proc()
            rows = build_process_rows(prev, curr, interval, cfg, compiled, excluded,
                                      fg_seconds, fg_by_pid, windows)
            prev = curr
            if not rows and not tabs:
                log(cfg, "nothing to report this interval")
                continue
            # Accumulate the day's totals before posting. Reset on rollover so
            # a tracker left running overnight does not fold two days together.
            # The usage summary is a HUMAN report, so it is keyed by the
            # machine's local wall clock — not by `started`, which is UTC
            # whenever use_local_time is false. Keying it in UTC put an IST
            # afternoon into the 03:00-09:00 bars and, near midnight, filed work
            # under the wrong day entirely. What the tracker POSTS to Gauzy is
            # unchanged; only these report buckets are local.
            local_now = datetime.now()
            today = local_now.strftime("%Y-%m-%d")
            if usage_day != today:
                # Resume the day rather than restarting it — see usage_for.
                resumed = client.usage_for(today)
                if resumed is None:
                    # Could not read what is already recorded. Accumulating now
                    # would build a day from zero and the next publish would
                    # overwrite the real one, so this cycle contributes nothing
                    # to the report and the resume is retried next interval.
                    # Posting time slots is unaffected — that is the record that
                    # matters, and this is only the summary built on top of it.
                    log(cfg, "note: could not read today's totals; report paused "
                             "this interval rather than restarting the day")
                else:
                    usage_day, usage = today, resumed
            if usage_day != today:
                status, resp = client.post_time_slot(rows, tabs, started, interval,
                                                     active_seconds, audio_seconds)
                if status in (200, 201):
                    log(cfg, f"posted slot ({int(active_seconds)}/{interval}s active), report deferred")
                prev_active = active_seconds > 0
                continue
            day_apps = usage.setdefault("apps", {})
            hours = usage.setdefault("hours", {})
            marks = usage.setdefault("marks", {})
            # Wall-clock marks. The hour buckets above sum the minute away, so
            # "idle began at 14:37" cannot be recovered from them afterwards —
            # it has to be noticed as it happens.
            #
            # Times name the START of the interval, not its end: the transition
            # happened somewhere inside it, and its start is the honest bound.
            # Resolution is therefore one interval (60s by default), which is
            # what the tracker actually knows — not a second more.
            slot_start = (local_now - timedelta(seconds=interval)).strftime("%H:%M")
            is_active = active_seconds > 0
            marks.setdefault("started_at", slot_start)
            if prev_active is not None and prev_active != is_active:
                if is_active:
                    marks["last_active_resumed_at"] = slot_start
                else:
                    marks["last_idle_started_at"] = slot_start
                    # A fresh idle run makes the previous "resumed" stale: the
                    # pair must read as one episode, or the dashboard shows work
                    # resuming before the idle it resumed from.
                    marks["last_active_resumed_at"] = None
            prev_active = is_active
            # Hour bucket for this slot. wall/active give the chart its idle
            # split; per-app foreground seconds give the productive split. Both
            # are recorded here because the API cannot serve either at day scale.
            hb = hours.setdefault(local_now.strftime("%H"),
                                  {"wall": 0, "active": 0, "apps": {}, "focus": {}})
            hb.setdefault("focus", {})   # hours written before `focus` existed
            hb["wall"] += interval
            hb["active"] += int(active_seconds)
            for r in rows:
                fg = int(r.get("foreground_seconds", 0) or 0)
                acc = day_apps.setdefault(r["name"], {"r": 0, "s": 0})
                acc["r"] += interval
                acc["s"] += fg
                # Only apps actually on screen go in the hour bucket — a bucket
                # listing every headless process would be mostly zeroes.
                if fg:
                    hb["apps"][r["name"]] = hb["apps"].get(r["name"], 0) + fg
                    # `focus` is the same seconds keyed for CLASSIFICATION rather
                    # than for reporting: browsers are replaced by their tab
                    # titles below, so "youtube" can be classified separately from
                    # the dashboard even though both are the chrome process.
                    # `apps` is left alone — App usage reports per application,
                    # and splitting it by tab would turn one row into fifty.
                    if not any(b in r["name"] for b in browsers):
                        hb["focus"][r["name"]] = hb["focus"].get(r["name"], 0) + fg
            for tab_title, tab_secs in tabs.items():
                hb["focus"][tab_title] = hb["focus"].get(tab_title, 0) + int(tab_secs)

            # Day timeline: what was happening, and WHEN. The hour buckets above
            # can say the 10:00 hour was 40% idle; they cannot say idle ran from
            # 10:40 to 11:00, because summing into an hour discards the order.
            #
            # Only the app is recorded, never a productivity category: the
            # admin's app-to-category mapping lives in the dashboard and changes
            # there. Categorising here would bake one day's mapping into history
            # and need a tracker redeploy to correct.
            #
            # Consecutive intervals in the same state and the same app extend the
            # previous entry rather than adding one, which keeps a full day to a
            # few dozen entries instead of ~1,400.
            top_app = None
            if active_seconds > 0 and rows:
                on_screen = [r for r in rows if int(r.get("foreground_seconds", 0) or 0) > 0]
                if on_screen:
                    top_app = max(on_screen,
                                  key=lambda r: int(r.get("foreground_seconds", 0) or 0))["name"]
                    # Every browser tab is the same process, so reporting "chrome"
                    # makes an hour of YouTube indistinguishable from an hour of
                    # the company dashboard. When the browser is what is on screen,
                    # the tab title is the only thing that says which — so it, not
                    # the process, is what gets classified.
                    if any(b in top_app for b in browsers) and tabs:
                        top_app = max(tabs.items(), key=lambda kv: kv[1])[0]
            segments = usage.setdefault("segments", [])
            end_hm = local_now.strftime("%H:%M")
            if (segments and segments[-1].get("k") == ("active" if is_active else "idle")
                    and segments[-1].get("a") == top_app
                    and segments[-1].get("e") == slot_start):
                # Contiguous with the previous entry: extend it.
                segments[-1]["e"] = end_hm
            else:
                segments.append({"s": slot_start, "e": end_hm,
                                 "k": "active" if is_active else "idle",
                                 "a": top_app})

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
                    elif shot is None and setting(cfg, overrides, "blur_screenshots", False):
                        shot_note = " | shot DROPPED (blur failed, not sent sharp)"
                    else:
                        shot_note = _upload_screenshot(
                            client, cfg, shot, started, resp,
                            setting(cfg, overrides, "screenshot_jpeg_quality", 0))
                        if blurred:
                            shot_note += " blurred"
                # Publish after the slot, so a failed summary never costs us the
                # slot itself — tracking matters more than the report.
                # Publish every 5th interval, not every one. The write is a
                # read-merge-write against the same row the dashboard saves to,
                # so a lower frequency shrinks the window in which an admin's
                # save could be overwritten, at the cost of the report trailing
                # reality by a few minutes — the right trade for a daily total.
                if cycle % 5 == 0:
                    client.publish_usage(today, usage)
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
