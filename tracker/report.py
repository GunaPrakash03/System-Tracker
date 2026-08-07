#!/usr/bin/env python3
"""
System-Tracker report — how long each app has been running.

Shows, for every tracked app currently alive, its RUNNING TIME (uptime, live
from /proc) and — if it can reach Gauzy — the TRACKED time recorded today.
This surfaces the "how long is this app running" number that Gauzy's built-in
Apps report does not show (that report only shows tracked duration).

When the admin settings app is reachable it also shows each app's PRODUCTIVITY
CATEGORY for the employee's department, and totals the time by category.

Usage:
    python3 report.py                 # uses ./config.json (or defaults)
    python3 report.py /path/config.json
    python3 report.py --no-gauzy      # skip the tracked-time column (offline)
    python3 report.py --no-categories # skip the productivity columns
"""

import json
import sys
import urllib.parse
import urllib.request
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
    # Match the tracker's clock: local wall-clock date by default.
    today = pt.now_ts(cfg).strftime("%Y-%m-%d")
    # Three things this endpoint is strict about, each a 400 or a silent empty
    # result if you get it wrong:
    #   * organizationId is REQUIRED ("organizationId must be a UUID"), even
    #     though the bearer token already identifies the caller.
    #   * start and end must be distinct instants — passing the same bare date
    #     for both fails with "Start date must be before to the end date", so
    #     the day is expressed as its opening and closing second.
    #   * the range is matched against stored UTC, which is what the tracker
    #     writes, so no local-time conversion belongs here.
    path = (f"/api/timesheet/activity?activityType=APP"
            f"&startDate={urllib.parse.quote(today + ' 00:00:00')}"
            f"&endDate={urllib.parse.quote(today + ' 23:59:59')}"
            f"&organizationId={client.organization_id}"
            f"&tenantId={client.tenant_id}"
            f"&employeeIds[0]={client.employee_id}")
    status, data = client._request("GET", path)
    if status not in (200, 201):
        return {}
    items = data if isinstance(data, list) else data.get("items", [])
    out = {}
    for it in items:
        title = it.get("title")
        if not title:
            continue
        out[title] = out.get(title, 0) + int(it.get("duration", 0) or 0)
    return out


def categories_for(cfg, employee_id):
    """{process_name: category} for this employee's department, plus the default
    for anything unclassified. ({}, None) when the admin app is unreachable.

    Fetched at REPORT time on purpose. Categories are a reporting lens, not a
    property of the captured data — no stored row carries one. That is what lets
    re-classifying an app, or moving someone to another department, correct
    historical reports as well as future ones. Baking the category in at capture
    would freeze yesterday's classification into yesterday's rows forever."""
    url = (cfg.get("categories_url") or "").strip()
    if not url:
        # Derive it from settings_url — the two live in the same admin app, so
        # configuring one and forgetting the other is the likely mistake.
        base = (cfg.get("settings_url") or "").strip()
        if not base:
            return {}, None
        url = base.replace("/api/settings", "/api/categories")
    sep = "&" if "?" in url else "?"
    try:
        req = urllib.request.Request(
            f"{url}{sep}employeeId={urllib.parse.quote(str(employee_id))}",
            headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except Exception:
        return {}, None
    if not isinstance(data, dict):
        return {}, None
    return (data.get("apps") or {}), (data.get("default") or "Neutral")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    cfg_path = args[0] if args else "config.json"
    cfg = pt.load_config(cfg_path)

    running = running_by_app(cfg)
    tracked = {} if "--no-gauzy" in flags else tracked_today(cfg)

    cats, default_cat = {}, None
    if "--no-categories" not in flags and "--no-gauzy" not in flags:
        try:
            client = pt.GauzyClient(cfg)
            client.login()
            cats, default_cat = categories_for(cfg, client.employee_id)
        except Exception:
            cats, default_cat = {}, None

    rows = sorted(running.items(), key=lambda kv: kv[1]["uptime"], reverse=True)
    show_tracked = bool(tracked)
    show_cats = default_cat is not None
    width = 40 + (16 if show_tracked else 0) + (16 if show_cats else 0)

    print()
    print(f"  App running times — {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("  " + "-" * width)
    header = f"  {'APP':<26}{'RUNNING FOR':<16}"
    if show_tracked:
        header += f"{'TRACKED TODAY':<16}"
    if show_cats:
        header += f"{'CATEGORY':<16}"
    print(header)
    print("  " + "-" * width)

    by_cat = {}
    for name, info in rows:
        line = f"  {name[:25]:<26}{pt.fmt_duration(info['uptime']):<16}"
        if show_tracked:
            t = tracked.get(name)
            line += (pt.fmt_duration(t) if t else "-").ljust(16)
        if show_cats:
            cat = cats.get(name.lower(), default_cat)
            line += cat.ljust(16)
            # Total the TRACKED time, not uptime: a database that has been up
            # for nine hours is not nine hours of anybody's working day.
            by_cat[cat] = by_cat.get(cat, 0) + int(tracked.get(name, 0) or 0)
        print(line)
    print("  " + "-" * width)
    print(f"  {len(rows)} apps running"
          + ("" if show_tracked else "   (run without --no-gauzy for tracked time)"))

    if show_cats and any(by_cat.values()):
        total = sum(by_cat.values()) or 1
        print()
        print("  Tracked time by category")
        print("  " + "-" * 40)
        for cat in ("Productive", "Neutral", "Unproductive"):
            secs = by_cat.get(cat, 0)
            print(f"  {cat:<16}{pt.fmt_duration(secs):<16}{secs * 100 // total:>3}%")
        print("  " + "-" * 40)
    elif show_cats and not show_tracked:
        # Categories resolved but there is no tracked time to total. Say which
        # of the two is missing rather than implying nothing is classified.
        print(f"  categories loaded ({len(cats)} app(s) classified) — no tracked "
              f"time today to total")
    elif show_cats:
        print(f"  categories: every app is {default_cat} "
              f"(nothing classified for this department yet)")
    print()


if __name__ == "__main__":
    main()
