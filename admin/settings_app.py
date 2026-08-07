#!/usr/bin/env python3
"""
System-Tracker admin settings app.

The surface where a super admin sets the things Gauzy has no field for:

  * per-employee screenshot interval   (Gauzy's screenshotFrequency is
                                        organisation-wide, not per employee)
  * per-employee "media counts as idle" rule
  * departments, and each app's productivity category WITHIN a department

Deliberately a separate app rather than a Gauzy fork. Gauzy is AGPL-3.0 and
already carries three source patches that cost a ~25-minute rebuild each time
they change; adding admin fields there would put every settings tweak behind
that same cycle. Talking to Gauzy over its REST API instead keeps this code
independent of that licence and rebuildable in a second.

Stdlib only, like the tracker: http.server + sqlite3 + urllib. No pip install,
no framework. Employees and departments are read live from the Gauzy API so
this app never becomes a second place where "who works here" is maintained;
only the mappings Gauzy cannot express are stored locally.

  python3 settings_app.py [config.json]

Binds to 127.0.0.1 by default. It has no login of its own, so exposing it on a
public interface would hand anyone the ability to turn a colleague's
screenshots off — put it behind the same reverse proxy and auth as Gauzy before
changing `bind_host`.
"""

import http.server
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from html import escape

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

DEFAULT_CONFIG = {
    "bind_host": "127.0.0.1",
    "bind_port": 8600,
    "db_path": "settings.db",
    # Read-only use of the Gauzy API: listing employees and departments so the
    # admin picks from real records instead of pasting UUIDs.
    "server_url": "http://localhost:3000",
    "email": "admin@ever.co",
    "password": "admin",
    # Category applied to an app nobody has classified yet. Neutral rather than
    # Unproductive on purpose: an unclassified app is an admin oversight, and
    # counting it against the employee would penalise them for it.
    "default_category": "Neutral",
    # Every view and write demands a Gauzy SUPER_ADMIN token. Only turn this off
    # for local development — with it false the port is wide open to anyone who
    # can reach it.
    "require_super_admin": True,
    # Origin the Gauzy dashboard is served from, for the browser preflight.
    # Not "*": that cannot carry credentials and would let any local page call
    # this API.
    "allow_origin": "http://localhost:4200",
}

CATEGORIES = ("Productive", "Neutral", "Unproductive")


def load_config(path):
    cfg = dict(DEFAULT_CONFIG)
    if path and os.path.exists(path):
        with open(path) as fh:
            cfg.update(json.load(fh))
    cfg["server_url"] = os.environ.get("GAUZY_URL", cfg["server_url"])
    cfg["email"] = os.environ.get("GAUZY_EMAIL", cfg["email"])
    cfg["password"] = os.environ.get("GAUZY_PASSWORD", cfg["password"])
    if not os.path.isabs(cfg["db_path"]):
        cfg["db_path"] = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      cfg["db_path"])
    return cfg


# --------------------------------------------------------------------------- #
# Storage
#
# Only what Gauzy cannot express lives here. Employee and department identities
# stay in Gauzy; these tables reference them by id and nothing more, so an
# employee deleted there simply stops being listed rather than leaving a
# half-valid duplicate record behind.
# --------------------------------------------------------------------------- #

SCHEMA = """
CREATE TABLE IF NOT EXISTS employee_settings (
    employee_id                TEXT PRIMARY KEY,
    screenshot_interval_seconds INTEGER,      -- NULL = no opinion, use tracker config
    count_audio_as_active      INTEGER,       -- NULL = no opinion; 0 = media is IDLE
    department_id              TEXT
);
CREATE TABLE IF NOT EXISTS app_category (
    department_id TEXT NOT NULL,
    app_name      TEXT NOT NULL,              -- process name, lowercase
    category      TEXT NOT NULL,
    PRIMARY KEY (department_id, app_name)
);
"""


def db(cfg):
    conn = sqlite3.connect(cfg["db_path"])
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# --------------------------------------------------------------------------- #
# Gauzy (read-only)
# --------------------------------------------------------------------------- #

