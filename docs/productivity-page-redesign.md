# Productivity page — redesign for review

**Status: implemented, 2026-08-10.** Section 6 records what actually shipped,
which differs from this draft in one important way — the day is drawn as a
timeline, not as a summary with no chart.

The reference image could not be opened from this machine (the CDN blocks
non-browser clients); it was eventually supplied as an attachment, and it showed
a Gantt-style ribbon with time on the x axis. That is what §6 describes.

## 1. What the page shows now

`/pages/employees/my-work` → Productivity tab, or `/pages/employees/productivity`.

- A stacked bar **per hour of the day**, five segments: Productive, Neutral,
  Unproductive, Idle, Not tracked.
- A **table with one row per hour**, same five columns plus tracked minutes, and
  a "Day average" row at the bottom.
- Two explanatory paragraphs.

Everything is a share of the whole hour, not of the tracked part — so an hour
with four minutes of work does not read like a full one.

## 2. What changes

### 2.1 Drop the per-hour breakdown

Remove the hourly chart and the hourly table. The page shows **one set of
figures for the day**:

| | |
|---|---|
| **Productive** | share of the day spent in apps categorised productive |
| **Idle** | tracked time with no keyboard, mouse or media activity |
| **Unproductive** | share spent in apps categorised unproductive |
| **Unmonitored** | time the tracker was not running (see §2.2) |

**Open question — what happens to "Neutral"?** Your list named productive, idle
and unproductive. Neutral currently absorbs anything uncategorised, and it is
where time lands when no window held focus at all (a headless build, a locked
screen). Three options:

- **(a)** Keep Neutral as a fourth figure. Nothing is hidden. *Recommended.*
- **(b)** Fold Neutral into Unproductive. Simple, but overstates unproductive
  time — an uncategorised app becomes an accusation.
- **(c)** Fold Neutral into Productive. Flatters the numbers; same objection.

Under (b) or (c) the day would no longer add up to what the tracker recorded,
and an uncategorised app would silently change someone's score. Worth being
deliberate about.

### 2.2 Rename "Not tracked"

"Not tracked" reads like a fault in the tool. It means the tracker was not
running — logged off, machine shut down, or outside working hours. Candidates,
best first:

| Word | Why |
|---|---|
| **Unmonitored** | states the fact without implying fault. *Recommended.* |
| **Offline** | familiar, but suggests network trouble |
| **Not recorded** | accurate, still slightly accusatory |
| **Outside tracking** | precise, long for a legend |

This is a label change in the chart legend, the table header and the
explanatory text. Say which you prefer.

## 3. The three new times — and the problem with them

You asked for:

1. **Tracking started at** — when tracking began today
2. **Last idle started at** — when the most recent idle period began
3. **Work resumed at** — the first productive moment after that idle period

**Only the first is available today, and only to the hour.**

The page reads the tracker's published summary
(`employee_setting.data.usage`), which is bucketed **per hour**: each bucket
holds `wall` seconds tracked, `active` seconds, and foreground seconds per app.
That structure can say "there was idle time in the 14:00 hour". It cannot say
"idle began at 14:37", because the minute detail is summed away before the page
ever sees it.

Two routes:

**(a) Extend the tracker to publish the times.** `proc_tracker.py` already knows
all three at the moment they happen — it decides second by second whether the
machine is active. Publishing three extra fields in the usage summary
(`started_at`, `last_idle_started_at`, `last_active_resumed_at`) is a small,
honest change, and the page then just displays them. *Recommended.*

**(b) Derive them from time slots.** Query `time_slot` for the day and walk it
looking for transitions. This sounds cheaper but is the worse option: the
existing code comments record that Gauzy's slot and activity endpoints are
**hard-capped at ~30 rows** by the controller and strip any limit passed, which
is exactly why this page stopped using them. A day is ~300 slots. We would be
deriving "when did idle start" from a tenth of the day and quietly getting it
wrong.

