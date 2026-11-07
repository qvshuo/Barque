"""Dashboard builder: computes renewal dates, status and totals."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from app.config import Config, SubscriptionConfig
from app.renewals import build_button_state, is_cycle_renewed


# Approximate billing cycles per year for yearly-cost estimation.
YEARLY_MULTIPLIERS = {
    "week": 52,
    "month": 12,
    "quarter": 4,
    "year": 1,
}

# relativedelta keyword for each supported billing cycle.
CYCLE_RELATIVEDELTA_ARGS = {
    "week": "weeks",
    "month": "months",
    "year": "years",
}


def now_display(timezone_name: str) -> str:
    current = datetime.now(ZoneInfo(timezone_name))
    return f"{current.year}年{current.month}月{current.day}日{current.hour}点{current.minute:02d}分"


def cycle_index(payment_date: date, billing_cycle: str, target: date) -> int:
    if target <= payment_date:
        return 0
    if billing_cycle == "week":
        return (target - payment_date).days // 7
    months = (target.year - payment_date.year) * 12 + target.month - payment_date.month
    return months // {"month": 1, "quarter": 3, "year": 12}[billing_cycle]


def next_renewal_date(payment_date: date, billing_cycle: str, today: date) -> date:
    count = cycle_index(payment_date, billing_cycle, today)
    renewal = add_cycles(payment_date, billing_cycle, count)
    if renewal < today:
        renewal = add_cycles(payment_date, billing_cycle, count + 1)
    return renewal


def current_period_start(payment_date: date, billing_cycle: str, renewal_date: date) -> date:
    count = cycle_index(payment_date, billing_cycle, renewal_date)
    return add_cycles(payment_date, billing_cycle, max(0, count - 1))


def add_cycles(payment_date: date, billing_cycle: str, cycle_count: int) -> date:
    if billing_cycle == "quarter":
        return payment_date + relativedelta(months=cycle_count * 3)
    return payment_date + relativedelta(**{CYCLE_RELATIVEDELTA_ARGS[billing_cycle]: cycle_count})


def build_subscription_id(subscription: SubscriptionConfig) -> str:
    if subscription.id:
        return subscription.id
    source = "|".join(
        [
            subscription.name,
            subscription.payment_date,
            subscription.billing_cycle,
        ]
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def build_dashboard(config: Config, rates_cache: dict, amount_to_cny, today: date, last_check_at: str | None = None, renewed_cycles: dict | None = None) -> dict:
    items = []
    expiring_count = 0
    monthly_due_cny = 0.0
    yearly_estimated_cny = 0.0
    renewed_cycles = renewed_cycles or {}

    for subscription in config.subscriptions:
        item = build_subscription_item(subscription, config.app.remind_before_days, rates_cache, amount_to_cny, today, renewed_cycles)
        items.append(item)
        if item["status"] == "expiring" and item["button_state"]["status_kind"] != "renewed":
            expiring_count += 1
        if item["renewal_date"][:7] == today.isoformat()[:7] and item["amount_cny"] is not None and item["button_state"]["status_kind"] != "renewed":
            monthly_due_cny += item["amount_cny"]
        if item["yearly_estimated_cny"] is not None:
            yearly_estimated_cny += item["yearly_estimated_cny"]

    category_groups = build_category_groups(items)
    summary = {
        "total_subscription_count": len(items),
        "total_category_count": len(category_groups),
        "expiring_subscription_count": expiring_count,
        "remind_before_days": config.app.remind_before_days,
        "monthly_due_cny": round(monthly_due_cny, 2),
        "yearly_estimated_cny": round(yearly_estimated_cny, 2),
        "last_check_at": last_check_at,
        "last_check_display": now_display(config.app.timezone),
        "exchange_rate_updated_at": rates_cache.get("updated_at"),
    }
    return {"summary": summary, "category_groups": category_groups}


def collect_active_cycle_keys(dashboard: dict) -> set[str]:
    keys = set()
    for group in dashboard["category_groups"]:
        for item in group["subscription_items"]:
            keys.add(f"{item['subscription_id']}:{item['payment_date']}:{item['renewal_date']}")
    return keys


def find_subscription_item(dashboard: dict, subscription_id: str, payment_date: str, renewal_date: str) -> dict | None:
    for group in dashboard["category_groups"]:
        for item in group["subscription_items"]:
            if (
                item["subscription_id"] == subscription_id
                and item["payment_date"] == payment_date
                and item["renewal_date"] == renewal_date
            ):
                return item
    return None


def build_subscription_item(subscription: SubscriptionConfig, remind_before_days: int, rates_cache: dict, amount_to_cny, today: date, renewed_cycles: dict | None = None) -> dict:
    payment_date = date.fromisoformat(subscription.payment_date)
    renewal_date = next_renewal_date(payment_date, subscription.billing_cycle, today)
    period_start = current_period_start(payment_date, subscription.billing_cycle, renewal_date)
    total_days = max((renewal_date - period_start).days, 1)
    used_days = (today - period_start).days
    progress_percent = round(max(0, min(used_days / total_days * 100, 100)), 2)
    days_left = (renewal_date - today).days
    reminder_start = renewal_date - timedelta(days=remind_before_days)

    subscription_id = build_subscription_id(subscription)
    cycle_renewed = is_cycle_renewed(renewed_cycles or {}, subscription_id, payment_date.isoformat(), renewal_date.isoformat())

    amount_cny = amount_to_cny(subscription.amount, subscription.currency, rates_cache)
    yearly_estimated_cny = None if amount_cny is None else round(amount_cny * YEARLY_MULTIPLIERS[subscription.billing_cycle], 2)
    return {
        "subscription_id": subscription_id,
        "name": subscription.name,
        "category": subscription.category,
        "billing_cycle": subscription.billing_cycle,
        "payment_date": payment_date.isoformat(),
        "period_start": period_start.isoformat(),
        "renewal_date": renewal_date.isoformat(),
        "days_left": days_left,
        "progress_percent": progress_percent,
        "status": "expiring" if today >= reminder_start else "active",
        "amount": round(subscription.amount, 2),
        "currency": subscription.currency,
        "amount_cny": amount_cny,
        "yearly_estimated_cny": yearly_estimated_cny,
        "notify_enabled": subscription.notify_enabled,
        "button_state": build_button_state(days_left, cycle_renewed, remind_before_days),
    }


def build_category_groups(items: list[dict]) -> list[dict]:
    grouped = {}
    for item in items:
        grouped.setdefault(item["category"], []).append(item)

    groups = []
    for category_name, subscription_items in grouped.items():
        groups.append(
            {
                "category_name": category_name,
                "subscription_count": len(subscription_items),
                "yearly_estimated_cny": round(sum(item["yearly_estimated_cny"] or 0 for item in subscription_items), 2),
                "subscription_items": subscription_items,
            }
        )
    return groups