class Gauzy:
    """Minimal read-only Gauzy client: enough to list employees and departments.

    Never writes. Every call returns [] on failure rather than raising, because
    an admin page that 500s when Gauzy restarts is worse than one that renders
    with an empty list and says so."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.token = None
        self.tenant_id = None
        self.organization_id = None

    def _request(self, method, path, body=None):
        url = self.cfg["server_url"].rstrip("/") + path
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            # Gauzy scopes reads by tenant and rejects the request without this
            # header — a bare bearer token returns 403 even for the caller's own
            # employee record. The tracker sends it for the same reason.
            if self.tenant_id:
                headers["Tenant-Id"] = self.tenant_id
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8", "replace")
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            return e.code, {}
        except Exception:
            return 0, {}

    def login(self):
        status, data = self._request("POST", "/api/auth/login", {
            "email": self.cfg["email"], "password": self.cfg["password"]})
        if status not in (200, 201) or not isinstance(data, dict):
            return False
        self.token = data.get("token")
        emp = (data.get("user", {}) or {}).get("employee") or {}
        self.organization_id = emp.get("organizationId")
        self.tenant_id = emp.get("tenantId") or (data.get("user", {}) or {}).get("tenantId")
        return bool(self.token)

    def _scoped_query(self, extra=""):
        """Gauzy's list endpoints take bracket-style query params
        (`where[tenantId]=…`), NOT the older `?data={json}` wrapper — that form
        is rejected with "where should not be empty". The scope is mandatory:
        omitting it is a 400, not an unfiltered list."""
        q = (f"where[organizationId]={urllib.parse.quote(str(self.organization_id))}"
             f"&where[tenantId]={urllib.parse.quote(str(self.tenant_id))}")
        return q + extra

    def role_of(self, bearer):
        """The Gauzy role name behind a caller's token, or None.

        The token is verified by ASKING GAUZY, not by decoding the JWT locally.
        A local decode would only prove the token is well-formed — this app has
        no way to check Gauzy's signing key, and a revoked or expired session
        would still parse cleanly. Handing the token straight back to the issuer
        is the only check that actually means anything here.

        The `role` relation must be requested explicitly; without it Gauzy
        returns a bare roleId and the name comes back empty."""
        if not bearer:
            return None
        req = urllib.request.Request(
            self.cfg["server_url"].rstrip("/") + "/api/user/me?relations[0]=role",
            headers={"Authorization": f"Bearer {bearer}",
                     "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace") or "{}")
        except Exception:
            return None
        return ((data.get("role") or {}).get("name")) or None

    def employees(self):
        """Employees as [(id, label)]. The `user` relation is requested
        explicitly because Gauzy returns bare ids otherwise, and a list of
        UUIDs is not something an admin can pick from."""
        if not self.token and not self.login():
            return []
        status, data = self._request(
            "GET", f"/api/employee?{self._scoped_query('&relations[0]=user')}")
        if status not in (200, 201):
            return []
        items = data.get("items", data if isinstance(data, list) else [])
        out = []
        for e in items or []:
            user = e.get("user") or {}
            label = (user.get("name")
                     or " ".join(filter(None, [user.get("firstName"), user.get("lastName")]))
                     or user.get("email") or e.get("id", "")[:8])
            out.append((e.get("id"), label))
        return [(i, l) for i, l in out if i]

    def departments(self):
        if not self.token and not self.login():
            return []
        status, data = self._request(
            "GET", f"/api/organization-department?{self._scoped_query()}")
        if status not in (200, 201):
            return []
        items = data.get("items", data if isinstance(data, list) else [])
        return [(d.get("id"), d.get("name") or "(unnamed)") for d in items or [] if d.get("id")]


# --------------------------------------------------------------------------- #
# HTML
#
# Server-rendered forms, no JavaScript. The whole app is a handful of settings
# an admin changes rarely; a build step and a framework would cost more than
# they return here.
# --------------------------------------------------------------------------- #

CSS = """
body{font:15px/1.5 system-ui,sans-serif;margin:0;background:#f6f7f9;color:#1a1a1a}
header{background:#222b45;color:#fff;padding:14px 22px}
header h1{margin:0;font-size:17px;font-weight:600}
nav{background:#fff;border-bottom:1px solid #dfe3e8;padding:0 22px}
nav a{display:inline-block;padding:11px 14px;color:#444;text-decoration:none}
nav a.on{border-bottom:2px solid #3366ff;color:#3366ff;font-weight:600}
main{padding:22px;max-width:960px}
table{border-collapse:collapse;width:100%;background:#fff;border:1px solid #dfe3e8}
th,td{padding:9px 11px;border-bottom:1px solid #eef0f3;text-align:left}
th{background:#fafbfc;font-size:13px;color:#555}
input,select{padding:6px 8px;border:1px solid #cfd4dc;border-radius:4px;font:inherit}
button{padding:7px 15px;background:#3366ff;color:#fff;border:0;border-radius:4px;
       font:inherit;cursor:pointer}
.note{background:#fff8e1;border:1px solid #ffe082;padding:11px 13px;border-radius:4px;
      margin-bottom:16px;font-size:14px}
.ok{background:#e8f5e9;border:1px solid #a5d6a7;padding:10px 13px;border-radius:4px;
    margin-bottom:16px;font-size:14px}
.muted{color:#777;font-size:13px}
"""


def page(title, body, active=""):
    tabs = [("/", "Employees"), ("/departments", "Departments"), ("/apps", "Apps")]
    nav = "".join(
        f'<a href="{h}" class="{"on" if h == active else ""}">{escape(t)}</a>'
        for h, t in tabs)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>{escape(title)} — System-Tracker admin</title><style>{CSS}</style></head>
<body><header><h1>System-Tracker — admin settings</h1></header>
<nav>{nav}</nav><main>{body}</main></body></html>""".encode("utf-8")


# --------------------------------------------------------------------------- #
# Handler
# --------------------------------------------------------------------------- #

class Handler(http.server.BaseHTTPRequestHandler):
    cfg = None
    gauzy = None

    def log_message(self, fmt, *args):
        pass                       # quiet; systemd journal carries what matters

    # ---- helpers ----
    def _send(self, body, status=200, ctype="text/html; charset=utf-8"):
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(json.dumps(obj).encode(), status, "application/json")

    def _deny(self, path):
        """403 for API callers, a readable page for a browser that wandered in.

        Says plainly that this lives under the dashboard now, because the most
        likely visitor is an admin who bookmarked the old standalone URL."""
        if path.startswith("/api/"):
            return self._json({"error": "super admin required"}, 403)
        return self._send(page("Not authorised", """
<h2>Not authorised</h2>
<p>These settings are part of the Gauzy dashboard now. Open
<b>Settings &rarr; Tracker Settings</b> there and sign in as a super admin.</p>
<p class="muted">This page is reached directly, without a Gauzy session, so it
cannot confirm who you are.</p>"""), 403)

    def _form(self):
        """POST body as a flat dict, whether it arrived as a browser form or as
        JSON from the Angular page. Accepting both keeps the standalone HTML
        forms working as a fallback for when the dashboard is unavailable —
        which is exactly when an admin may need to turn screenshots off."""
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode("utf-8", "replace")
        if "json" in (self.headers.get("Content-Type") or "").lower():
            try:
                data = json.loads(raw or "{}")
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}
        return {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}

    # ---- authorisation ----
    #
    # Enforced HERE, server-side, not by hiding a menu entry. Gauzy can decline
    # to show the link, but that only shapes the UI — anything reachable on the
    # port would still answer. Since these settings decide whether a colleague
    # is screenshotted, "you cannot see the button" is not an access control.
    #
    # `/api/settings` is deliberately exempt: the TRACKER reads it, as a daemon
    # with no interactive Gauzy session to present. It exposes one employee's
    # two harmless preferences and changes nothing, whereas every write and the
    # employee roster behind the admin views require SUPER_ADMIN.

    ANON_PATHS = ("/api/settings",)

    def _bearer(self):
        h = self.headers.get("Authorization") or ""
        return h[7:].strip() if h.lower().startswith("bearer ") else ""

    def _authorised(self, path):
        if path in self.ANON_PATHS:
            return True
        if not self.cfg.get("require_super_admin", True):
            return True
        return self.gauzy.role_of(self._bearer()) == "SUPER_ADMIN"

    def _cors(self):
        """The dashboard is served from another origin (:4200 vs :8600), so the
        browser preflights every authenticated call. Echoing a configured origin
        rather than `*` matters: `*` is incompatible with credentialed requests
        and would invite any page on this machine to call the API."""
        origin = self.cfg.get("allow_origin") or ""
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    # ---- routing ----
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(url.query)
        route = {
            "/api/settings": self.api_settings,
            "/api/categories": self.api_categories,
            "/api/admin/state": self.api_state,
            "/": self.view_employees,
            "/departments": self.view_departments,
            "/apps": self.view_apps,
        }.get(url.path)
        if not route:
            return self._send(b"not found", 404, "text/plain")
        if not self._authorised(url.path):
            return self._deny(url.path)
        return route(qs)

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        form = self._form()
        route = {
            "/save-employee": self.save_employee,
            "/save-app": self.save_app,
            "/delete-app": self.delete_app,
            "/api/admin/employee": self.api_save_employee,
            "/api/admin/app": self.api_save_app,
            "/api/admin/app-delete": self.api_delete_app,
        }.get(url.path)
        if not route:
            return self._send(b"not found", 404, "text/plain")
        if not self._authorised(url.path):
            return self._deny(url.path)
        return route(form)

    def _redirect(self, to):
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    # ---- API: what the tracker reads ----
    def api_settings(self, qs):
        """The endpoint `settings_url` in the tracker config points at.

        Returns ONLY keys the admin has actually set. An unset value is omitted
        rather than sent as null or as a guessed default, because the tracker
        treats a present key as an override — sending defaults from here would
        quietly overrule every machine's config.json."""
        emp = (qs.get("employeeId") or [""])[0]
        if not emp:
            return self._json({"error": "employeeId required"}, 400)
        conn = db(self.cfg)
        row = conn.execute(
            "SELECT screenshot_interval_seconds, count_audio_as_active "
            "FROM employee_settings WHERE employee_id=?", (emp,)).fetchone()
        conn.close()
        out = {}
        if row:
            if row["screenshot_interval_seconds"] is not None:
                out["screenshot_interval_seconds"] = int(row["screenshot_interval_seconds"])
            if row["count_audio_as_active"] is not None:
                out["count_audio_as_active"] = bool(row["count_audio_as_active"])
        return self._json(out)

    def api_categories(self, qs):
        """Process-name -> category for an employee's department.

        Consumed at REPORT time, never at capture time. Categories are a
        reporting lens, so re-classifying an app or moving someone between
        departments must correct history too — which only works if the captured
        rows never carried a category in the first place."""
        emp = (qs.get("employeeId") or [""])[0]
        conn = db(self.cfg)
        dept = None
        if emp:
            row = conn.execute("SELECT department_id FROM employee_settings "
                               "WHERE employee_id=?", (emp,)).fetchone()
            dept = row["department_id"] if row else None
        dept = dept or (qs.get("departmentId") or [""])[0]
        if not dept:
            conn.close()
            return self._json({"default": self.cfg["default_category"], "apps": {}})
        rows = conn.execute("SELECT app_name, category FROM app_category "
                            "WHERE department_id=?", (dept,)).fetchall()
        conn.close()
        return self._json({"departmentId": dept,
                           "default": self.cfg["default_category"],
                           "apps": {r["app_name"]: r["category"] for r in rows}})

    # ---- JSON API for the Gauzy dashboard page ----
    #
    # One state call rather than three. The dashboard page needs employees,
    # their overrides and the department list together before it can render a
    # single row, so splitting them would only add round trips and a half-drawn
    # table.

    def api_state(self, qs):
        conn = db(self.cfg)
        saved = {r["employee_id"]: r for r in
                 conn.execute("SELECT * FROM employee_settings").fetchall()}
        conn.close()
        employees = []
        for eid, label in self.gauzy.employees():
            s = saved.get(eid)
            employees.append({
                "id": eid,
                "label": label,
                "screenshot_interval_seconds":
                    None if not s or s["screenshot_interval_seconds"] is None
                    else int(s["screenshot_interval_seconds"]),
                # Only ever false or null. True is never stored — see the note
                # in save_employee about not overruling a machine's own config.
                "count_audio_as_active":
                    False if (s and s["count_audio_as_active"] == 0) else None,
                "department_id": (s["department_id"] if s else None) or "",
            })
        return self._json({
            "employees": employees,
            "departments": [{"id": d, "name": n} for d, n in self.gauzy.departments()],
        })

    def api_save_employee(self, form):
        eid = form.get("employee_id") or ""
        if not eid:
            return self._json({"error": "employee_id required"}, 400)
        iv = form.get("screenshot_interval_seconds")
        media = form.get("count_audio_as_active")
        conn = db(self.cfg)
        conn.execute(
            "INSERT INTO employee_settings"
            " (employee_id, screenshot_interval_seconds, count_audio_as_active, department_id)"
            " VALUES (?,?,?,?)"
            " ON CONFLICT(employee_id) DO UPDATE SET"
            "  screenshot_interval_seconds=excluded.screenshot_interval_seconds,"
            "  count_audio_as_active=excluded.count_audio_as_active,"
            "  department_id=excluded.department_id",
            (eid,
             int(iv) if isinstance(iv, (int, float)) or (isinstance(iv, str) and iv.isdigit()) else None,
             0 if media is False else None,
             form.get("department_id") or None))
        conn.commit()
        conn.close()
        return self._json({"ok": True})

    def api_save_app(self, form):
        dept = form.get("department_id") or ""
        app = (form.get("app_name") or "").strip().lower()
        cat = form.get("category") if form.get("category") in CATEGORIES else "Neutral"
        if not (dept and app):
            return self._json({"error": "department_id and app_name required"}, 400)
        conn = db(self.cfg)
        conn.execute("INSERT INTO app_category (department_id, app_name, category)"
                     " VALUES (?,?,?) ON CONFLICT(department_id, app_name)"
                     " DO UPDATE SET category=excluded.category", (dept, app, cat))
        conn.commit()
        conn.close()
        return self._json({"ok": True})

    def api_delete_app(self, form):
        conn = db(self.cfg)
        conn.execute("DELETE FROM app_category WHERE department_id=? AND app_name=?",
                     (form.get("department_id") or "", form.get("app_name") or ""))
        conn.commit()
        conn.close()
        return self._json({"ok": True})

    # ---- views ----
    def view_employees(self, qs):
        conn = db(self.cfg)
        saved = {r["employee_id"]: r for r in
                 conn.execute("SELECT * FROM employee_settings").fetchall()}
        conn.close()
        emps = self.gauzy.employees()
        depts = self.gauzy.departments()
        banner = ""
        if not emps:
            banner = ('<div class="note">Could not read employees from Gauzy at '
                      f'{escape(self.cfg["server_url"])}. Check it is running and '
                      'that the credentials in the config are an employee account.</div>')
        if qs.get("saved"):
            banner += '<div class="ok">Saved. The tracker picks this up within 60 seconds.</div>'
        rows = []
        for eid, label in emps:
            s = saved.get(eid)
            iv = "" if not s or s["screenshot_interval_seconds"] is None else s["screenshot_interval_seconds"]
            media_idle = bool(s and s["count_audio_as_active"] == 0)
            dsel = (s["department_id"] if s else "") or ""
            dopts = '<option value="">—</option>' + "".join(
                f'<option value="{escape(d)}"{" selected" if d == dsel else ""}>{escape(n)}</option>'
                for d, n in depts)
            rows.append(f"""<tr><form method="post" action="/save-employee">
<input type="hidden" name="employee_id" value="{escape(eid)}">
<td>{escape(label)}<div class="muted">{escape(eid[:8])}</div></td>
<td><select name="interval">
  <option value=""{"" if iv else " selected"}>default</option>
  {"".join(f'<option value="{v}"{" selected" if str(iv)==str(v) else ""}>{v//60} min</option>' for v in (60,180,300,600))}
</select></td>
<td><input type="checkbox" name="media_idle" value="1"{" checked" if media_idle else ""}></td>
<td><select name="department_id">{dopts}</select></td>
<td><button>Save</button></td></form></tr>""")
        body = banner + f"""<h2>Per-employee settings</h2>
<p class="muted">The tracker reads these live — no restart. Blank means the
machine's own config decides.</p>
<table><tr><th>Employee</th><th>Screenshot every</th>
<th>Media counts as idle</th><th>Department</th><th></th></tr>
{"".join(rows) or '<tr><td colspan="5" class="muted">No employees.</td></tr>'}</table>"""
        return self._send(page("Employees", body, "/"))

    def view_departments(self, qs):
        depts = self.gauzy.departments()
        rows = "".join(f"<tr><td>{escape(n)}</td><td class='muted'>{escape(d[:8])}</td>"
                       f"<td><a href='/apps?departmentId={escape(d)}'>Edit apps</a></td></tr>"
                       for d, n in depts)
        body = f"""<h2>Departments</h2>
<div class="note">Departments live in Gauzy, not here — add or rename them under
<b>Organization → Departments</b> and they appear in this list. Keeping one
source of truth avoids two lists of departments drifting apart.</div>
<table><tr><th>Name</th><th>Id</th><th></th></tr>
{rows or '<tr><td colspan="3" class="muted">None yet.</td></tr>'}</table>"""
        return self._send(page("Departments", body, "/departments"))

    def view_apps(self, qs):
        depts = self.gauzy.departments()
        dept = (qs.get("departmentId") or [""])[0] or (depts[0][0] if depts else "")
        conn = db(self.cfg)
        rows = conn.execute("SELECT app_name, category FROM app_category "
                            "WHERE department_id=? ORDER BY app_name", (dept,)).fetchall()
        conn.close()
        picker = "".join(f'<option value="{escape(d)}"{" selected" if d==dept else ""}>'
                         f'{escape(n)}</option>' for d, n in depts)
        listed = "".join(f"""<tr><form method="post" action="/save-app">
<input type="hidden" name="department_id" value="{escape(dept)}">
<input type="hidden" name="app_name" value="{escape(r['app_name'])}">
<td>{escape(r['app_name'])}</td>
<td><select name="category">{"".join(
    f'<option{" selected" if r["category"]==c else ""}>{c}</option>' for c in CATEGORIES)}</select></td>
<td><button>Save</button></form>
<form method="post" action="/delete-app" style="display:inline">
<input type="hidden" name="department_id" value="{escape(dept)}">
<input type="hidden" name="app_name" value="{escape(r['app_name'])}">
<button style="background:#b71c1c">Remove</button></form></td></tr>""" for r in rows)
        body = f"""<h2>App productivity, per department</h2>
<div class="note">Apps are matched on <b>process name</b> (what the tracker
reports: <code>chrome</code>, <code>code</code>, <code>postgres</code>).
The same app can be Productive in one department and Unproductive in another.
Anything unclassified counts as <b>{escape(self.cfg['default_category'])}</b>.</div>
<form method="get"><select name="departmentId">{picker}</select>
<button>Show</button></form>
<table style="margin-top:14px"><tr><th>Process name</th><th>Category</th><th></th></tr>
{listed or '<tr><td colspan="3" class="muted">Nothing classified yet.</td></tr>'}
<tr><form method="post" action="/save-app">
<input type="hidden" name="department_id" value="{escape(dept)}">
<td><input name="app_name" placeholder="e.g. spotify" required></td>
<td><select name="category">{"".join(f"<option>{c}</option>" for c in CATEGORIES)}</select></td>
<td><button>Add</button></td></form></tr></table>"""
        return self._send(page("Apps", body, "/apps"))

    # ---- writes ----
    def save_employee(self, form):
        eid = form.get("employee_id", "")
        if not eid:
            return self._redirect("/")
        iv = form.get("interval") or ""
        conn = db(self.cfg)
        conn.execute(
            "INSERT INTO employee_settings"
            " (employee_id, screenshot_interval_seconds, count_audio_as_active, department_id)"
            " VALUES (?,?,?,?)"
            " ON CONFLICT(employee_id) DO UPDATE SET"
            "  screenshot_interval_seconds=excluded.screenshot_interval_seconds,"
            "  count_audio_as_active=excluded.count_audio_as_active,"
            "  department_id=excluded.department_id",
            (eid,
             int(iv) if iv.isdigit() else None,
             # Unchecked means "no opinion" (NULL), not "media is active" (1).
             # Storing 1 here would override a machine that deliberately set
             # count_audio_as_active false in its own config.
             0 if form.get("media_idle") else None,
             form.get("department_id") or None))
        conn.commit()
        conn.close()
        return self._redirect("/?saved=1")

    def save_app(self, form):
        dept, app = form.get("department_id", ""), (form.get("app_name") or "").strip().lower()
        cat = form.get("category") if form.get("category") in CATEGORIES else "Neutral"
        if dept and app:
            conn = db(self.cfg)
            conn.execute("INSERT INTO app_category (department_id, app_name, category)"
                         " VALUES (?,?,?) ON CONFLICT(department_id, app_name)"
                         " DO UPDATE SET category=excluded.category", (dept, app, cat))
            conn.commit()
            conn.close()
        return self._redirect(f"/apps?departmentId={urllib.parse.quote(dept)}")

    def delete_app(self, form):
        dept, app = form.get("department_id", ""), form.get("app_name", "")
        conn = db(self.cfg)
        conn.execute("DELETE FROM app_category WHERE department_id=? AND app_name=?",
                     (dept, app))
        conn.commit()
        conn.close()
        return self._redirect(f"/apps?departmentId={urllib.parse.quote(dept)}")


def main():
    cfg = load_config(sys.argv[1] if len(sys.argv) > 1 else
                      os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "config.json"))
    conn = db(cfg)
    conn.close()
    Handler.cfg = cfg
    Handler.gauzy = Gauzy(cfg)
    Handler.gauzy.login()
    srv = http.server.ThreadingHTTPServer((cfg["bind_host"], cfg["bind_port"]), Handler)
    print(f"admin settings on http://{cfg['bind_host']}:{cfg['bind_port']}  "
          f"db={cfg['db_path']}", flush=True)
    print(f"tracker settings_url -> http://{cfg['bind_host']}:{cfg['bind_port']}/api/settings",
          flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
