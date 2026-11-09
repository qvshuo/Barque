"""SQLite persistence. Each operation owns its connection and transaction."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from app.config import (
    AppConfig,
    Config,
    SubscriptionConfig,
    validate_settings,
    validate_subscription,
    validate_subscription_id,
)


class SubscriptionConflictError(ValueError):
    pass


# Business entities use explicit methods; the generic interface only serves caches.
RUNTIME_STATE_KEYS = {"exchange_rates"}


class Database:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "barque.sqlite3"
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id = 1), value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
                    billing_cycle TEXT NOT NULL, payment_date TEXT NOT NULL,
                    amount REAL NOT NULL CHECK(amount >= 0), currency TEXT NOT NULL,
                    notify_enabled INTEGER NOT NULL CHECK(notify_enabled IN (0, 1))
                );
                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS notification_attempts (
                    cycle_key TEXT PRIMARY KEY, status TEXT NOT NULL CHECK(status IN ('pending','success','failed')),
                    attempts INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL, retry_at REAL NOT NULL,
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS renewals (cycle_key TEXT PRIMARY KEY);
            """)
        self._initialize()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT 1 FROM settings WHERE id = 1").fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO settings VALUES (1, ?)", (json.dumps(asdict(AppConfig())),)
                )
                connection.execute("PRAGMA user_version=1")

    @staticmethod
    def _read_subscriptions(connection) -> list[SubscriptionConfig]:
        return [
            SubscriptionConfig(**{**dict(row), "notify_enabled": bool(row["notify_enabled"])})
            for row in connection.execute("SELECT * FROM subscriptions ORDER BY rowid")
        ]

    @staticmethod
    def _read_order(connection) -> dict:
        row = connection.execute("SELECT value FROM state WHERE key='display_order'").fetchone()
        return json.loads(row[0]) if row else {}

    def get_config(self) -> Config:
        with self.connect() as connection:
            connection.execute("BEGIN")
            settings = json.loads(
                connection.execute("SELECT value FROM settings WHERE id = 1").fetchone()[0]
            )
            return Config(
                AppConfig(**settings),
                self._ordered(self._read_subscriptions(connection), self._read_order(connection)),
            )

    @staticmethod
    def _ordered(subscriptions, order):
        categories = list(dict.fromkeys(item.category for item in subscriptions))
        saved_categories = [name for name in order.get("categories", []) if name in categories]
        categories = saved_categories + [
            name for name in categories if name not in saved_categories
        ]
        category_ranks = {name: index for index, name in enumerate(categories)}
        ranks = {value: index for index, value in enumerate(order.get("subscriptions", []))}
        return sorted(
            subscriptions,
            key=lambda item: (category_ranks[item.category], ranks.get(item.id, len(ranks))),
        )

    def update_settings(self, data: dict) -> AppConfig:
        settings = validate_settings(data)
        with self.connect() as connection:
            connection.execute(
                "UPDATE settings SET value = ? WHERE id = 1", (json.dumps(asdict(settings)),)
            )
        return settings

    def _subscription_groups(self, connection) -> dict:
        items = self._read_subscriptions(connection)
        order = self._read_order(connection)
        groups = {name: [] for name in order.get("categories", [])}
        for item in self._ordered(items, order):
            groups.setdefault(item.category, []).append(asdict(item))
        categories = [
            {"name": name, "subscriptions": subscriptions} for name, subscriptions in groups.items()
        ]
        revision = hashlib.sha256(json.dumps(categories, sort_keys=True).encode()).hexdigest()
        return {"categories": categories, "revision": revision}

    def get_subscription_groups(self) -> dict:
        with self.connect() as connection:
            connection.execute("BEGIN")
            return self._subscription_groups(connection)

    def save_subscription_groups(self, data: dict) -> dict:
        if not isinstance(data.get("categories"), list) or not isinstance(
            data.get("revision"), str
        ):
            raise ValueError("缺少有效的订阅分类或版本")
        categories, subscriptions, ids = [], [], set()
        for group in data["categories"]:
            if not isinstance(group, dict) or not isinstance(group.get("subscriptions"), list):
                raise ValueError("订阅分类格式无效")
            name = group.get("name")
            if (
                not isinstance(name, str)
                or not name.strip()
                or len(name.strip()) > 100
                or name.strip() in categories
            ):
                raise ValueError("分类名称不能为空、重复或超过 100 个字符")
            categories.append(name.strip())
            for item in group["subscriptions"]:
                if not isinstance(item, dict):
                    raise ValueError("订阅数据格式无效")
                subscription_id = validate_subscription_id(item.get("id"))
                if subscription_id in ids:
                    raise ValueError("订阅 ID 无效或重复")
                subscription = validate_subscription(
                    {**item, "category": name.strip()}, subscription_id
                )
                ids.add(subscription_id)
                subscriptions.append(subscription)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if self._subscription_groups(connection)["revision"] != data["revision"]:
                raise SubscriptionConflictError("订阅已在其他页面更新，请重新加载后再编辑")
            self._replace_subscriptions(connection, subscriptions)
            self._write_state(
                connection,
                "display_order",
                {"categories": categories, "subscriptions": [item.id for item in subscriptions]},
            )
            return self._subscription_groups(connection)

    def _replace_subscriptions(self, connection, subscriptions: list[SubscriptionConfig]):
        old = {
            row["id"]: (row["payment_date"], row["billing_cycle"])
            for row in connection.execute(
                "SELECT id, payment_date, billing_cycle FROM subscriptions"
            )
        }
        for subscription in subscriptions:
            if old.get(subscription.id) == (subscription.payment_date, subscription.billing_cycle):
                old.pop(subscription.id)
        for subscription_id in old:
            connection.execute(
                "DELETE FROM renewals WHERE cycle_key LIKE ?", (subscription_id + ":%",)
            )
        connection.execute("DELETE FROM subscriptions")
        for subscription in subscriptions:
            self._write_subscription(connection, subscription)

    def export_config(self) -> dict:
        with self.connect() as connection:
            connection.execute("BEGIN")
            settings = json.loads(
                connection.execute("SELECT value FROM settings WHERE id = 1").fetchone()[0]
            )
            groups = self._subscription_groups(connection)["categories"]
            return {
                "version": 1,
                "settings": settings,
                "categories": [group["name"] for group in groups],
                "subscriptions": [item for group in groups for item in group["subscriptions"]],
            }

    def import_config(self, data: dict) -> Config:
        if (
            type(data.get("version")) is not int
            or data["version"] != 1
            or not isinstance(data.get("settings"), dict)
            or not isinstance(data.get("subscriptions"), list)
        ):
            raise ValueError("配置文件格式或版本无效")
        if (
            not {
                "timezone",
                "check_interval_seconds",
                "remind_before_days",
                "notify_url",
                "reminder_time",
            }
            <= data["settings"].keys()
        ):
            raise ValueError("配置缺少必填设置")
        settings = validate_settings(data["settings"])
        subscriptions = []
        seen = set()
        for item in data["subscriptions"]:
            if not isinstance(item, dict):
                raise ValueError("订阅数据格式无效")
            if (
                not {
                    "id",
                    "name",
                    "category",
                    "billing_cycle",
                    "payment_date",
                    "amount",
                    "currency",
                    "notify_enabled",
                }
                <= item.keys()
            ):
                raise ValueError("订阅数据缺少必填字段")
            subscription_id = validate_subscription_id(item.get("id"))
            if subscription_id in seen:
                raise ValueError("订阅 ID 无效或重复")
            subscription = validate_subscription(item, subscription_id)
            seen.add(subscription_id)
            subscriptions.append(subscription)
        categories = data.get(
            "categories", list(dict.fromkeys(item.category for item in subscriptions))
        )
        if not isinstance(categories, list) or any(
            not isinstance(name, str) or not name.strip() or name != name.strip() or len(name) > 100
            for name in categories
        ):
            raise ValueError("配置中的分类格式无效")
        if len(set(categories)) != len(categories) or not {
            item.category for item in subscriptions
        } <= set(categories):
            raise ValueError("配置中的分类重复或缺失")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._replace_subscriptions(connection, subscriptions)
            self._write_state(
                connection,
                "display_order",
                {"categories": categories, "subscriptions": [item.id for item in subscriptions]},
            )
            connection.execute(
                "UPDATE settings SET value = ? WHERE id = 1", (json.dumps(asdict(settings)),)
            )
        return Config(settings, subscriptions)

    @staticmethod
    def _write_subscription(connection, subscription: SubscriptionConfig):
        values = asdict(subscription)
        connection.execute(
            """INSERT INTO subscriptions (id, name, category, billing_cycle, payment_date, amount, currency, notify_enabled)
            VALUES (:id, :name, :category, :billing_cycle, :payment_date, :amount, :currency, :notify_enabled)""",
            values,
        )

    @staticmethod
    def _write_state(connection, key: str, value):
        connection.execute(
            "INSERT INTO state VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )

    def read_state(self, key: str, default: dict) -> dict:
        if key not in RUNTIME_STATE_KEYS:
            raise ValueError("运行状态键无效")
        with self.connect() as connection:
            row = connection.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
            return json.loads(row[0]) if row else deepcopy(default)

    def write_state(self, key: str, value: dict):
        if key not in RUNTIME_STATE_KEYS:
            raise ValueError("运行状态键无效")
        with self.connect() as connection:
            self._write_state(connection, key, value)

    def load_renewals(self) -> dict:
        with self.connect() as connection:
            return {row[0]: True for row in connection.execute("SELECT cycle_key FROM renewals")}

    def set_renewed(self, cycle_key: str, renewed: bool):
        with self.connect() as connection:
            if renewed:
                connection.execute("INSERT OR IGNORE INTO renewals VALUES (?)", (cycle_key,))
            else:
                connection.execute("DELETE FROM renewals WHERE cycle_key = ?", (cycle_key,))

    def cleanup_renewals(self, active_keys: set[str], subscriptions: list[SubscriptionConfig]):
        anchors = {item.id: (item.payment_date, item.billing_cycle) for item in subscriptions}
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            unchanged = {
                row["id"]
                for row in connection.execute(
                    "SELECT id, payment_date, billing_cycle FROM subscriptions"
                )
                if anchors.get(row["id"]) == (row["payment_date"], row["billing_cycle"])
            }
            # Preserve marks created after a concurrent billing-anchor edit.
            expired = [
                (row[0],)
                for row in connection.execute("SELECT cycle_key FROM renewals")
                if row[0] not in active_keys and row[0].split(":", 1)[0] in unchanged
            ]
            connection.executemany("DELETE FROM renewals WHERE cycle_key = ?", expired)

    def claim_notification(self, cycle_key: str) -> bool:
        """Lease before I/O. A crash leaves pending work retryable after five minutes."""
        now = time.time()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM notification_attempts WHERE cycle_key=?", (cycle_key,)
            ).fetchone()
            if row and (row["status"] == "success" or row["retry_at"] > now):
                return False
            connection.execute(
                """INSERT INTO notification_attempts VALUES (?, 'pending', 1, ?, ?, NULL)
                ON CONFLICT(cycle_key) DO UPDATE SET status='pending', attempts=attempts+1,
                updated_at=excluded.updated_at, retry_at=excluded.retry_at, error=NULL""",
                (cycle_key, now, now + 300),
            )
            return True

    def finish_notification(self, cycle_key: str, success: bool):
        now = time.time()
        with self.connect() as connection:
            connection.execute(
                "UPDATE notification_attempts SET status=?, updated_at=?, retry_at=?, error=? WHERE cycle_key=?",
                (
                    "success" if success else "failed",
                    now,
                    now + 60,
                    None if success else "Bark 发送失败",
                    cycle_key,
                ),
            )
