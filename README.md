# Short-Term Rental Manager

> A Home Assistant OS add-on that automates short-term rental operations — lock codes, thermostat control, valve control, owner notifications, and a live dashboard — all driven by your Airbnb iCal calendar.

---

## Features

| | |
|---|---|
| 📅 **Calendar sync** | Polls your Airbnb iCal URL on a configurable interval and parses guest names, phone numbers, and reservation details |
| 🔐 **Automatic lock codes** | Sets a unique guest PIN at check-in, clears it at check-out; manages a fixed cleaner PIN between back-to-back reservations; supports multiple locks simultaneously |
| 🔔 **Door event notifications** | Real-time Z-Wave lock event listener — notified instantly when your guest or cleaner uses their code |
| ✅ **Task-completion notifications** | A separate notification confirms after the add-on has finished all check-in or check-out tasks |
| 🌡️ **Thermostat control** | View current temp, adjust set point with ±1° stepper, switch HVAC modes — from the Devices tab |
| 💧 **Water valve control** | Open or close your main water shutoff from the Devices tab |
| ⚡ **Automation triggers** | Fire any HA automations at check-in, check-out, or when the cleaner locks up |
| 🧹 **Cleaner detection** | Detects when the cleaner arrives (keypad event) and when they lock up and leave |
| 🛡️ **Test mode** | Simulates all actions without executing anything; every event logged with `[TEST]` prefix |

---

## UI Overview

```
┌─────────────────────────────────────────────────┐
│  Rental Manager                    Synced 2:14p  ●  ↻  │
├──────────┬──────────┬──────────┬──────────┬──────────┬──────────┤
│🏠 Dashboard│📅 Upcoming│📋 Activity│⚡ Actions │🔌 Devices │⚙️ Settings│
├─────────────────────────────────────────────────┤
│                                                 │
│  ┌──────────────────────────────────────────┐   │
│  │  Property Status                         │   │
│  │  ✅  OCCUPIED                            │   │
│  │                                          │   │
│  │  John Smith                              │   │
│  │  ┌────────────┐  ┌────────────┐         │   │
│  │  │ Check-in ✎ │  │ Check-out ✎│         │   │
│  │  │ Jun 23 3pm │  │ Jun 25 11am│         │   │
│  │  └────────────┘  └────────────┘         │   │
│  │  ┌──────────────────────────────────┐   │   │
│  │  │ Guest Code    ••••••   [Reveal]  │   │   │
│  │  └──────────────────────────────────┘   │   │
│  └──────────────────────────────────────────┘   │
│                                                 │
│  ┌──────────────────────────────────────────┐   │
│  │  RECENT ACTIVITY              View all → │   │
│  │  🏠  Check-in tasks complete — John…     │   │
│  │  🔑  Guest arrived, used code first time │   │
│  │  🔐  Guest code set in slot 2            │   │
│  └──────────────────────────────────────────┘   │
│                                                 │
│  [        ↻  Refresh Calendar             ]     │
└─────────────────────────────────────────────────┘
```

```
┌─────────────────────────────────────────────────┐
│  Devices                                    ↻   │
├─────────────────────────────────────────────────┤
│  LOCKS                                          │
│  ┌──────────────────────────────────────────┐   │
│  │  Front Door Lock           [  Locked  ]  │   │
│  │  🔋 Battery: 87%                         │   │
│  │  ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄   │   │
│  │  Slot 1    —              Empty          │   │
│  │  Slot 2 ▸  5382          [  Guest  ]    │   │
│  │  Slot 3 ▸  • • • •       [ Cleaner ]   │   │
│  │  Slot 4    —              Empty          │   │
│  │  Slot 5    —              Empty          │   │
│  │  ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄   │   │
│  │  [ Unlock ]              [   Lock   ]   │   │
│  └──────────────────────────────────────────┘   │
│                                                 │
│  THERMOSTAT                                     │
│  ┌──────────────────────────────────────────┐   │
│  │  Living Room               [  Heating ]  │   │
│  │  Current          Set To                 │   │
│  │  71°F         [ − ]  74°F  [ + ]         │   │
│  │  [ Heat ] [ Cool ] [ Auto ] [ Off ]      │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

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
| Water Valve Entity | Select a `valve.*` or `switch.*` entity for your water shutoff |

---

## Tabs

### Dashboard

The main status view — updates in real-time via WebSocket.

- **Status card** — VACANT / OCCUPIED / CLEANER with color-coded background
- **Active guest block** — name, check-in/out times (tap to edit inline), guest code (tap Reveal)
- **Next reservation card** — upcoming guest and arrival time (shown when vacant or in cleaner mode)
- **Recent activity** — last 5 log entries
- **Refresh Calendar** button — forces an immediate iCal poll

**Inline time editing**: tap any check-in or check-out cell to override the time for that specific reservation. Edits persist across calendar refreshes.

### Upcoming

All future reservations from your calendar. Tap any card for full details — guest name, phone last 4, email, number of adults, reservation code, and UID.

### Activity

Full event history — filterable, paginated, newest first. Stores the last 500 entries.

Filter options: **All / Check-in / Check-out / First Entry / Cleaner / Errors**

### Actions

What the add-on is scheduled to do and when — one card per upcoming reservation event, showing every step: lock code changes, notifications, and automation triggers.

### Devices

Live status and controls for all configured hardware.

**Locks**
- State badge (Locked / Unlocked) and battery level
- Code slots table (30 slots queried from Z-Wave JS):
  - Actual PIN — if in the Z-Wave JS value cache
  - `• • • •` — slot is occupied but PIN not cached
  - `—` — slot is empty
  - Guest and cleaner slots always show the correct PIN regardless of cache
- **Lock** and **Unlock** buttons

**Thermostats** (one card per entity)
- Current temperature reading
- Set-point stepper — tap `−` or `+` to adjust; debounced
- HVAC mode pills (shows whatever modes your device supports)

**Water Valve**
- Current state
- **Open Valve** / **Close Valve** button (contextual)

---

## Lock Code Logic

Guest PIN: the add-on uses the guest's **phone last 4 digits** from the Airbnb iCal description. If no phone is present, a random 4-digit PIN is generated. The code is saved to `/data/state.json` and survives add-on restarts.

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

Codes are read via the Z-Wave JS WebSocket API (`zwave_js/get_value`), which reads from Z-Wave JS's **value cache** — not directly from the lock hardware.

For each of the 30 queried slots, two properties are read:

| Property | What it tells you |
|---|---|
| `userIdStatus` | Whether the slot is occupied (`1`) or empty (`0`) — always in cache |
| `userCode` | The actual PIN — available if Z-Wave JS has polled this slot recently |

If a slot shows `• • • •`, Z-Wave JS knows a code exists there but doesn't have the PIN cached. This resolves after the lock is next polled by HA.

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
- Every action logged in Activity as `[TEST] …`
- Yellow warning banner shown at the top of the UI

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

**Persistent data** in `/data/` (survives add-on updates and restarts):

| File | Contents |
|---|---|
| `settings.json` | All user configuration |
| `activity_log.json` | Event history (last 500 entries) |
| `reservation_overrides.json` | Per-reservation manual time edits |
| `state.json` | Active guest code |
| `options.json` | HA add-on options (test_mode) |

---

## Development

```bash
cd str_manager
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -v
```
