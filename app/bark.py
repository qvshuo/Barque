"""Send notifications through Bark."""

from __future__ import annotations

import logging
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

logger = logging.getLogger(__name__)


def send_bark_notification(notify_url: str, title: str, body: str) -> bool:
    try:
        parsed = urlsplit(notify_url)
        path = parsed.path.rstrip("/") + f"/{quote(title, safe='')}/{quote(body, safe='')}"
        url = urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))
        response = httpx.get(url, timeout=10)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("code") != 200:
            raise ValueError("Bark rejected notification")
    except (httpx.HTTPError, httpx.InvalidURL, ValueError):
        logger.warning("Bark notification failed")
        return False
    logger.info("Bark notification sent: %s", title)
    return True
