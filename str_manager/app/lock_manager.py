import logging

from . import ha_client

logger = logging.getLogger(__name__)


async def set_code(entity_id: str, slot: int, code: str) -> None:
    logger.info("Setting lock code slot %d on %s", slot, entity_id)
    await ha_client.call_service("zwave_js", "set_lock_usercode", {
        "entity_id": entity_id,
        "code_slot": slot,
        "usercode": code,
    })


async def clear_code(entity_id: str, slot: int) -> None:
    logger.info("Clearing lock code slot %d on %s", slot, entity_id)
    await ha_client.call_service("zwave_js", "clear_lock_usercode", {
        "entity_id": entity_id,
        "code_slot": slot,
    })
