# Browser URL capture — proposal

**Status:** awaiting approval. Nothing below is built. This documents what the
work is, what it costs and what it exposes, so the decision is made with the
trade-offs visible rather than discovered during rollout.

**Requested:** reports should show the actual address —
`https://hrportal.youngglobes.com/leave/apply` — not just the page title.

---

## 1. Why the tracker cannot already do this

Settled, and worth restating because it is the whole reason an extension is
needed at all: **the operating system does not know the URL.** A browser window
is one window to the OS; the tab, its address and its history live inside the
browser process. `xprop` returns the window title and nothing else, and no
window property has ever carried a URL.

So today the tracker records the page **title**, which is genuinely useful —

| Recorded today | The URL behind it |
|---|---|
| `HR Portal - Young Globes` | `https://hrportal.youngglobes.com/...` |
| `Sent - Zoho Mail (gunaprakash@youngglobes.com)` | `https://mail.zoho.com/...` |
| `* general (Channel) - Young Globes - Slack` | `https://app.slack.com/client/...` |
| `Meet - yvu-eeeu-wkt` | `https://meet.google.com/yvu-eeeu-wkt` |

— but the domain cannot be derived from it. Chrome titles are
`Page title - Google Chrome`; the hostname appears nowhere. Anything that
reports a real URL has to read it from **inside the browser**.

---

## 2. Proposed architecture

```
Chrome extension  ──POST──▶  tracker (127.0.0.1)  ──▶  Gauzy API  ──▶  reports
```

**The extension does not talk to Gauzy.** It reports the active tab to a local
endpoint on the tracker, and the tracker forwards it using credentials it
already holds.

That indirection is the important design decision. The alternative — the
extension posting to Gauzy directly — would require Gauzy API credentials
inside a browser extension, where any employee can open the developer tools and
read them. Those are the same credentials that can read every employee's
tracked data. Keeping them in the tracker means the browser holds nothing
sensitive, and it also means URL activity buffers through the tracker's existing
retry path rather than being lost whenever Gauzy is briefly unreachable.

The receiving end is small: Gauzy already accepts `type: "URL"` activities and
the tracker already posts them. Only the *source* of the string changes.

---

## 3. Automatic installation

Asked directly: can this install itself with the tracker, with no per-machine
clicking? **For Chrome, yes. For Firefox on this fleet, no.**

### Chrome — fully automatic

A managed-policy file force-installs the extension at the next browser launch:

```
/etc/opt/chrome/policies/managed/system-tracker.json
{ "ExtensionInstallForcelist": ["<extension-id>;https://<host>/updates.xml"] }
```

Force-installed means the employee cannot disable or remove it, and nobody has
to click anything. `packaging/install.sh` writes that file.

Two consequences:

- **It needs root.** `install.sh` deliberately refuses to run as root today, so
  this becomes a separate `sudo` step rather than being folded into the existing
  installer.
- **The extension must be hosted.** Either an unlisted Chrome Web Store listing,
  or a self-hosted `.crx` plus an update XML that every workstation can reach.
  Self-hosting also requires pinning the extension ID with a key, or the ID
  changes on every build and the policy stops matching.

### Firefox — blocked on two things, both external

`/etc/firefox/policies/policies.json` with `force_installed` is the equivalent
mechanism, but on this fleet:

- **Firefox is installed as a snap.** Confinement means the extension has to be
  served over `https://`; a local file path outside the snap is not readable.
- **Mozilla must sign the XPI.** Release Firefox refuses unsigned extensions
  even under policy. Signing goes through AMO — an unlisted submission keeps it
  private, but it is an external review with its own turnaround, and not
  something an installer can perform.

### Edge

Same mechanism as Chrome (`/etc/opt/edge/policies/managed/`). Not installed on
the current target machine, so out of scope until it is.

---

## 4. What this exposes — read before approving

**The extension is visible and cannot be hidden.** Chrome lists force-installed
extensions in `chrome://extensions` marked *"Installed by your administrator"*,
and removal is blocked rather than concealed. Employees will see it. This is not
a limitation to engineer around — attempting to hide monitoring software is
exactly what turns a defensible policy into a liability, and many jurisdictions
require workplace monitoring to be disclosed regardless.

**URLs are materially more sensitive than titles.** A title says
`Sent - Zoho Mail`. A full URL can carry document identifiers, customer
references, search terms, session tokens and password-reset links in the query
string. The decision below about query strings is therefore not cosmetic.

---

## 5. Decisions needed before implementation

| # | Decision | Options | Recommendation |
|---|---|---|---|
| 1 | Hosting for the update XML | Chrome Web Store (unlisted) · self-host on the Gauzy box | **Self-host** — workstations already reach that box on :3000; no store account or review |
| 2 | Query strings | Store full URL · strip `?...` and keep path · domain + path only | **Strip query strings.** They are where tokens and personal data live, and they are almost never what a productivity report needs |
| 3 | Scope of capture | Active tab only · every open tab | **Active tab only** — matches what is recorded today, and "every tab" records pages nobody is looking at |
| 4 | Private / incognito windows | Excluded · included via policy | **Excluded** (the browser default) |
| 5 | Browsers in scope | Chrome only · Chrome + Firefox | **Chrome first**; Firefox is blocked on AMO signing and can follow |
| 6 | Retention | Same as existing activity data · shorter for URLs | Worth an explicit answer given point 4 above |

---

## 6. Effort

| Piece | Size | Notes |
|---|---|---|
| Chrome extension (MV3, active-tab URL) | Small | ~100 lines; no libraries |
| Local receive endpoint in the tracker | Small | Stdlib `http.server`, bound to 127.0.0.1 |
| Posting as Gauzy `URL` activities | Small | The path already exists and works |
| `.crx` packaging, stable ID, update XML | Medium | The fiddly part |
| Hosting the update XML | Small | Depends on decision 1 |
| Policy file + `sudo` step in the installer | Small | Changes the install model slightly |
| Firefox port + AMO signing | Medium | Blocked externally; not day one |

No new runtime dependency on the tracker side — the receiver is stdlib
`http.server`, the same constraint the rest of the tracker holds to.

---

## 7. What this does not change

- Background tabs stay unreported under the recommendation in decision 3.
- Nothing about screenshots, idle detection or process tracking.
- The tracker keeps recording page titles; URLs are additional, not a
  replacement, so reports degrade gracefully to titles on any machine or browser
  where the extension is absent.

---

## 8. Approval

Answer the six decisions in §5 — decisions 1 and 2 are the ones that change the
build. Once they are settled this becomes an implementation plan rather than a
proposal.
