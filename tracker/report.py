#!/usr/bin/env python3
"""
System-Tracker report — how long each app has been running.

Shows, for every tracked app currently alive, its RUNNING TIME (uptime, live
from /proc) and — if it can reach Gauzy — the TRACKED time recorded today.
This surfaces the "how long is this app running" number that Gauzy's built-in
Apps report does not show (that report only shows tracked duration).

Usage:
    python3 report.py                 # uses ./config.json (or defaults)
    python3 report.py /path/config.json
    python3 report.py --no-gauzy      # skip the tracked-time column (offline)
"""

import sys
from datetime import datetime, timezone

import proc_tracker as pt


def running_by_app(cfg):
    compiled = pt.compile_patterns(cfg["watchlist"])
    excluded = pt.compile_patterns(cfg.get("exclude", []))
    snap = pt.scan_proc()
    agg = {}  # name -> {"uptime": s, "count": n}
    for info in snap.values():
        name = info["name"]
        if excluded and pt.match(name, excluded):
            continue
        if compiled and not pt.match(name, compiled):
            continue
        a = agg.setdefault(name, {"uptime": 0, "count": 0})
        a["uptime"] = max(a["uptime"], info.get("uptime", 0))
        a["count"] += 1
    return agg


def tracked_today(cfg):
    """Return {app_title: tracked_seconds} for today's system-tracker APP
    activities, via the Gauzy API. {} on any failure."""
    try:
        client = pt.GauzyClient(cfg)
        client.login()
    except Exception:
        return {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Pull today's activities for this employee and sum durations per title.
    path = (f"/api/timesheet/activity?activityType=APP"
            f"&startDate={today}&endDate={today}"
            f"&employeeIds[0]={client.employee_id}")
    status, data = client._request("GET", path)
    if status not in (200, 201):
        return {}
    items = data.get("items", data if isinstance(data, list) else [])
    out = {}
    for it in items:
        title = it.get("title")
        if not title:
            continue
        out[title] = out.get(title, 0) + int(it.get("duration", 0) or 0)
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    cfg_path = args[0] if args else "config.json"
    cfg = pt.load_config(cfg_path)

    running = running_by_app(cfg)
    tracked = {} if "--no-gauzy" in flags else tracked_today(cfg)

    rows = sorted(running.items(), key=lambda kv: kv[1]["uptime"], reverse=True)
    show_tracked = bool(tracked)

    print()
    print(f"  App running times — {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("  " + "-" * (58 if show_tracked else 40))
    header = f"  {'APP':<26}{'RUNNING FOR':<16}"
    if show_tracked:
        header += f"{'TRACKED TODAY':<16}"
    print(header)
    print("  " + "-" * (58 if show_tracked else 40))
    for name, info in rows:
        line = f"  {name[:25]:<26}{pt.fmt_duration(info['uptime']):<16}"
        if show_tracked:
            t = tracked.get(name)
            line += (pt.fmt_duration(t) if t else "-").ljust(16)
        print(line)
    print("  " + "-" * (58 if show_tracked else 40))
    print(f"  {len(rows)} apps running"
          + ("" if show_tracked else "   (run without --no-gauzy for tracked time)"))
    print()


if __name__ == "__main__":
    main()
