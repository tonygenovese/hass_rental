import logging

from . import ha_client

logger = logging.getLogger(__name__)


async def send(notify_service: str, title: str, message: str, notification_id: str = "str_mgr") -> None:
    if notify_service:
        await ha_client.call_service("notify", notify_service, {
            "title": title,
            "message": message,
        })

    await ha_client.call_service("persistent_notification", "create", {
        "title": title,
        "message": message,
        "notification_id": notification_id,
    })
    logger.info("Notification sent: %s — %s", title, message)
