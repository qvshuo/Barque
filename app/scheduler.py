"""Background thread that checks subscriptions and sends reminders."""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.services.config_loader import load_config
from app.services.exchange_service import ExchangeService, send_bark_notification
from app.services.log_store import read_json, trim_notifications, write_json_atomic
from app.services.renewal_state import cleanup_renewal_state, is_cycle_renewed, load_renewal_state, save_renewal_state
from app.services.subscription_service import build_dashboard, collect_active_cycle_keys, find_subscription_item


logger = logging.getLogger(__name__)


def today_in_timezone(timezone_name: str) -> date:
    return datetime.now(ZoneInfo(timezone_name)).date()


def now_iso(timezone_name: str) -> str:
    return datetime.now(ZoneInfo(timezone_name)).isoformat(timespec="seconds")


class Scheduler:
    def __init__(self, config_path: Path, data_dir: Path) -> None:
        self.config_path = config_path
        self.data_dir = data_dir
        self.notification_log_path = data_dir / "notification_log.json"
        self.exchange_cache_path = data_dir / "exchange_rates.json"
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_check_at: str | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self.run, name="barque-scheduler", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=10)

    def run(self) -> None:
        while not self.stop_event.is_set():
            interval = 3600
            try:
                config = load_config(self.config_path)
                interval = config.app.check_interval_seconds
                self.run_once(config)
            except Exception as exc:
                logger.exception("Scheduler cycle failed: %s", exc)
            self.stop_event.wait(interval)

    def run_once(self, config=None) -> dict:
        config = config or load_config(self.config_path)
        today = today_in_timezone(config.app.timezone)
        logger.info("Subscription check started")
        exchange = ExchangeService(self.exchange_cache_path, config.app.timezone, config.app.notify_url)
        rates_cache = exchange.sync_once_per_day(today, self.configured_currencies(config))
        self.last_check_at = now_iso(config.app.timezone)
        renewed_cycles = load_renewal_state(self.data_dir)
        dashboard = build_dashboard(config, rates_cache, exchange.amount_to_cny, today, self.last_check_at, renewed_cycles)
        self._cleanup_expired_renewal_state(dashboard)
        self.send_due_notifications(config, dashboard)
        trim_notifications(self.notification_log_path)
        logger.info("Subscription check finished")
        return dashboard

    def sync_exchange_rates(self, config=None) -> None:
        config = config or load_config(self.config_path)
        today = today_in_timezone(config.app.timezone)
        exchange = ExchangeService(self.exchange_cache_path, config.app.timezone, config.app.notify_url)
        exchange.sync_once_per_day(today, self.configured_currencies(config))

    def configured_currencies(self, config) -> set[str]:
        return {subscription.currency for subscription in config.subscriptions}

    def get_dashboard(self) -> dict:
        config = load_config(self.config_path)
        today = today_in_timezone(config.app.timezone)
        exchange = ExchangeService(self.exchange_cache_path, config.app.timezone, config.app.notify_url)
        rates_cache = exchange.load_rates()
        renewed_cycles = load_renewal_state(self.data_dir)
        dashboard = build_dashboard(config, rates_cache, exchange.amount_to_cny, today, self.last_check_at, renewed_cycles)
        self._cleanup_expired_renewal_state(dashboard)
        return dashboard

    def _cleanup_expired_renewal_state(self, dashboard: dict) -> None:
        active_keys = collect_active_cycle_keys(dashboard)
        state = load_renewal_state(self.data_dir)
        cleaned = cleanup_renewal_state(state, active_keys)
        if cleaned is not state:
            save_renewal_state(self.data_dir, cleaned)

    def send_due_notifications(self, config, dashboard: dict) -> None:
        log_data = read_json(self.notification_log_path, {"notifications": []})
        notifications = log_data.get("notifications", [])
        sent_keys = {item.get("dedupe_key") for item in notifications if isinstance(item, dict)}

        for group in dashboard["category_groups"]:
            for item in group["subscription_items"]:
                if item["status"] != "expiring":
                    continue
                if not item.get("notify_enabled", True):
                    logger.info("Bark notification disabled for subscription: %s", item["name"])
                    continue
                dedupe_key = f"{item['subscription_id']}:{item['payment_date']}:{item['renewal_date']}"
                if dedupe_key in sent_keys:
                    continue
                if is_cycle_renewed(load_renewal_state(self.data_dir), item["subscription_id"], item["payment_date"], item["renewal_date"]):
                    logger.info("Skipping notification for manually renewed subscription: %s", item["name"])
                    continue
                body = (
                    f"{item['name']} 将于 {item['renewal_date']} 续费，剩余 {item['days_left']} 天，"
                    f"费用 {item['currency']} {item['amount']:.2f}"
                )
                if item["amount_cny"] is not None:
                    body += f"（约 ¥{item['amount_cny']:.2f}）"
                success = send_bark_notification(config.app.notify_url, "订阅续费提醒", body)
                if success:
                    notifications.append(
                        {
                            "dedupe_key": dedupe_key,
                            "subscription_id": item["subscription_id"],
                            "payment_date": item["payment_date"],
                            "renewal_date": item["renewal_date"],
                            "sent_at": now_iso(config.app.timezone),
                        }
                    )
                    sent_keys.add(dedupe_key)

        log_data["notifications"] = notifications
        write_json_atomic(self.notification_log_path, log_data)
