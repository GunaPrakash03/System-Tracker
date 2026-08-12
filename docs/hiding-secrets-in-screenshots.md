# Hiding passwords and OTPs in screenshots

Whether a screenshot can be made to omit a password or a one-time code, what is
actually achievable on this stack, and what is not. Findings are from testing on
`sys0041`, not from documentation.

## First, a correction worth making

**Passwords are usually not in the screenshot to begin with.** A password field
renders as dots. Capturing the screen captures the dots, not the characters. The
same is true of `sudo` and `ssh` prompts, which echo nothing at all.

So the risk is narrower and more specific than "passwords":

| Genuinely at risk | Why |
|---|---|
| **OTP / 2FA codes** | Displayed as plain text — an authenticator app, an SMS notification, an email preview |
| **Revealed passwords** | A password manager with the eye icon clicked, or a "show password" checkbox |
| **Secrets in a terminal** | An API token echoed by a command, a `.env` printed with `cat`, a connection string in a prompt |
| **Secrets in an editor** | A config file with credentials open in the editor |
| **Tokens in a URL** | A reset link or signed URL in the address bar |

Most of these are text on screen with nothing marking them as secret, which is
what makes automatic redaction hard.

## What is possible today, with no new dependencies

### 1. Blur the whole screen — already implemented

`blur_screenshots`, set per employee from Tracker Settings. Applied on the
workstation before the image leaves it, so a readable screen is never
transmitted or stored. It is a downscale-to-1/20-then-stretch, which is
irreversible: the detail is gone from the file, not merely obscured.

This is the only mechanism available today that reliably hides a secret,
because it does not need to know where the secret is. It costs the detail of
the record — you can see which window and roughly what shape of work, not what
was being done.

Combined with the 800px scaling now in place, a blurred capture is about 12 KB.

### 2. Skip capture for named windows — implementable, not yet built

The tracker already knows every window's `wm_class` and title
(`list_windows()`, `proc_tracker.py:556`), and on X11 it sees all of them, not
just the focused one. A denylist could suppress the capture entirely for that
interval:

```json
"screenshot_skip_windows": [
  "bitwarden", "keepass", "1password", "seahorse",
  "polkit-gnome-authentication-agent",
  "(?i)sign in", "(?i)log in", "(?i)verification code"
]
```

Match on class or title; if anything matches, take no screenshot for that slot.
The time slot itself is unaffected — activity is still recorded, only the image
is skipped.

**Its limits should be stated plainly.** A login page titled "Home" will not
match. An OTP arriving as a desktop notification is drawn by `gnome-shell`, not
by a window of its own, so it cannot be matched at all. This reduces exposure
for predictable cases; it does not remove it.

### 3. A pause switch — implementable, and probably the most honest control

Let the person about to handle a secret suppress capture for a few minutes:

```bash
touch ~/.local/share/system-tracker/pause-screenshots
```

The tracker checks for the file each interval, skips the capture while it
exists, and removes it after a configured timeout so it cannot be left on
forever. Activity tracking continues throughout, so the pause cannot be used to
hide time — only to hide the image.

This is worth preferring over cleverer schemes because it is *predictable*. The
employee knows exactly when capture is off, and the record shows that a pause
happened rather than silently containing a gap.

## What is not possible here

### Detecting password fields automatically

This is the approach that sounds right and does not work on this stack.

AT-SPI, the Linux accessibility API, is the only interface that knows a widget
is a password field — `Atspi.Role.PASSWORD_TEXT` exists precisely for this. It
is installed here and functional: 23 applications were visible on the
accessibility bus during testing.

But look at *which* applications:

```
gnome-shell, gsd-color, gsd-keyboard, gsd-wacom, gsd-media-keys,
ibus-extension-gtk3, gsd-power, evolution-alarm-notify, xpad,
xdg-desktop-portal-gtk, gjs, gsd-xsettings
```

GNOME system components only. **No Chrome, no editor, no terminal.** Chromium
and Electron expose their internals to AT-SPI only when accessibility is forced
on at launch (`--force-renderer-accessibility`), which carries a real
performance cost and has to be applied to every browser start. `toolkit-accessibility`
is also `false` on this desktop.

Since nearly every OTP and most password entry happens in a browser, an AT-SPI
approach would miss the actual risk while adding a heavyweight dependency. It
*would* detect GNOME's own authentication dialogs, which are on the bus — but
those already mask their input, so there is nothing to protect.

### OCR the screenshot and blank out anything secret-looking

Needs Tesseract or similar — outside the stdlib-only rule for `tracker/`, slow
enough to matter at one capture a minute, and unreliable on the exact strings
that matter. A six-digit code is indistinguishable from any other six digits.
The process would also have to read every secret in order to redact it, which
moves the risk rather than removing it.

### Redact a fixed region

Blanking, say, the top-right corner where notifications appear is fragile in
both directions: it hides real work, and it misses the same notification on a
different monitor layout.

## Recommendation

In order of effort:

1. **Turn blurring on for anyone who handles credentials as part of their job.**
   It exists, it works, and it is the only complete answer. The cost is a less
   detailed record for those people.
2. **Add the pause switch.** Small, predictable, and it covers the cases a
   denylist cannot — including OTP notifications.
3. **Add the window denylist** if there are specific applications (a password
   manager, a banking portal) that recur. Treat it as reducing exposure, never
   as a guarantee.
4. **Do not pursue AT-SPI field detection** unless browsers are brought onto the
   accessibility bus, at which point the trade-off should be re-examined.

And one thing that costs nothing: the screenshot interval is already a dashboard
setting. Capturing every five minutes rather than every minute reduces the
chance of catching a transient OTP by roughly five times, and cuts storage in
the same proportion.

## A note on what this is for

If the concern is that stored screenshots could leak credentials, the mitigation
is above. If the concern is that employees are uncomfortable being screenshotted
while handling personal accounts, blurring addresses the appearance but not the
feeling; a pause switch does address it, because it hands them the control. That
is a policy decision rather than a technical one, and worth taking deliberately.
