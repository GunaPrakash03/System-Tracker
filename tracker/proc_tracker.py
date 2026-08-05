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
    "count_audio_as_active": True,      # background video/music keeps it active
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


def is_active_now(cfg):
    """Decide if this instant is active: recent input OR audio playing."""
    idle = get_idle_seconds()
    recent_input = (idle is not None) and (idle < cfg["idle_threshold_seconds"])
    audio = cfg.get("count_audio_as_active", True) and is_audio_playing()
    return recent_input or audio, {"idle_s": idle, "audio": audio,
                                   "recent_input": recent_input}


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
        self._ctx = ssl.create_default_context()

    def _request(self, method, path, body=None, auth=True):
        url = f"{self.base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
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


# --------------------------------------------------------------------------- #
# Main loop
# --------------------------------------------------------------------------- #

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

    prev = scan_proc()
    try:
        while True:
            started = datetime.now(timezone.utc)
            fg_seconds = {}       # wm_class -> seconds focused
            fg_by_pid = {}        # focused PID -> seconds focused (exact match)
            tabs = {}             # active browser tab title -> seconds watched
            active_seconds = 0    # seconds this slot was active (input or audio)
            audio_seconds = 0     # seconds audio/video was playing
            deadline = time.monotonic() + interval
            while time.monotonic() < deadline:
                time.sleep(fsample)
                # activity sample: active if recent input OR audio playing
                active, sig = is_active_now(cfg)
                if active:
                    active_seconds += fsample
                if sig["audio"]:
                    audio_seconds += fsample
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
                extra = f" (audio {audio_seconds}s)" if audio_seconds else ""
                fg = [r for r in rows if r["foreground_seconds"] > 0]
                watching = ", ".join(f"{r['name']}" for r in fg[:3]) or "-"
                wins = f" | {len(windows)} windows" if windows else ""
                log(cfg, f"{state} {pct}% ({active_seconds}/{interval}s){extra} | "
                         f"{len(rows)} apps, on-screen: {watching} | {len(tabs)} tabs{wins}")
            elif status == 401:
                log(cfg, "token expired, re-login"); client.login()
            else:
                log(cfg, f"push failed HTTP {status}: {str(resp)[:150]}")
    except KeyboardInterrupt:
        log(cfg, "stopped")


if __name__ == "__main__":
    main()
