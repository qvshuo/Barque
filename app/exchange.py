"""Exchange-rate synchronization, caching and currency conversion."""

from __future__ import annotations

import logging
import math
from datetime import date, datetime
from sys import float_info
from zoneinfo import ZoneInfo

import httpx

from app.currencies import DEFAULT_CURRENCIES
from app.database import Database

logger = logging.getLogger(__name__)

# Initial cache used until the first successful exchange-rate sync.
DEFAULT_CACHE = {
    "base": "CNY",
    "date": None,
    "updated_at": None,
    "rates": {"CNY": 1.0},
}


def valid_rate(value) -> bool:
    return type(value) in (int, float) and 0 < value <= float_info.max


class ExchangeService:
    def __init__(self, database: Database, timezone: str) -> None:
        self.database = database
        self.timezone = timezone

    def load_rates(self) -> dict:
        cache = self.database.read_state("exchange_rates", DEFAULT_CACHE)
        cache.setdefault("rates", {"CNY": 1.0})
        cache["rates"].setdefault("CNY", 1.0)
        return cache

    def sync_once_per_day(self, today: date, required_currencies: set[str] | None = None) -> dict:
        cache = self.load_rates()
        required_currencies = {currency.upper() for currency in required_currencies or set()}
        required_currencies &= set(DEFAULT_CURRENCIES)
        required_currencies.add("CNY")
        if cache.get("date") == today.isoformat() and self._has_required_rates(
            cache, required_currencies
        ):
            return cache

        target_currencies = sorted(
            currency for currency in required_currencies if currency != "CNY"
        )
        if not target_currencies:
            cache["date"] = today.isoformat()
            cache["updated_at"] = datetime.now(ZoneInfo(self.timezone)).isoformat(
                timespec="seconds"
            )
            cache["rates"] = {"CNY": 1.0}
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
            rates = payload.get("rates") if isinstance(payload, dict) else None
            if not isinstance(rates, dict) or not all(
                valid_rate(rates.get(currency)) for currency in target_currencies
            ):
                raise ValueError("Frankfurter response contains missing or invalid rates")
            rates = {currency: float(rates[currency]) for currency in target_currencies}
            rates["CNY"] = 1.0
            cache = {
                "base": "CNY",
                "date": today.isoformat(),
                "updated_at": datetime.now(ZoneInfo(self.timezone)).isoformat(timespec="seconds"),
                "rates": rates,
            }
            self.database.write_state("exchange_rates", cache)
            logger.info("Exchange rates synced for %s", today.isoformat())
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Exchange rate sync failed: %s", exc)
        return cache

    def _has_required_rates(self, cache: dict, required_currencies: set[str]) -> bool:
        rates = cache.get("rates", {})
        return all(
            currency == "CNY" or valid_rate(rates.get(currency)) for currency in required_currencies
        )

    def amount_to_cny(
        self, amount: float, currency: str, rates_cache: dict | None = None
    ) -> float | None:
        currency = currency.upper()
        if currency == "CNY":
            return round(amount, 2)
        cache = rates_cache or self.load_rates()
        rate = cache.get("rates", {}).get(currency)
        if not valid_rate(rate):
            logger.warning("Missing or invalid exchange rate for %s", currency)
            return None
        converted = amount / rate
        return round(converted, 2) if math.isfinite(converted) else None