Route (a) means a tracker change plus a redeploy to the workstations, which is
the real cost. Route (b) needs no tracker change but cannot be trusted. I would
not build (b).

### 3.1 What the three fields would show

```
Tracking started      09:14
Last idle began       14:37   (28 minutes)
Work resumed          15:05
```

Points worth settling:

- **If the person is idle right now**, "Work resumed" has no value yet. Show a
  dash, or "still idle" with the elapsed time.
- **If there was no idle at all today**, both idle rows show a dash rather than
  disappearing, so the layout does not jump.
- **"Tracking started" is the first start of the day**, not the most recent. If
  someone logs out at lunch and back in, that is a gap in Unmonitored, not a new
  start. Say if you would rather see the latest.

## 4. What this page is not

Worth stating, because the request touches it: this page shows **one employee
for one day**, chosen by the header selectors. It is not a comparison across
people and not a date range. Idle is measured from the tracked time itself; the
active remainder is split by which app was **on screen**, since only one window
holds focus at a time — an app's raw duration is not a usable weight, because
the tracker records every running process and they would sum to many times the
wall clock.

## 5. Questions before I build

1. **Neutral** — keep it as a fourth figure, or fold it in? (§2.1)
2. **Which replacement word** for "Not tracked"? (§2.2)
3. **Route (a) or (b)** for the three times — extend the tracker, or leave them
   out for now? (§3) If (a), the tracker needs redeploying to each workstation.
4. **The image** — I could not view it. If it settles the layout, describe it.

## 6. What shipped

The page, top to bottom:

1. **Three wall-clock marks** — Tracking started, Last idle began, Work resumed.
2. **Summary** — one stacked strip plus a table: Productive, Neutral,
   Unproductive, Idle, Tracked, Unmonitored.
3. **Across the day** — a horizontal ribbon on a real time axis, running from
   the hour the day started through to **24:00**.

The standing explanatory paragraphs under the chart were removed on request;
the definitions live here instead.

### 6.1 The ribbon reads two sources, deliberately

| Source | Gives | Limitation |
|---|---|---|
| **Time slots** | the whole day, since they have existed all along | ten-minute buckets; no app, so colour comes from the hour's dominant category |
| **Tracker `segments`** | the app by name, so a two-minute spell keeps its own colour | only exist from 2026-08-10, when the feature shipped |

Segments win wherever they exist; slots fill the rest. Drawing both would stack
a coarse block over a fine one and hide precisely the detail worth seeing.

This was arrived at the hard way. Building from segments alone left a normal
morning looking untracked. Building from slots alone made two minutes of
Spotify inside a terminal-heavy hour disappear, because slots record how long
was active but never in what.

### 6.2 Browser time is classified by tab title

Every tab is the same `chrome` process, so classifying by process made an hour
of YouTube score identically to an hour of the dashboard. The tracker now
publishes a `focus` map keyed by **tab title** for browsers; `apps` is left
keyed by process, because App usage reports per application and splitting it by
tab would turn one row into fifty.

Consequence worth stating: browser time starts life unclassified and therefore
Neutral. Classifying the handful of sites that matter (`gauzy`, `slack`,
`hr portal`, …) moved 2h 27m out of Neutral in one edit. Matching is substring
and longest-wins, so `slack` catches every channel and DM.

### 6.3 Axis runs to midnight, not to the last block

Fitting the axis to the recorded blocks made an hour of tracking fill the width
and read like a full day. It now spans login → 24:00, so the empty evening is
visible as empty.

## 7. Decisions from review

- **Neutral kept** as a fourth figure rather than folded into Productive or
  Unproductive — folding it would make an unclassified app silently change
  someone's score.
- **"Not tracked" renamed "Unmonitored"**, and it sits outside the percentages:
  counting it as idle would make finishing early look like sitting idle.
- **Day totals are summed, not averaged.** The old "day average" averaged
  per-hour percentages, weighting a two-minute hour the same as a full one.
