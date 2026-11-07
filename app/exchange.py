"""Exchange-rate synchronization, caching and currency conversion."""

from __future__ import annotations

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

from app.bark import send_bark_notification
from app.database import Database
from app.currencies import DEFAULT_CURRENCIES, CURRENCIES_URL


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


class ExchangeService:
    def __init__(self, database: Database, timezone: str, notify_url: str) -> None:
        self.database = database
        self.timezone = timezone
        self.notify_url = notify_url

    def load_rates(self) -> dict:
        cache = self.database.read_state("exchange_rates", DEFAULT_CACHE)
        cache.setdefault("rates", {"CNY": 1.0})
        cache["rates"].setdefault("CNY", 1.0)
        return cache

    def sync_supported_currencies(self, today: date) -> dict[str, str]:
        cache = self.database.read_state("currency_catalog", {"currencies": DEFAULT_CURRENCIES})
        if cache.get("date") == today.isoformat():
            return cache["currencies"]
        try:
            response = httpx.get(CURRENCIES_URL, timeout=15, follow_redirects=True)
            response.raise_for_status()
            currencies = response.json()
            if not isinstance(currencies, dict) or "CNY" not in currencies or not all(isinstance(code, str) and len(code) == 3 and code.isascii() and code.isalpha() and code.isupper() and isinstance(name, str) for code, name in currencies.items()):
                raise ValueError("Invalid currency catalog")
            cache = {"date": today.isoformat(), "currencies": dict(sorted(currencies.items()))}
            self.database.write_state("currency_catalog", cache)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Currency catalog sync failed: %s", exc)
        return cache["currencies"]

    def sync_once_per_day(self, today: date, required_currencies: set[str] | None = None) -> dict:
        cache = self.load_rates()
        required_currencies = {currency.upper() for currency in required_currencies or set()}
        required_currencies.add("CNY")
        if cache.get("date") == today.isoformat() and self._has_required_rates(cache, required_currencies):
            return cache

        target_currencies = sorted(currency for currency in required_currencies if currency != "CNY")
        if not target_currencies:
            cache["date"] = today.isoformat()
            cache["updated_at"] = datetime.now(ZoneInfo(self.timezone)).isoformat(timespec="seconds")
            cache["rates"] = {"CNY": 1.0}
            cache["failure_count"] = 0
            cache["failure_notified_at"] = None
            cache["last_error"] = None
            self.database.write_state("exchange_rates", cache)
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
                "updated_at": datetime.now(ZoneInfo(self.timezone)).isoformat(timespec="seconds"),
                "rates": rates,
                "failure_count": 0,
                "failure_notified_at": None,
                "last_error": None,
            }
            self.database.write_state("exchange_rates", cache)
            logger.info("Exchange rates synced for %s", today.isoformat())
        except Exception as exc:
            cache["failure_count"] = int(cache.get("failure_count") or 0) + 1
            cache["last_error"] = str(exc)
            if self.notify_url and cache["failure_count"] >= 7 and cache.get("failure_notified_at") != today.isoformat():
                send_bark_notification(self.notify_url, "Barque 汇率同步异常", "Frankfurter 汇率已连续 7 次同步失败，请检查网络或服务状态。")
                cache["failure_notified_at"] = today.isoformat()
            self.database.write_state("exchange_rates", cache)
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
