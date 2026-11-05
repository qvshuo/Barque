"""Currency conversion and Bark notification helpers."""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from app.services.log_store import read_json, write_json_atomic


logger = logging.getLogger(__name__)

# Initial cache used until the first successful exchange-rate sync.
DEFAULT_CACHE = {
    "base": "CNY",
    "date": None,
    "updated_at": None,
    "rates": {"CNY": 1.0},
    "failure_count": 0,
    "failure_notified_at": None,
    "last_error": None,
}


def now_iso(timezone_name: str) -> str:
    return datetime.now(ZoneInfo(timezone_name)).isoformat(timespec="seconds")


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


class ExchangeService:
    def __init__(self, cache_path: Path, timezone: str, notify_url: str) -> None:
        self.cache_path = cache_path
        self.timezone = timezone
        self.notify_url = notify_url

    def load_rates(self) -> dict:
        cache = read_json(self.cache_path, DEFAULT_CACHE)
        cache.setdefault("rates", {"CNY": 1.0})
        cache["rates"].setdefault("CNY", 1.0)
        return cache

    def sync_once_per_day(self, today: date, required_currencies: set[str] | None = None) -> dict:
        cache = self.load_rates()
        required_currencies = {currency.upper() for currency in required_currencies or set()}
        required_currencies.add("CNY")
        if cache.get("date") == today.isoformat() and self._has_required_rates(cache, required_currencies):
            return cache

        target_currencies = sorted(currency for currency in required_currencies if currency != "CNY")
        if not target_currencies:
            cache["date"] = today.isoformat()
            cache["updated_at"] = now_iso(self.timezone)
            cache["rates"] = {"CNY": 1.0}
            cache["failure_count"] = 0
            cache["failure_notified_at"] = None
            cache["last_error"] = None
            write_json_atomic(self.cache_path, cache)
            return cache

        try:
            response = httpx.get(
                "https://api.frankfurter.dev/v1/latest",
                params={"from": "CNY", "to": ",".join(target_currencies)},
                follow_redirects=True,
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
            rates = payload.get("rates")
            if not isinstance(rates, dict):
                raise ValueError("Frankfurter response missing rates")
            rates = {key.upper(): float(value) for key, value in rates.items()}
            rates["CNY"] = 1.0
            cache = {
                "base": "CNY",
                "date": today.isoformat(),
                "updated_at": now_iso(self.timezone),
                "rates": rates,
                "failure_count": 0,
                "failure_notified_at": None,
                "last_error": None,
            }
            write_json_atomic(self.cache_path, cache)
            logger.info("Exchange rates synced for %s", today.isoformat())
        except Exception as exc:
            cache["failure_count"] = int(cache.get("failure_count") or 0) + 1
            cache["last_error"] = str(exc)
            if cache["failure_count"] >= 7 and cache.get("failure_notified_at") != today.isoformat():
                send_bark_notification(self.notify_url, "Cirrus 汇率同步异常", "Frankfurter 汇率已连续 7 次同步失败，请检查网络或服务状态。")
                cache["failure_notified_at"] = today.isoformat()
            write_json_atomic(self.cache_path, cache)
            logger.warning("Exchange rate sync failed: %s", exc)
        return cache

    def _has_required_rates(self, cache: dict, required_currencies: set[str]) -> bool:
        rates = cache.get("rates", {})
        return all(currency == "CNY" or rates.get(currency) for currency in required_currencies)

    def amount_to_cny(self, amount: float, currency: str, rates_cache: dict | None = None) -> float | None:
        currency = currency.upper()
        if currency == "CNY":
            return round(amount, 2)
        cache = rates_cache or self.load_rates()
        rate = cache.get("rates", {}).get(currency)
        if not rate:
            logger.warning("Missing exchange rate for %s", currency)
            return None
        return round(amount / float(rate), 2)
