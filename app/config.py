"""Configuration models and validation for the administration API."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BILLING_CYCLES = {"week", "month", "quarter", "year"}


@dataclass(frozen=True)
class AppConfig:
    timezone: str = "Asia/Shanghai"
    check_interval_seconds: int = 3600
    remind_before_days: int = 7
    notify_url: str = ""
    reminder_time: str = "09:00"


@dataclass(frozen=True)
class SubscriptionConfig:
    name: str
    category: str
    billing_cycle: str
    payment_date: str
    amount: float
    currency: str
    notify_enabled: bool = True
    id: str = ""


@dataclass(frozen=True)
class Config:
    app: AppConfig
    subscriptions: list[SubscriptionConfig]


def required_str(data: dict, key: str, max_length: int = 200) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
        raise ValueError(f"{key} 不能为空且不能超过 {max_length} 个字符")
    return value.strip()


def validate_settings(data: dict) -> AppConfig:
    timezone = required_str(data, "timezone", 100)
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("请输入有效的 IANA 时区，例如 Asia/Shanghai") from exc
    for key, minimum, maximum in (("check_interval_seconds", 10, 86400), ("remind_before_days", 0, 365)):
        value = data.get(key)
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"{key} 必须是 {minimum} 至 {maximum} 之间的整数")
    notify_url = data.get("notify_url", "")
    if not isinstance(notify_url, str) or len(notify_url) > 2048:
        raise ValueError("Bark 地址无效")
    notify_url = notify_url.strip()
    if notify_url:
        parsed = urlparse(notify_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Bark 地址必须是有效的 HTTP(S) 地址，例如 https://api.day.app/你的密钥")
    reminder_time = data.get("reminder_time", "09:00")
    import re
    if not isinstance(reminder_time, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", reminder_time):
        raise ValueError("提醒时间须为有效的 HH:MM 时间")
    return AppConfig(timezone, data["check_interval_seconds"], data["remind_before_days"], notify_url, reminder_time)


def validate_subscription(data: dict, subscription_id: str = "") -> SubscriptionConfig:
    name = required_str(data, "name")
    category = required_str(data, "category", 100)
    billing_cycle = data.get("billing_cycle")
    if not isinstance(billing_cycle, str) or billing_cycle not in BILLING_CYCLES:
        raise ValueError("请选择有效的计费周期")
    payment_date = required_str(data, "payment_date", 10)
    try:
        if date.fromisoformat(payment_date).isoformat() != payment_date:
            raise ValueError
    except ValueError as exc:
        raise ValueError("付款日期必须是有效的 YYYY-MM-DD 日期") from exc
    amount = data.get("amount")
    if type(amount) not in (int, float) or not math.isfinite(amount) or not 0 <= amount <= 1_000_000_000:
        raise ValueError("费用必须是 0 至 1000000000 之间的有限数字")
    currency = required_str(data, "currency", 3).upper()
    if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
        raise ValueError("币种必须是三个英文字母，例如 CNY 或 USD")
    notify_enabled = data.get("notify_enabled", True)
    if type(notify_enabled) is not bool:
        raise ValueError("通知开关必须为布尔值")
    return SubscriptionConfig(name, category, billing_cycle, payment_date, float(amount), currency, notify_enabled, subscription_id)
