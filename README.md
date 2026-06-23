# Short-Term Rental Manager

> A Home Assistant OS add-on that automates short-term rental operations — lock codes, thermostat control, valve control, owner notifications, and a live dashboard — all driven by your Airbnb iCal calendar.

![Dashboard](screenshots/dashboard.png)

---

## Features

| | |
|---|---|
| 📅 **Calendar sync** | Polls your Airbnb iCal URL on a configurable interval and parses guest names, phone numbers, and reservation details |
| 🔐 **Automatic lock codes** | Sets a unique guest PIN at check-in, clears it at check-out; manages a fixed cleaner PIN between back-to-back reservations; supports multiple locks simultaneously |
| 🔔 **Door event notifications** | Real-time Z-Wave lock event listener — notified instantly when your guest or cleaner uses their code |
| ✅ **Task-completion notifications** | A second notification confirms after the add-on has finished all check-in or check-out tasks |
| 🌡️ **Thermostat control** | View current temp, adjust set point with ±1° stepper, switch HVAC modes — from the Devices tab |
| 💧 **Water valve control** | Open or close your main water shutoff from the Devices tab |
| ⚡ **Automation triggers** | Fire any HA automations at check-in, check-out, or when the cleaner locks up |
| 🧹 **Cleaner detection** | Detects when the cleaner arrives (keypad event) and when they lock up and leave |
| 🛡️ **Test mode** | Simulates all actions without executing anything; every event logged with `[TEST]` prefix |

---

## Requirements

- Home Assistant OS or Supervised
- Z-Wave JS integration with at least one Z-Wave lock
- Airbnb iCal URL (host dashboard → Calendar → Export)
- HA Companion App on your phone (for push notifications)

---

## Installation

### Add-on Store (recommended)

1. **Settings → Add-ons → Add-on Store → ⋮ → Repositories**
2. Add this URL:
   ```
   https://github.com/tonygenovese/hass_rental
   ```
3. Close — **Short-Term Rental Manager** appears in the store
4. **Install → Start → Show in sidebar**

### SSH / local install

```bash
cd /addons
git clone https://github.com/tonygenovese/hass_rental.git
```

Reload the Add-on Store and install from the **Local** section.

---

## Setup

Open **Rental Manager** in the sidebar → **Settings** tab.

### 📅 Calendar

| Field | What to enter |
|---|---|
| Airbnb iCal URL | Paste from Airbnb → Calendar → Export calendar |
| Property Timezone | IANA name, e.g. `America/New_York` — controls when check-in/out times apply |
| Sync Interval | How often to poll (minutes). Default 30, min 5. |
| Default Check-in | Fallback time if Airbnb omits it, e.g. `15:00` |
| Default Check-out | Fallback time, e.g. `11:00` |

### 🔐 Lock

| Field | What to enter |
|---|---|
| Lock Entity / Entities | Select one or more HA lock entities — all receive the same codes |
| Guest Code Slot | Slot number for guest PINs (e.g. `2`) |
| Cleaner Code Slot | Slot number for the permanent cleaner PIN (e.g. `3`) |
| Cleaner PIN | Fixed PIN for your cleaner. Leave blank to keep the existing one. |

### 🔔 Notifications & Automations

| Field | What to enter |
|---|---|
| Notify Service | Your phone's HA notify service (requires Companion App) |
| Check-in Automations | HA automations to trigger at check-in |
| Check-out Automations | HA automations to trigger at check-out |
| Pre-Check-in Automations | Triggered when the cleaner locks up and leaves between stays |

### 🔌 Device Monitoring

| Field | What to enter |
|---|---|
| Thermostat Entity / Entities | One or more `climate.*` entities |
| Water Valve Entity | A `valve.*` or `switch.*` entity for your water shutoff |

![Settings tab](screenshots/settings.png)

---

## Tabs

### Dashboard

The main status view — updates in real-time via WebSocket.

- **Status card** — VACANT / OCCUPIED / CLEANER with color-coded background
- **Active guest block** — name, check-in/out times (tap to edit inline), guest code (tap Reveal)
- **Next reservation card** — upcoming guest and arrival time (shown when vacant or in cleaner mode)
- **Recent activity** — last 5 log entries
- **Refresh Calendar** button — forces an immediate iCal poll

![Dashboard — occupied](screenshots/dashboard_occupied.png)

**Inline time editing**: tap any check-in or check-out cell to override the time for that specific reservation. Edits persist across calendar refreshes.

### Upcoming

All future reservations from your calendar. Tap any card for full details — guest name, phone last 4, email, number of adults, reservation code, and UID.

![Upcoming tab](screenshots/upcoming.png)

### Activity

Full event history — filterable, paginated, newest first. Stores the last 500 entries.

Filter options: **All / Check-in / Check-out / First Entry / Cleaner / Errors**

![Activity tab](screenshots/activity.png)

### Actions

What the add-on is scheduled to do and when — one card per upcoming reservation event, showing every step: lock code changes, notifications, and automation triggers.

![Actions tab](screenshots/actions.png)

### Devices

Live status and controls for all configured hardware.

![Devices tab](screenshots/devices.png)

**Locks**
- State badge (Locked / Unlocked) and battery level
- Code slots table (30 slots queried from Z-Wave JS):
  - Shows the actual PIN if it's in the Z-Wave JS cache
  - Shows `• • • •` if the slot is occupied but the PIN isn't cached
  - Shows `—` for empty slots
  - Guest and cleaner slots are always shown with the correct PIN regardless of cache
