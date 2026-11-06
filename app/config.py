"""TOML configuration loader and validators."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


BILLING_CYCLES = {"week", "month", "quarter", "year"}


@dataclass(frozen=True)
class AppConfig:
    title: str
    timezone: str
    check_interval_seconds: int
    remind_before_days: int
    notify_url: str


@dataclass(frozen=True)
class SubscriptionConfig:
    name: str
    category: str
    billing_cycle: str
    payment_date: str
    amount: float
    currency: str
    notify_enabled: bool


@dataclass(frozen=True)
class Config:
    app: AppConfig
    subscriptions: list[SubscriptionConfig]


def load_config(path: Path) -> Config:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid TOML config: {exc}") from exc

    app_raw = raw.get("app")
    if not isinstance(app_raw, dict):
        raise ValueError("Missing [app] config")

    app = AppConfig(
        title=_required_str(app_raw, "title"),
        timezone=_required_str(app_raw, "timezone"),
        check_interval_seconds=_required_int(app_raw, "check_interval_seconds", minimum=1),
        remind_before_days=_required_int(app_raw, "remind_before_days", minimum=0),
        notify_url=_required_str(app_raw, "notify_url"),
    )

    try:
        ZoneInfo(app.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Invalid timezone: {app.timezone}") from exc

    subscriptions_raw = raw.get("subscriptions")
    if not isinstance(subscriptions_raw, list):
        raise ValueError("Missing [[subscriptions]] config")

    subscriptions = [_load_subscription(item, index) for index, item in enumerate(subscriptions_raw, start=1)]
    return Config(app=app, subscriptions=subscriptions)


def _load_subscription(item: object, index: int) -> SubscriptionConfig:
    if not isinstance(item, dict):
        raise ValueError(f"Subscription #{index} must be a table")

    billing_cycle = _required_str(item, "billing_cycle")
    if billing_cycle not in BILLING_CYCLES:
        raise ValueError(f"Subscription #{index} has unsupported billing_cycle: {billing_cycle}")

    payment_date = _required_str(item, "payment_date")
    try:
        date.fromisoformat(payment_date)
    except ValueError as exc:
        raise ValueError(f"Subscription #{index} has invalid payment_date: {payment_date}") from exc

    amount = item.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, int | float) or amount < 0:
        raise ValueError(f"Subscription #{index} requires non-negative amount")

    notify_enabled = item.get("notify_enabled", True)
    if not isinstance(notify_enabled, bool):
        raise ValueError(f"Subscription #{index} notify_enabled must be a boolean")

    return SubscriptionConfig(
        name=_required_str(item, "name"),
        category=_required_str(item, "category"),
        billing_cycle=billing_cycle,
        payment_date=payment_date,
        amount=float(amount),
        currency=_required_str(item, "currency").upper(),
        notify_enabled=notify_enabled,
    )


def _required_str(data: dict, key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing or invalid required field: {key}")
    return value.strip()


def _required_int(data: dict, key: str, minimum: int) -> int:
    value = data.get(key)
    if not isinstance(value, int) or value < minimum:
        raise ValueError(f"Missing or invalid required field: {key}")
    return value
