// System-Tracker Silent Screenshot — GNOME Shell extension.
//
// Why this exists: on a Wayland session the only sanctioned screenshot route
// for an ordinary process is xdg-desktop-portal, and GNOME's portal ALWAYS
// draws a white flash (it calls org.gnome.Shell.Screenshot with flash=true).
// The direct Screenshot D-Bus API — which takes a flash=false argument — is
// refused to unsandboxed callers ("Screenshot is not allowed"). Code running
// INSIDE gnome-shell has neither limit: Shell.Screenshot.screenshot() writes a
// PNG with no flash, no sound, and no notification. That is exactly how
// commercial trackers (DeskTime, Hubstaff) capture silently on Wayland.
//
// This extension does one thing: expose a D-Bus method the tracker calls once
// per interval to write a full-screen PNG to a path it names.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';

const IFACE = `
<node>
  <interface name="org.gnome.Shell.Extensions.SystemTrackerShot">
    <method name="CaptureToFile">
      <arg type="s" direction="in"  name="path"/>
      <arg type="b" direction="out" name="success"/>
    </method>
  </interface>
</node>`;

const OBJECT_PATH = '/org/gnome/Shell/Extensions/SystemTrackerShot';

export default class SystemTrackerShotExtension extends Extension {
    enable() {
        this._shooter = new Shell.Screenshot();
        this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._dbus.export(Gio.DBus.session, OBJECT_PATH);
    }

    disable() {
        this._dbus?.unexport();
        this._dbus = null;
        this._shooter = null;
    }

    // Async D-Bus handler: DBusExportedObject dispatches "CaptureToFile" to
    // "CaptureToFileAsync" when this shape (params array + invocation) exists,
    // so the reply is sent only after the capture actually finishes.
    CaptureToFileAsync([path], invocation) {
        const reply = (ok) => invocation.return_value(new GLib.Variant('(b)', [ok]));

        let stream;
        try {
            stream = Gio.File.new_for_path(path).replace(
                null, false, Gio.FileCreateFlags.NONE, null);
        } catch (e) {
            reply(false);
            return;
        }

        // include_cursor = false. No flash is drawn: the flash is a UI-layer
        // effect (screenshot.js _flashAsync), not part of Shell.Screenshot.
        this._shooter.screenshot(false, stream, (obj, res) => {
            let ok = false;
            try {
                obj.screenshot_finish(res);
                ok = true;
            } catch (e) {
                ok = false;
            }
            try { stream.close(null); } catch (e) { /* best effort */ }
            reply(ok);
        });
    }
}
