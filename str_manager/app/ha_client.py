import asyncio
import json
import logging
import os
from collections.abc import Callable, Coroutine
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

HA_URL        = "http://supervisor/core/api"
SUPERVISOR_URL = "http://supervisor"
WS_URL        = "ws://supervisor/core/websocket"


def _token() -> str:
    return os.environ.get("SUPERVISOR_TOKEN", "")


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}


async def call_service(domain: str, service: str, data: dict[str, Any]) -> None:
    async with aiohttp.ClientSession() as session:
        url = f"{HA_URL}/services/{domain}/{service}"
        async with session.post(url, json=data, headers=_headers()) as resp:
            if resp.status >= 400:
                text = await resp.text()
                logger.error("Service call %s.%s failed %s: %s", domain, service, resp.status, text)
            else:
                logger.debug("Service %s.%s called successfully", domain, service)


async def get_states(domain: str | None = None) -> list[dict[str, Any]]:
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{HA_URL}/states", headers=_headers()) as resp:
            if resp.status >= 400:
                logger.error("get_states failed: %s", resp.status)
                return []
            states: list[dict[str, Any]] = await resp.json()
    if not isinstance(states, list):
        return []
    if domain:
        states = [s for s in states if s["entity_id"].startswith(f"{domain}.")]
    return states


async def get_notify_services() -> list[str]:
    """Return a list of available notify service names (e.g. 'mobile_app_iphone')."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{HA_URL}/services", headers=_headers()) as resp:
            if resp.status >= 400:
                logger.error("get_services failed: %s", resp.status)
                return []
            services: list[dict[str, Any]] = await resp.json()
    if not isinstance(services, list):
        return []
    for domain_block in services:
        if domain_block.get("domain") == "notify":
            return sorted(domain_block.get("services", {}).keys())
    return []


async def get_state(entity_id: str) -> dict[str, Any] | None:
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{HA_URL}/states/{entity_id}", headers=_headers()) as resp:
            if resp.status == 404:
                return None
            return await resp.json()


async def get_lock_usercodes(entity_id: str, node_id: int, max_slots: int = 10) -> dict[str, str]:
    """
    Query Z-Wave JS usercode values for slots 1‥max_slots.
    Returns {slot_str: code_str} for every non-empty slot.
    Uses a short-lived WS connection so as not to disturb the event listener.
    """
    import websockets

    results: dict[str, str] = {}
    try:
        async with websockets.connect(WS_URL, open_timeout=5, ping_timeout=5) as ws:
            # Auth
            await ws.recv()  # auth_required
            await ws.send(json.dumps({"type": "auth", "access_token": _token()}))
            auth_ok = json.loads(await ws.recv())
            if auth_ok.get("type") != "auth_ok":
                return results

            # Resolve config_entry_id for the entity
            await ws.send(json.dumps({"id": 1, "type": "config/entity_registry/get", "entity_id": entity_id}))
            reg = json.loads(await ws.recv())
            entry_id = (reg.get("result") or {}).get("config_entry_id")
            if not entry_id:
                logger.warning("get_lock_usercodes: no config_entry_id for %s", entity_id)
                return results

            # Send all slot queries in one burst
            slot_for_id: dict[int, int] = {}
            for slot in range(1, max_slots + 1):
                mid = slot + 1  # ids start at 2 (1 was used above)
                slot_for_id[mid] = slot
                await ws.send(json.dumps({
                    "id": mid,
                    "type": "zwave_js/get_value",
                    "entry_id": entry_id,
                    "node_id": node_id,
                    "command_class": 99,   # Access Control / UserCode
                    "endpoint": 0,
                    "property": "userCode",
                    "property_key": slot,
                }))

            # Collect responses (one per slot, with timeout)
            for _ in range(max_slots):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    resp = json.loads(raw)
                    slot = slot_for_id.get(resp.get("id"))
                    if slot and resp.get("success"):
                        val = resp.get("result")
                        if val and str(val).strip():
                            results[str(slot)] = str(val).strip()
                except asyncio.TimeoutError:
                    break
    except Exception as exc:
        logger.error("get_lock_usercodes(%s) failed: %s", entity_id, exc)
    return results


async def reload_addon_store() -> bool:
    """Tell the Supervisor to re-fetch all add-on repositories."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{SUPERVISOR_URL}/store/reload",
                headers=_headers(),
            ) as resp:
                return resp.status < 400
    except Exception as exc:
        logger.error("reload_addon_store failed: %s", exc)
        return False


# WebSocket event subscription

_ws_listeners: dict[str, list[Callable[..., Coroutine[Any, Any, None]]]] = {}
_ws_task: asyncio.Task | None = None
_msg_id = 0


def _next_id() -> int:
    global _msg_id
    _msg_id += 1
    return _msg_id


async def subscribe_events(event_type: str, callback: Callable[..., Coroutine[Any, Any, None]]) -> None:
    _ws_listeners.setdefault(event_type, []).append(callback)


async def start_ws_listener() -> None:
    global _ws_task
    _ws_task = asyncio.create_task(_ws_loop())


async def stop_ws_listener() -> None:
    if _ws_task:
        _ws_task.cancel()


async def _ws_loop() -> None:
    import websockets

    while True:
        try:
            async with websockets.connect(WS_URL) as ws:
                auth_req = json.loads(await ws.recv())
                if auth_req.get("type") != "auth_required":
                    raise RuntimeError(f"Unexpected WS handshake: {auth_req}")

                await ws.send(json.dumps({"type": "auth", "access_token": _token()}))
                auth_ok = json.loads(await ws.recv())
                if auth_ok.get("type") != "auth_ok":
                    raise RuntimeError(f"WS auth failed: {auth_ok}")

                for event_type in _ws_listeners:
                    sub_id = _next_id()
                    await ws.send(json.dumps({
                        "id": sub_id,
                        "type": "subscribe_events",
                        "event_type": event_type,
                    }))
                    await ws.recv()  # subscription ack

                logger.info("HA WebSocket connected and subscribed to %s", list(_ws_listeners))

                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("type") == "event":
                        event = msg.get("event", {})
                        et = event.get("event_type")
                        if et in _ws_listeners:
                            for cb in _ws_listeners[et]:
                                asyncio.create_task(cb(event.get("data", {})))

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("WS disconnected (%s), reconnecting in 10s...", exc)
            await asyncio.sleep(10)
