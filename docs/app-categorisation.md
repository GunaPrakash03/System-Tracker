# How applications are categorised

Every figure on the Productivity page and the App categories tab comes from one
mapping: **process name → Productive | Neutral | Unproductive**, held per
department in **Settings → Tracker settings**. This document is what that
mapping means, because the obvious reading of it is wrong in one important way.

## The two shapes the tracker publishes

The tracker publishes a daily summary onto the employee's own settings record.
Two parts of it matter here, and they are keyed differently:

| Field | Keyed by | Example keys |
|---|---|---|
| `usage.apps` | **process name** | `chrome`, `code`, `spotify`, `gnome-terminal-server` |
| `usage.hours[HH].focus` | **window title** | `YouTube`, `HR Portal - Young Globes`, `gnome-terminal-server` |

`focus` is the one that drives categorisation, because it is the only place a
browser can be split at all: a process called `chrome` says nothing about
whether the person was reading a ticket or watching a video. Note that `focus`
mixes the two shapes — a non-browser window arrives under its process name, a
browser tab arrives under its page title.

## Matching

1. **Exact match** on the lowercased name wins.
2. Otherwise the **longest entry contained in the name** wins. This is why
   `terminal` classifies `gnome-terminal-server`, and why classifying `codex`
   explicitly beats the accidental `code` hit inside it.
3. **Unmatched browser tabs inherit the browser's own category.**
4. Anything still unmatched is **unclassified** — it counts towards no category.

Rule 3 is the one worth understanding.

## Why browsers work by exception

The mapping is written against process names, so `chrome: Productive` looks like
it classifies the browser. It does not, on its own: a browser's time arrives
keyed by *page title*, and a title almost never contains the word "chrome". Left
there, every unlisted page fell through to Neutral, and the `chrome` entry
classified nothing it was meant to.

That failure was invisible for a long time because the *listed* pages matched on
their own — `youtube`, `zoho mail`, `yg portal` — so the list looked like it was
working. What exposed it was the rebrand: the dashboard's title changed from
"Gauzy" to "Young Globes Workspace", the `gauzy` entry stopped matching, and
roughly a quarter of the day moved from Productive to Neutral overnight with no
setting changed by anyone.

So an unmatched browser tab now takes the browser's category. In practice:

```
chrome:   Productive     <- the default for every tab
youtube:  Neutral        <- exception
spotify:  Unproductive   <- exception
```

Reading: *everything in Chrome is productive except YouTube, which is neutral,
and Spotify, which is unproductive.* You list the exceptions, not every site.

## Unclassified is not a category

An application that matches nothing — and is not a browser tab — is left
unclassified. It appears in its own grey group on the **App categories** tab and
counts towards none of the three shares.

This is deliberate. Unmatched apps used to default to Neutral, which made
Neutral a dumping ground: genuinely-neutral applications and never-classified
ones summed into a single figure, so the gaps in a department's list were
invisible and Neutral always looked larger than it should. Grey says "nobody has
decided about this yet", which is a different statement from "this is neutral
work" and should not be confused with it.

## Where each page gets its numbers

| Page | Shows | Audience |
|---|---|---|
| **Productivity** | how much of the day was productive / neutral / unproductive / idle | the employee, and admins and managers |
| **App categories** | which applications earned that time, grouped by app within each category | admins and managers only (`ORG_EMPLOYEES_VIEW`) |

Both classify with the same rule and the same fallback, so their totals agree —
the difference between them is whatever lands in Unclassified, which the
Productivity page does not draw.

## Two things that surprise people

**The report trails by up to five minutes.** Time slots and screenshots post
every 60 seconds, but the usage summary these pages read is published every
fifth cycle (`proc_tracker.py`, `if cycle % 5 == 0`). The lower frequency
narrows the window in which the tracker's read-merge-write could overwrite an
admin's save to the same record. Refreshing sooner than that shows the previous
snapshot: the page is current, the data is not yet.

**Each browser tab is its own entry.** A video is recorded under its full title
— "This AI Voice Agent BOOKS Appointments… - YouTube" — not under "YouTube", so
looking for a row named "YouTube" understates it. Both titles contain `youtube`
and both classify identically; the App categories tab rolls them back up under
`chrome` so the row count stays readable, with the titles on the tooltip.

## Changing the mapping

Settings → Tracker settings → **App categories**, per department. Changes take
effect on the tracker's next settings fetch — no restart, no rebuild. Historical
days are re-categorised too, because classification happens when the page is
drawn, not when the time was recorded. That cuts both ways: fixing a mapping
corrects the past, and so does breaking one.
