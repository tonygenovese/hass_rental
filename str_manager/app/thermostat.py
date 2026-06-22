import logging

from . import ha_client

logger = logging.getLogger(__name__)


async def set_temperature(entity_id: str, temperature: float) -> None:
    if not entity_id:
        return
    logger.info("Setting thermostat %s to %.1f", entity_id, temperature)
    await ha_client.call_service("climate", "set_temperature", {
        "entity_id": entity_id,
        "temperature": temperature,
    })
