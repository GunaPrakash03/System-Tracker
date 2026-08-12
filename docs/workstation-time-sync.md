# Workstation clocks: network time and timezone

Every timestamp in this system originates on a workstation. The tracker reads
the machine's clock, stamps the slot, and posts it; nothing downstream corrects
it. A machine whose clock is wrong produces a record that is wrong, and the
dashboard has no way to tell the difference.

This is what to check on each machine, and why it matters more here than it
does for most software.

## What "correct" means for a workstation

Two separate settings, both of which have to be right:

| Setting | Required value | What breaks if wrong |
|---|---|---|
| **Clock synchronised** | `yes`, via NTP | Slots land at times the work did not happen |
| **Time zone** | `Asia/Kolkata` (IST, +05:30) | Hourly charts and the day timeline are offset |

The two are independent. A machine can hold perfectly accurate UTC and still
report the wrong hour if its zone is wrong, and it can be set to IST while
drifting minutes away from real time.

## Checking a machine

```bash
timedatectl
```

A correctly configured workstation looks like this — real output from `sys0041`:

```
                 Local time: Wed 2026-08-12 18:06:39 IST
             Universal time: Wed 2026-08-12 12:36:39 UTC
                   RTC time: Wed 2026-08-12 12:36:39
                  Time zone: Asia/Kolkata (IST, +0530)
  System clock synchronized: yes
                NTP service: active
            RTC in local TZ: no
```

The three lines that matter:

- **`System clock synchronized: yes`** — the clock is being corrected from the
  network. If this says `no`, the machine is running on whatever its hardware
  clock drifted to.
- **`NTP service: active`** — something is actually doing the correcting.
- **`Time zone: Asia/Kolkata`** — not `UTC`, and not `Etc/GMT+5`, which is a
  different thing and does not observe the same rules.

`RTC in local TZ: no` should also stay as it is. Storing local time in the
hardware clock is a Windows convention; on a dual-boot machine it makes the two
systems disagree about what time it is.

## Fixing a machine

Ubuntu uses `systemd-timesyncd`, which is installed by default:

```bash
# turn network time on
sudo timedatectl set-ntp true

# set the zone
sudo timedatectl set-timezone Asia/Kolkata

# confirm the service is running and will come back after a reboot
systemctl is-active systemd-timesyncd     # active
systemctl is-enabled systemd-timesyncd    # enabled

# see which server it is using and how often it polls
timedatectl show-timesync --property=ServerName --property=PollIntervalMaxUSec
```

On `sys0041` that last command reports `ntp.ubuntu.com`, polling at most every
34 minutes, which is the stock Ubuntu configuration and is entirely adequate.

**Restart the tracker after changing either setting.** A running process keeps
the timezone it started with, so a corrected zone does not reach the tracker
until it restarts:

```bash
systemctl --user restart system-tracker
```

## Slot times no longer come from this clock

Since `use_network_time` was added, the timestamp on a time slot is taken from
the **server**, not from the workstation. Every API response carries a `Date`
header, and the tracker is making a request every interval anyway, so the
server's clock is free.

It is anchored as `(server time, CLOCK_BOOTTIME)` rather than as an offset
against the wall clock, and that detail is the whole point:

- **Boottime cannot be set and does not jump.** Once anchored, the recorded time
  is immune to anything done to the system clock afterwards.
- **It keeps counting across suspend**, unlike `CLOCK_MONOTONIC`, so a laptop
  that sleeps does not wake reporting the moment it went down.
- **An outage does not lose the clock.** Boottime keeps advancing, so the last
  anchor stays good for as long as the machine is up, and the first response
  after the network returns re-anchors it.

Only a tracker that has *never* reached the server falls back to the system
clock, because at that point there is nothing else to use.

The startup log says which is in force:

```
clock: server time (system clock is +1s off)
```

and complains when this machine's own clock is more than
`clock_skew_warn_seconds` (default 30) away. Recording stays correct either way;
the warning exists because a machine tens of seconds out is broken or is being
adjusted, and silently compensating would hide that.

### Which means the workstation clock still matters — for other things

**The timezone still comes from the machine.** The server supplies the instant,
not the zone; it has no idea where the workstation is. Hour buckets, the day
timeline and the idle marks are all local, so a machine set to the wrong zone
still produces a chart that reads at the wrong hours.

**Everything else on the machine still depends on it** — file timestamps,
package tooling, TLS certificate validation, the system journal. A workstation
with a broken clock is a broken workstation, whatever the tracker does about it.

**Set it correctly anyway.** Network time in the tracker is a safety net against
tampering and drift, not a licence to leave a machine misconfigured.

## Which clock produces what

| What | Source | On an IST machine |
|---|---|---|
| Slot `startedAt` | server `Date`, advanced on boottime | **UTC** |
| Hour buckets, day segments, idle marks | `datetime.now()` — always local | **IST** |

So a slot recorded at `12:36 UTC` appears in the `18:00` hour bucket. Both
describe the same moment, expressed in different zones: the slot must be UTC
because the API stores naive UTC, while the hourly chart is a human-facing
summary that should read in the employee's own working hours.

**Do not try to reconcile a slot time against an hour bucket by eye.** They will
differ by the machine's UTC offset, and that is not a symptom of a broken clock.

`use_local_time` must stay `false`. It only applies now when network time is
unavailable or switched off, and setting it true posts local time into a column
the API reads as UTC — putting every slot five and a half hours into the future,
the failure that appeared the first time a second workstation was provisioned.

## What a wrong clock used to cost

Kept here because it explains why the network clock exists, and because it still
applies to any machine running an older tracker:

- **Wrong clocks are invisible.** A machine an hour ahead produced a perfectly
  plausible day; nothing in the dashboard flagged it.
- **A machine that is behind lost data.** Slots are keyed by start time, so a
  clock jumping backwards — exactly what happens when a badly out-of-sync
  machine finally syncs — made the tracker re-post times the server already had,
  and the duplicates were discarded.
- **The clock was a trust boundary.** Anyone able to set the time on their own
  machine could shift their hours, or erase a span of the day by winding back.
  That is the specific problem the server clock removes.

## Checking the whole fleet

There is no central view of workstation clock health, so this is a manual check
at provisioning time and whenever a report looks wrong. On each machine:

```bash
timedatectl | grep -E 'synchronized|NTP service|Time zone'
```

Anything other than `yes`, `active` and `Asia/Kolkata` needs the fix above
before its data is trusted.
