import logging

from . import ha_client

logger = logging.getLogger(__name__)


async def trigger(automation_ids: list[str]) -> None:
    for automation_id in automation_ids:
        if not automation_id:
            continue
        logger.info("Triggering automation %s", automation_id)
        await ha_client.call_service("automation", "trigger", {
            "entity_id": automation_id,
            "skip_condition": False,
        })
