#!/usr/bin/env python3
"""
System-Tracker — background/backend process tracker for Ever Gauzy.

Captures which processes are running per interval (GUI apps AND headless
backends — node, postgres, docker, plus dev tools like VS Code, Postman,
Antigravity) and pushes them into a Gauzy instance as APP activities inside
time slots, using the same API the official desktop agent uses.

This fills the gap the Gauzy agent and ActivityWatch both leave on Linux:
neither sees background/headless processes. See docs/feasibility.md.

Stdlib only — no pip install. Works on Wayland and X11 (reads /proc, not windows).
"""

import json
import os
import time
import re
import sys
import ssl
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
    # A process is reported if its name matches one of these patterns
    # (case-insensitive regex). Empty list => report every user process
    # above cpu_min_percent. Kernel threads are always skipped.
    "watchlist": [
        # editors / dev tools
        r"code", r"postman", r"antigravity", r"sublime", r"idea", r"pycharm",
        # terminals + shells + terminal tools
        r"gnome-terminal", r"konsole", r"xterm", r"kitty", r"alacritty",
        r"tilix", r"terminator", r"terminal",
        r"^bash$", r"^zsh$", r"^fish$", r"tmux", r"screen$",
        r"vim", r"nvim", r"nano", r"emacs", r"htop", r"ssh",
        # runtimes / backends
        r"node", r"postgres", r"docker", r"dockerd", r"containerd",
        r"nginx", r"python", r"php", r"redis", r"mysql", r"mariadb",
        r"java", r"ruby", r"go$",
        # browsers / media
        r"chrome", r"firefox", r"spotify",
    ],
    # Processes matching any of these are ALWAYS skipped, even if they match the
    # watchlist — filters out helper/sandbox noise (e.g. chrome-sandbox).
    "exclude": [
        r"sandbox", r"crashpad", r"crash.?handler", r"-helper",
        r"gpu.?process", r"utility", r"zygote", r"broker",
    ],
    # If watchlist is empty, only report processes using at least this much
    # CPU in the interval (percent of one core). Ignored when watchlist is set.
    "cpu_min_percent": 1.0,
    # Report at most this many distinct processes per interval (busiest first).
    "max_processes": 40,
    "verbose": True,
}


def load_config(path):
    cfg = dict(DEFAULT_CONFIG)
    if path and os.path.exists(path):
        with open(path) as fh:
            cfg.update(json.load(fh))
    # env overrides for secrets in deployment
    cfg["server_url"] = os.environ.get("GAUZY_URL", cfg["server_url"])
    cfg["email"] = os.environ.get("GAUZY_EMAIL", cfg["email"])
    cfg["password"] = os.environ.get("GAUZY_PASSWORD", cfg["password"])
    return cfg


def log(cfg, *args):
    if cfg.get("verbose"):
        print(f"[{datetime.now():%H:%M:%S}]", *args, flush=True)


# --------------------------------------------------------------------------- #
# /proc scanner
# --------------------------------------------------------------------------- #

_CLK_TCK = os.sysconf("SC_CLK_TCK")  # clock ticks per second (usually 100)


