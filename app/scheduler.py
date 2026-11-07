"""Background subscription checks; configuration changes wake the scheduler."""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.bark import send_bark_notification
from app.database import Database
from app.exchange import ExchangeService
from app.renewals import is_cycle_renewed
from app.subscriptions import build_dashboard, collect_active_cycle_keys

logger = logging.getLogger(__name__)


def today_in_timezone(timezone_name: str) -> date:
    return datetime.now(ZoneInfo(timezone_name)).date()


def local_now(timezone_name: str) -> datetime:
    return datetime.now(ZoneInfo(timezone_name))


def now_iso(timezone_name: str) -> str:
    return datetime.now(ZoneInfo(timezone_name)).isoformat(timespec="seconds")


class Scheduler:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_check_at: str | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.run, name="barque-scheduler", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
        if self.thread:
            self.thread.join(timeout=20)

    def wake(self) -> None:
        self.wake_event.set()

    def run(self) -> None:
        while not self.stop_event.is_set():
            self.wake_event.clear()
            interval = 3600
            try:
                config = self.database.get_config()
                interval = config.app.check_interval_seconds
                self.run_once(config)
                now = local_now(config.app.timezone)
                hour, minute = map(int, config.app.reminder_time.split(":"))
                target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if target <= now:
                    target += timedelta(days=1)
                interval = min(interval, max(1, (target - now).total_seconds()))
            except Exception:
                logger.exception("Scheduler cycle failed")
            self.wake_event.wait(interval)

    def run_once(self, config=None) -> dict:
        config = config or self.database.get_config()
        today = today_in_timezone(config.app.timezone)
        exchange = ExchangeService(self.database, config.app.timezone, config.app.notify_url)
        exchange.sync_supported_currencies(today)
        rates_cache = exchange.sync_once_per_day(today, {subscription.currency for subscription in config.subscriptions})
        self.last_check_at = now_iso(config.app.timezone)
        dashboard = self._build_dashboard(config, exchange, rates_cache, today)
        self.database.cleanup_renewals(collect_active_cycle_keys(dashboard))
        if config.app.notify_url and local_now(config.app.timezone).strftime("%H:%M") >= config.app.reminder_time:
            self.send_due_notifications(config, dashboard)
        return dashboard

    def get_dashboard(self, config=None) -> dict:
        config = config or self.database.get_config()
        exchange = ExchangeService(self.database, config.app.timezone, config.app.notify_url)
        return self._build_dashboard(config, exchange, exchange.load_rates(), today_in_timezone(config.app.timezone))

    def _build_dashboard(self, config, exchange: ExchangeService, rates_cache: dict, today: date) -> dict:
        return build_dashboard(config, rates_cache, exchange.amount_to_cny, today, self.last_check_at, self.database.load_renewals())

    def send_due_notifications(self, config, dashboard: dict) -> None:
        log_data = self.database.read_state("notification_log", {"notifications": []})
        notifications = log_data.get("notifications", [])
        sent_keys = {item.get("dedupe_key") for item in notifications if isinstance(item, dict)}
        for group in dashboard["category_groups"]:
            for item in group["subscription_items"]:
                if self.stop_event.is_set():
                    return
                if item["status"] != "expiring":
                    continue
                latest = self.database.get_config()
                if latest.app != config.app:
                    return
                current = next((subscription for subscription in latest.subscriptions if subscription.id == item["subscription_id"]), None)
                if current is None or not current.notify_enabled:
                    continue
                # Do not send a stale snapshot after an edit changes its contents or billing anchor.
                if any(getattr(current, key) != item[key] for key in ("name", "category", "billing_cycle", "payment_date", "currency")) or round(current.amount, 2) != item["amount"]:
                    continue
                dedupe_key = f"{item['subscription_id']}:{item['payment_date']}:{item['renewal_date']}"
                if dedupe_key in sent_keys or is_cycle_renewed(self.database.load_renewals(), item["subscription_id"], item["payment_date"], item["renewal_date"]):
                    continue
                body = f"{item['name']} 将于 {item['renewal_date']} 续费，剩余 {item['days_left']} 天，费用 {item['currency']} {item['amount']:.2f}"
                if item["amount_cny"] is not None:
                    body += f"（约 ¥{item['amount_cny']:.2f}）"
                if send_bark_notification(config.app.notify_url, "订阅续费提醒", body):
                    notifications.append({"dedupe_key": dedupe_key, "subscription_id": item["subscription_id"], "payment_date": item["payment_date"], "renewal_date": item["renewal_date"], "sent_at": now_iso(config.app.timezone)})
                    sent_keys.add(dedupe_key)
                    # Persist each success so a later failure cannot resend earlier messages.
                    self.database.write_state("notification_log", {"notifications": notifications[-1000:]})