- **Lock** and **Unlock** buttons

**Thermostats** (one card per entity)
- Current temperature reading
- Set-point stepper — tap `−` or `+` to adjust; debounced, sends one command per burst
- HVAC mode pills (shows whatever modes your device supports: Heat / Cool / Auto / Off / etc.)

**Water Valve**
- Current state
- **Open Valve** / **Close Valve** button (shows the contextual action only)

---

## Lock Code Logic

Guest PIN: the add-on uses the guest's **phone last 4 digits** from the Airbnb iCal `DESCRIPTION` field. If no phone number is present, a random 4-digit PIN is generated. The code is saved to `/data/state.json` and survives add-on restarts.

| When | What happens |
|---|---|
| Check-in time reached | Guest PIN set in guest slot on all configured locks |
| Check-out time, no next guest within 24h | Guest PIN cleared → VACANT |
| Check-out time, next guest within 24h | Guest PIN cleared + cleaner PIN set → CLEANER |
| Next reservation starts (cleaner mode) | Cleaner PIN cleared + new guest PIN set → OCCUPIED |
| Add-on restarts during an active stay | Guest code restored from `/data/state.json` |

---

## Notifications

### Task-completion (fires within one poll interval of the scheduled time)

| When | Title | Message |
|---|---|---|
| Check-in tasks done | **Ready for [Guest]** | "Check-in tasks done for [Guest]. Code XXXX set in slot N." |
| Check-out, property vacant | **Check-out Complete** | "Check-out tasks done for [Guest]. Guest code cleared. Property is vacant." |
| Check-out, cleaner mode | **Check-out Complete** | "Check-out tasks done for [Guest]. Guest code cleared. Cleaner mode active." |

### Door events (fires instantly — no polling delay)

| When | Title | Message |
|---|---|---|
| Guest uses keypad for the first time | **Guest Arrived!** | "[Guest] has arrived and used their code for the first time." |
| Cleaner uses keypad | **Cleaner Arrived** | "Cleaner entered the property." |
| Cleaner locks up and leaves | **Cleaner Left** | "Cleaner locked up and left the property." |

> In **test mode**, no notifications are sent. All events appear in the Activity tab with a `[TEST]` prefix.

---

## Z-Wave JS Lock Code Reading

Codes are read via the Z-Wave JS WebSocket API using `zwave_js/get_value`. This reads from Z-Wave JS's **value cache** — not directly from the lock hardware.

For each of the 30 queried slots, two properties are read:

| Property | What it tells you |
|---|---|
| `userIdStatus` | Whether the slot is occupied (`1`) or empty (`0`) — always in cache |
| `userCode` | The actual PIN — available if Z-Wave JS has polled this slot recently |

If a slot shows `• • • •`, Z-Wave JS knows a code exists there but doesn't have the PIN cached yet. This typically resolves after the lock is next polled by HA (when the lock wakes up or a code is used).

The guest code and cleaner code are always shown accurately because the add-on sets them directly and stores them locally.

---

## Test Mode

Enable in the add-on options (`Settings → Add-ons → Short-Term Rental Manager → Configuration`):

```yaml
test_mode: true
```

With test mode on:
- Lock codes are **not** set or cleared
- Thermostat commands are **not** sent
- Automations are **not** triggered
- Notifications are **not** sent
- Every action is logged in the Activity tab as `[TEST] …`
- A yellow banner appears at the top of every tab

Use this to verify your iCal sync, state transitions, and action scheduling before your first real guest.

---

## Architecture

```
str_manager/
├── config.yaml                   # Add-on manifest (ingress, arch, HA API, test_mode option)
├── Dockerfile
├── requirements.txt
├── run.sh                        # Container entrypoint
└── app/
    ├── main.py                   # FastAPI — REST API, WebSocket, lifespan startup
    ├── ha_client.py              # HA REST + Z-Wave JS WebSocket client
    ├── ical_parser.py            # iCal fetch and parse → Reservation objects
    ├── scheduler.py              # APScheduler poll loop + state machine transitions
    ├── state_machine.py          # RentalState enum + determine_state()
    ├── lock_manager.py           # set/clear lock user codes
    ├── thermostat.py             # set temperature via climate services
    ├── notifier.py               # push + persistent notifications
    ├── automations.py            # trigger HA automations
    ├── activity_log.py           # rolling 500-entry log
    ├── settings.py               # config CRUD
    ├── reservation_overrides.py  # per-reservation manual time overrides
    └── options.py                # reads test_mode from HA add-on options
```

**Persistent data** in `/data/` (add-on volume, survives updates):

| File | Contents |
|---|---|
| `settings.json` | All user configuration |
| `activity_log.json` | Event history (last 500 entries) |
| `reservation_overrides.json` | Per-reservation manual time edits |
| `state.json` | Active guest code — survives restarts |
| `options.json` | HA add-on options (test_mode) |

---

## Development

```bash
cd str_manager
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -v
```

Test suite covers iCal parsing, state machine logic, transition side effects, activity log, and settings migration.

---

## Screenshots

> To add screenshots: take them from your running HA instance, save as PNG into a `screenshots/` folder at the repo root, and push. The image paths used in this README are:

```
screenshots/dashboard.png
screenshots/dashboard_occupied.png
screenshots/upcoming.png
screenshots/activity.png
screenshots/actions.png
screenshots/devices.png
screenshots/settings.png
```
