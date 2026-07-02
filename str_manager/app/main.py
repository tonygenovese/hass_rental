import asyncio
import logging
import logging.handlers
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import activity_log, ha_client, manual_reservations, reservation_overrides, scheduler, settings

_LOG_PATH = "/data/app.log"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
try:
    _file_handler = logging.handlers.RotatingFileHandler(_LOG_PATH, maxBytes=500_000, backupCount=1)
    _file_handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(_file_handler)
except OSError as exc:
    logging.getLogger(__name__).warning("File logging disabled (%s)", exc)
logger = logging.getLogger(__name__)

_ws_clients: set[WebSocket] = set()


async def _broadcast(msg: dict[str, Any]) -> None:
    dead = set()
    for ws in _ws_clients:
        try:
            await ws.send_json(msg)
        except Exception:
            dead.add(ws)
    _ws_clients.difference_update(dead)


@asynccontextmanager
async def lifespan(app: FastAPI):
    activity_log.init()
    cfg = settings.load()

    scheduler.broadcast_hook = _broadcast

    await ha_client.subscribe_events("zwave_js_notification", scheduler.handle_lock_event)
    await ha_client.start_ws_listener()

    scheduler.start(cfg.get("poll_interval_minutes", 30))
    asyncio.create_task(scheduler.poll())

    activity_log.add("info", "Short-Term Rental Manager started.")
    yield

    scheduler.stop()
    await ha_client.stop_ws_listener()


app = FastAPI(lifespan=lifespan)


# ── REST API ──────────────────────────────────────────────────────────────────

@app.get("/api/status")
async def api_status():
    return scheduler.get_status()


@app.get("/api/reservations")
async def api_reservations():
    return scheduler.get_reservations()


@app.get("/api/activity-log")
async def api_activity_log(page: int = 1, limit: int = 50, type: str = "all"):
    return activity_log.get_page(page, limit, type if type != "all" else None)


@app.get("/api/settings")
async def api_get_settings():
    return settings.masked(settings.load())


@app.post("/api/settings")
async def api_save_settings(body: dict):
    current = settings.load()
    # Preserve stored cleaner PIN when the field comes back masked OR blank —
    # the UI blanks the masked field, so "" must mean "keep existing" too
    if body.get("cleaner_code") in ("", "••••", None):
        body["cleaner_code"] = current.get("cleaner_code", "")
    merged = {**current, **body}
    settings.save(merged)
    scheduler.restart(merged.get("poll_interval_minutes", 30))
    activity_log.add("info", "Settings updated.")
    return {"ok": True}


@app.get("/api/ha/entities")
async def api_ha_entities(domain: str = ""):
    states = await ha_client.get_states(domain if domain else None)
    return [
        {"entity_id": s["entity_id"], "name": s.get("attributes", {}).get("friendly_name", s["entity_id"])}
        for s in states
    ]


@app.get("/api/ha/notify-services")
async def api_notify_services():
    names = await ha_client.get_notify_services()
    return [{"service": n, "label": n.replace("_", " ").title()} for n in names]


@app.get("/api/upcoming-actions")
async def api_upcoming_actions(limit: int = 5, offset: int = 0):
    return scheduler.get_upcoming_actions(limit, offset)


@app.post("/api/reservation-override")
async def api_reservation_override(body: dict):
    uid = body.get("uid", "").strip()
    if not uid:
        return JSONResponse({"ok": False, "error": "uid required"}, status_code=400)
    reservation_overrides.set_times(
        uid,
        check_in=body.get("check_in"),
        check_out=body.get("check_out"),
    )
    activity_log.add("info", f"Times manually updated for reservation {uid}")
    # Re-fetch so the state machine picks up the new effective times immediately
    asyncio.create_task(scheduler.poll())
    return {"ok": True}


@app.get("/api/device-status")
async def api_device_status():
    cfg = settings.load()
    lock_ids        = cfg.get("lock_entity_ids", [])
    thermostat_ids  = cfg.get("thermostat_entity_ids", [])
    valve_id        = cfg.get("water_valve_entity_id", "")

    locks = []
    for lid in lock_ids:
        state = await ha_client.get_state(lid)
        if not state:
            continue
        attrs = state.get("attributes", {})
        node_id = attrs.get("node_id")

        # Start with any codes exposed as entity attributes (some integrations do this)
        code_slots: dict[str, dict] = {}
        for slot in range(1, 11):
            key = f"code_slot_{slot}"
            if key in attrs:
                val = attrs[key]
                code_slots[str(slot)] = {"code": str(val) if val else None, "occupied": bool(val)}

        # Supplement via Z-Wave JS WS API (reads userIdStatus + userCode from cache)
        if node_id is not None:
            zwave_data = await ha_client.get_lock_usercodes(lid, node_id, max_slots=30)
            for slot_str, slot_data in zwave_data.items():
                if slot_str not in code_slots:
                    code_slots[slot_str] = slot_data
                else:
                    if slot_data.get("occupied"):
                        code_slots[slot_str]["occupied"] = True
                    if slot_data.get("code"):
                        code_slots[slot_str]["code"] = slot_data["code"]

        locks.append({
            "entity_id":     lid,
            "name":          attrs.get("friendly_name", lid),
            "state":         state.get("state"),
            "battery_level": attrs.get("battery_level"),
            "node_id":       node_id,
            "code_slots":    code_slots,
        })

    thermostats = []
    for tid in thermostat_ids:
        state = await ha_client.get_state(tid)
        if not state:
            continue
        attrs = state.get("attributes", {})
        thermostats.append({
            "entity_id":           tid,
            "name":                attrs.get("friendly_name", tid),
            "state":               state.get("state"),
            "current_temperature": attrs.get("current_temperature"),
            "target_temperature":  attrs.get("temperature"),
            "hvac_action":         attrs.get("hvac_action"),
            "unit":                attrs.get("temperature_unit", "°F"),
            "hvac_modes":          attrs.get("hvac_modes", []),
            "min_temp":            attrs.get("min_temp"),
            "max_temp":            attrs.get("max_temp"),
            "temp_step":           attrs.get("target_temp_step", 1),
        })

    water_valve = None
    if valve_id:
        state = await ha_client.get_state(valve_id)
        if state:
            attrs = state.get("attributes", {})
            water_valve = {
                "entity_id": valve_id,
                "name":      attrs.get("friendly_name", valve_id),
                "state":     state.get("state"),
            }

    return {
        "locks":         locks,
        "thermostats":   thermostats,
        "water_valve":   water_valve,
        "managed_codes": scheduler.get_managed_codes(),
    }


