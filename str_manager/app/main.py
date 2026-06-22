import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import activity_log, ha_client, scheduler, settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_ws_clients: set[WebSocket] = set()


async def _broadcast(msg: dict[str, Any]) -> None:
    dead = set()
    for ws in _ws_clients:
        try:
            await ws.send_json(msg)
        except Exception:
            dead.add(ws)
    _ws_clients -= dead


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
    # Don't overwrite cleaner_code if masked value sent back
    if body.get("cleaner_code") == "••••":
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


@app.post("/api/refresh")
async def api_refresh():
    asyncio.create_task(scheduler.poll())
    return {"ok": True, "message": "Calendar refresh triggered."}


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