def _read(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except (OSError, IOError):
        return None


def scan_proc():
    """Return {pid: {"name": str, "cpu_ticks": int, "cmdline": str}} for
    every live user process (kernel threads excluded)."""
    out = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = entry
        cmdline_raw = _read(f"/proc/{pid}/cmdline")
        # kernel threads have an empty cmdline — skip them
        if not cmdline_raw:
            continue
        stat = _read(f"/proc/{pid}/stat")
        if not stat:
            continue
        try:
            # comm is field 2, wrapped in parens and may contain spaces/parens;
            # fields after the last ')' are space-separated.
            s = stat.decode("utf-8", "replace")
            rparen = s.rfind(")")
            comm = s[s.find("(") + 1:rparen]
            rest = s[rparen + 2:].split()
            utime = int(rest[11])  # field 14 overall (0-indexed here 11)
            stime = int(rest[12])  # field 15
        except (ValueError, IndexError):
            continue
        cmdline = cmdline_raw.replace(b"\x00", b" ").decode("utf-8", "replace").strip()
        # Prefer the real basename from cmdline when comm is truncated (comm caps at 15 chars)
        name = comm
        if cmdline:
            first = cmdline.split(" ")[0]
            base = os.path.basename(first)
            if base and not base.startswith("["):
                name = base or comm
        out[pid] = {"name": name, "cpu_ticks": utime + stime, "cmdline": cmdline[:200]}
    return out


def compile_watchlist(patterns):
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def match(name, compiled):
    return any(rx.search(name) for rx in compiled)


def diff_processes(prev, curr, interval, cfg, compiled, excluded):
    """Compare two /proc snapshots taken `interval` seconds apart and return a
    list of {name, cpu_percent} for processes to report this interval."""
    agg = {}  # name -> cpu_ticks delta
    for pid, info in curr.items():
        name = info["name"]
        # a process running the whole interval counts; new ones count too
        prev_ticks = prev.get(pid, {}).get("cpu_ticks", info["cpu_ticks"])
        delta = max(0, info["cpu_ticks"] - prev_ticks)
        agg.setdefault(name, 0)
        agg[name] += delta

    rows = []
    for name, ticks in agg.items():
        # noise filter first — helper/sandbox processes are never reported
        if excluded and match(name, excluded):
            continue
        cpu_percent = (ticks / _CLK_TCK) / interval * 100.0
        if compiled:
            if not match(name, compiled):
                continue
        else:
            if cpu_percent < cfg["cpu_min_percent"]:
                continue
        rows.append({"name": name, "cpu_percent": round(cpu_percent, 1)})
    rows.sort(key=lambda r: r["cpu_percent"], reverse=True)
    return rows[: cfg["max_processes"]]


# --------------------------------------------------------------------------- #
# Gauzy API client
# --------------------------------------------------------------------------- #

class GauzyClient:
    def __init__(self, cfg):
        self.base = cfg["server_url"].rstrip("/")
        self.cfg = cfg
        self.token = None
        self.employee_id = None
        self.organization_id = None
        self.tenant_id = None
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
            {"email": self.cfg["email"], "password": self.cfg["password"]},
            auth=False,
        )
        if status != 200 or not data.get("token"):
            raise RuntimeError(f"login failed (HTTP {status}): {data.get('message', data)}")
        self.token = data["token"]
        user = data.get("user", {})
        emp = user.get("employee") or {}
        self.employee_id = emp.get("id")
        self.organization_id = emp.get("organizationId")
        self.tenant_id = emp.get("tenantId") or user.get("tenantId")
        if not (self.employee_id and self.organization_id and self.tenant_id):
            raise RuntimeError(
                "login ok but this user has no employee record / org / tenant. "
                "Use an account that is an Employee in an organization."
            )
        return user

    def post_time_slot(self, activities, started_at, duration, overall):
        """activities: list of {name, cpu_percent}. Wraps them as APP activities
        in a Gauzy time slot and posts it."""
        date = started_at.strftime("%Y-%m-%d")
        tm = started_at.strftime("%H:%M:%S")
        recorded = started_at.isoformat()
        acts = [
            {
                "title": a["name"],
                "duration": duration,
                "type": "APP",
                "projectId": None,
                "date": date,
                "time": tm,
                "recordedAt": recorded,
                "organizationId": self.organization_id,
                "employeeId": self.employee_id,
                "metaData": [{"source": "system-tracker", "cpuPercent": a["cpu_percent"]}],
            }
            for a in activities
        ]
        payload = {
            "tenantId": self.tenant_id,
            "organizationId": self.organization_id,
            "employeeId": self.employee_id,
            "duration": duration,
            "keyboard": 0,
            "mouse": 0,
            "overall": overall,
            "startedAt": recorded,
            "recordedAt": recorded,
            "activities": acts,
        }
        return self._request("POST", "/api/timesheet/time-slot", payload)


# --------------------------------------------------------------------------- #
# Main loop
# --------------------------------------------------------------------------- #

def main():
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config.json"
    )
    cfg = load_config(cfg_path)
    compiled = compile_watchlist(cfg["watchlist"])
    excluded = compile_watchlist(cfg.get("exclude", []))
    interval = cfg["interval_seconds"]

    client = GauzyClient(cfg)
    log(cfg, f"Logging in to {cfg['server_url']} as {cfg['email']} ...")
    user = client.login()
    log(cfg, f"Authenticated. employee={client.employee_id[:8]} "
             f"org={client.organization_id[:8]}")
    log(cfg, f"Watchlist: {len(cfg['watchlist'])} patterns | interval {interval}s")

    prev = scan_proc()
    try:
        while True:
            time.sleep(interval)
            started = datetime.now(timezone.utc)
            curr = scan_proc()
            rows = diff_processes(prev, curr, interval, cfg, compiled, excluded)
            prev = curr
            if not rows:
                log(cfg, "no matching processes this interval")
                continue
            # overall "active" = sum of cpu across reported procs, capped at interval
            active = min(interval, int(sum(r["cpu_percent"] for r in rows) / 100.0 * interval) or 1)
            status, resp = client.post_time_slot(rows, started, interval, active)
            names = ", ".join(f"{r['name']}({r['cpu_percent']}%)" for r in rows[:8])
            if status in (200, 201):
                log(cfg, f"pushed {len(rows)} procs -> {names}")
            elif status == 401:
                log(cfg, "token expired, re-login")
                client.login()
            else:
                log(cfg, f"push failed HTTP {status}: {str(resp)[:160]}")
    except KeyboardInterrupt:
        log(cfg, "stopped")


if __name__ == "__main__":
    main()