@app.post("/api/device/lock")
async def api_device_lock(body: dict):
    entity_id = body.get("entity_id", "").strip()
    action = body.get("action", "")
    if not entity_id or action not in ("lock", "unlock"):
        return JSONResponse({"ok": False, "error": "invalid params"}, status_code=400)
    await ha_client.call_service("lock", action, {"entity_id": entity_id})
    activity_log.add("info", f"Lock manually {action}ed: {entity_id}")
    return {"ok": True}


@app.post("/api/device/thermostat")
async def api_device_thermostat(body: dict):
    entity_id = body.get("entity_id", "").strip()
    temperature = body.get("temperature")
    hvac_mode = body.get("hvac_mode", "").strip()
    if not entity_id:
        return JSONResponse({"ok": False, "error": "entity_id required"}, status_code=400)
    if temperature is not None:
        await ha_client.call_service("climate", "set_temperature", {
            "entity_id": entity_id, "temperature": float(temperature)
        })
        activity_log.add("thermostat", f"Thermostat {entity_id} set to {temperature}° manually")
    if hvac_mode:
        await ha_client.call_service("climate", "set_hvac_mode", {
            "entity_id": entity_id, "hvac_mode": hvac_mode
        })
        activity_log.add("thermostat", f"Thermostat {entity_id} mode set to {hvac_mode}")
    return {"ok": True}


@app.post("/api/device/valve")
async def api_device_valve(body: dict):
    entity_id = body.get("entity_id", "").strip()
    action = body.get("action", "")
    if not entity_id or action not in ("open", "close"):
        return JSONResponse({"ok": False, "error": "invalid params"}, status_code=400)
    domain = entity_id.split(".")[0]
    svc = ("open_valve" if action == "open" else "close_valve") if domain == "valve" \
          else ("turn_on" if action == "open" else "turn_off")
    await ha_client.call_service(domain, svc, {"entity_id": entity_id})
    activity_log.add("info", f"Water valve {action}ed manually: {entity_id}")
    return {"ok": True}


@app.post("/api/refresh")
async def api_refresh():
    asyncio.create_task(scheduler.poll())
    return {"ok": True, "message": "Calendar refresh triggered."}


@app.get("/api/test-reservations")
async def api_get_test_reservations():
    return manual_reservations.load_raw()


@app.post("/api/test-reservations")
async def api_add_test_reservation(body: dict):
    guest_name = body.get("guest_name", "Test Guest").strip()
    check_in   = body.get("check_in", "").strip()
    check_out  = body.get("check_out", "").strip()
    if not check_in or not check_out:
        return JSONResponse({"ok": False, "error": "check_in and check_out required"}, status_code=400)
    entry = manual_reservations.add(guest_name, check_in, check_out)
    asyncio.create_task(scheduler.poll())
    return {"ok": True, "reservation": entry}


@app.delete("/api/test-reservations/{uid}")
async def api_delete_test_reservation(uid: str):
    ok = manual_reservations.remove(uid)
    asyncio.create_task(scheduler.poll())
    return {"ok": ok}


@app.delete("/api/test-reservations")
async def api_clear_test_reservations():
    manual_reservations.clear()
    asyncio.create_task(scheduler.poll())
    return {"ok": True}


@app.get("/api/app-logs")
async def api_app_logs(lines: int = 300):
    try:
        with open(_LOG_PATH) as f:
            all_lines = f.readlines()
        return {"lines": [l.rstrip() for l in all_lines[-lines:]]}
    except FileNotFoundError:
        return {"lines": []}


@app.post("/api/reload-store")
async def api_reload_store():
    ok = await ha_client.reload_addon_store()
    if ok:
        await asyncio.sleep(4)  # wait for HA to finish fetching before we respond
    return {"ok": ok}


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_clients.add(ws)
    try:
        await ws.send_json({"type": "status_update", "data": scheduler.get_status()})
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(ws)


# ── Static frontend ───────────────────────────────────────────────────────────

app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
