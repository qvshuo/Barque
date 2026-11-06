"""Send notifications through Bark."""

from __future__ import annotations

import logging
from urllib.parse import quote

import httpx


logger = logging.getLogger(__name__)


def send_bark_notification(notify_url: str, title: str, body: str) -> bool:
    url = notify_url.rstrip("/") + f"/{quote(title)}/{quote(body)}"
    try:
        response = httpx.get(url, timeout=10)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Bark notification failed: %s", exc)
        return False
    logger.info("Bark notification sent: %s", title)
    return True
