# Short-Term Rental Manager

A Home Assistant OS add-on that automates short-term rental property operations — lock code management, thermostat control, owner notifications, and a live dashboard — all driven by your Airbnb iCal calendar.

## Features

- **Calendar sync** — polls your Airbnb iCal URL on a configurable schedule
- **Lock code automation** — sets a unique 6-digit guest code at check-in, clears it at check-out; activates your fixed cleaner code between back-to-back reservations
- **First entry detection** — notifies you the moment your guest physically uses their code for the first time
- **Thermostat control** — switches between guest and away temperatures automatically
- **Automation triggers** — run any HA automations at check-in and check-out
- **Notifications** — pushes to your HA mobile app and creates persistent in-dashboard notifications
- **Live dashboard** — sidebar panel with status, upcoming reservations, full activity log, and settings

## Requirements

- Home Assistant OS or Supervised
- Z-Wave JS integration with a Z-Wave lock
- Airbnb iCal calendar URL (exported from your Airbnb host dashboard)

## Installation

1. SSH into your HA OS machine and copy this repository into `/addons/str_manager/`

```bash
cd /addons
git clone https://github.com/tonygenovese/hass_rental.git str_manager
```

2. In Home Assistant go to **Settings → Add-ons → Add-on Store**, click the three-dot menu, and select **Check for updates**

3. Find **Short-Term Rental Manager** under the Local section, click **Install**

4. Start the add-on and enable **Show in sidebar**

5. Open **Rental Manager** in the sidebar, go to the **Settings** tab, and configure:
   - Your Airbnb iCal URL
   - Lock entity and code slot numbers
   - Cleaner PIN (fixed)
   - Thermostat and temperatures (optional)
   - Notification service
   - Check-in / check-out automations (optional)

## Dashboard

| Tab | Description |
|---|---|
| Dashboard | Current status, active guest details, guest code (tap to reveal), recent activity |
| Upcoming | All future reservations from your calendar |
| Activity Log | Full filterable event history — check-ins, check-outs, first entries, cleaner visits, errors |
| Settings | All configuration with live entity dropdowns populated from HA |

## Lock Code Logic

| State | Lock behavior |
|---|---|
| Guest checked in | Random 6-digit code set in configured guest slot |
| Guest checked out (no next reservation) | Guest code cleared |
| Guest checked out (next reservation within 24h) | Guest code cleared → cleaner code set in cleaner slot |
| Next guest checks in | Cleaner code cleared → new guest code set |

## Development & Testing

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -v
```

80 tests covering iCal parsing, state machine logic, transition side effects, activity log, and settings.
