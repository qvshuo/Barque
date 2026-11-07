"""SQLite persistence. Each operation owns its connection and transaction."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from app.config import AppConfig, Config, SubscriptionConfig, validate_settings, validate_subscription


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
            if connection.execute("SELECT 1 FROM settings WHERE id = 1").fetchone():
                return
            connection.execute("INSERT INTO settings VALUES (1, ?)", (json.dumps(asdict(AppConfig())),))
            connection.execute("PRAGMA user_version=1")

    def get_config(self) -> Config:
        with self.connect() as connection:
            connection.execute("BEGIN")
            settings = json.loads(connection.execute("SELECT value FROM settings WHERE id = 1").fetchone()[0])
            settings.pop("title", None)  # Ignore the removed setting in existing databases.
            rows = connection.execute("SELECT * FROM subscriptions ORDER BY rowid").fetchall()
            subscriptions = [SubscriptionConfig(**{**dict(row), "notify_enabled": bool(row["notify_enabled"])}) for row in rows]
            order = connection.execute("SELECT value FROM state WHERE key = 'display_order'").fetchone()
            return Config(AppConfig(**settings), self._ordered(subscriptions, json.loads(order[0]) if order else {}))

    @staticmethod
    def _ordered(subscriptions, order):
        categories = list(dict.fromkeys(item.category for item in subscriptions))
        saved_categories = [name for name in order.get("categories", []) if name in categories]
        categories = saved_categories + [name for name in categories if name not in saved_categories]
        category_ranks = {name: index for index, name in enumerate(categories)}
        ranks = {value: index for index, value in enumerate(order.get("subscriptions", []))}
        return sorted(subscriptions, key=lambda item: (category_ranks[item.category], ranks.get(item.id, len(ranks))))

    @staticmethod
    def _prune_order(connection, moved_id=None):
        row = connection.execute("SELECT value FROM state WHERE key = 'display_order'").fetchone()
        if row is None:
            return
        order = json.loads(row[0])
        rows = connection.execute("SELECT id, category FROM subscriptions").fetchall()
        categories = {row["category"] for row in rows}
        ids = {row["id"] for row in rows}
        order["categories"] = [name for name in order["categories"] if name in categories]
        ordered_ids = [value for value in order["subscriptions"] if value in ids and value != moved_id]
        ordered_ids.extend(row["id"] for row in rows if row["id"] not in ordered_ids and row["id"] != moved_id)
        if moved_id in ids:
            ordered_ids.append(moved_id)
        order["subscriptions"] = ordered_ids
        Database._write_state(connection, "display_order", order)

    def move(self, kind: str, target: str, direction: str):
        if not all(isinstance(value, str) for value in (kind, target, direction)) or kind not in {"category", "subscription"} or direction not in {"forward", "backward"}:
            raise ValueError("排序参数无效")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute("SELECT * FROM subscriptions ORDER BY rowid").fetchall()
            subscriptions = [SubscriptionConfig(**{**dict(row), "notify_enabled": bool(row["notify_enabled"])}) for row in rows]
            row = connection.execute("SELECT value FROM state WHERE key = 'display_order'").fetchone()
            subscriptions = self._ordered(subscriptions, json.loads(row[0]) if row else {})
            categories = list(dict.fromkeys(item.category for item in subscriptions))
            ids = [item.id for item in subscriptions]
            if kind == "category":
                values = categories
            else:
                current = next((item for item in subscriptions if item.id == target), None)
                if current is None:
                    raise ValueError("订阅已不存在，请刷新后重试")
                values = [item.id for item in subscriptions if item.category == current.category]
            if target not in values:
                raise ValueError("分类已不存在，请刷新后重试")
            index = values.index(target)
            neighbor = index + (-1 if direction == "forward" else 1)
            if 0 <= neighbor < len(values):
                if kind == "subscription":
                    left, right = ids.index(target), ids.index(values[neighbor])
                    ids[left], ids[right] = ids[right], ids[left]
                else:
                    categories[index], categories[neighbor] = categories[neighbor], categories[index]
            self._write_state(connection, "display_order", {"categories": categories, "subscriptions": ids})

    def supported_currencies(self) -> dict[str, str]:
        from app.currencies import DEFAULT_CURRENCIES
        return self.read_state("currency_catalog", {"currencies": DEFAULT_CURRENCIES})["currencies"]

    def update_settings(self, data: dict) -> AppConfig:
        settings = validate_settings(data)
        with self.connect() as connection:
            connection.execute("UPDATE settings SET value = ? WHERE id = 1", (json.dumps(asdict(settings)),))
        return settings

    def import_config(self, data: dict) -> Config:
        if type(data.get("version")) is not int or data["version"] != 1 or not isinstance(data.get("settings"), dict) or not isinstance(data.get("subscriptions"), list):
            raise ValueError("配置文件格式或版本无效")
        if not {"timezone", "check_interval_seconds", "remind_before_days", "notify_url", "reminder_time"} <= data["settings"].keys():
            raise ValueError("配置缺少必填设置")
        settings = validate_settings(data["settings"])
        currencies = self.supported_currencies()
        subscriptions = []
        seen = set()
        for item in data["subscriptions"]:
            if not isinstance(item, dict):
                raise ValueError("订阅数据格式无效")
            if not {"id", "name", "category", "billing_cycle", "payment_date", "amount", "currency", "notify_enabled"} <= item.keys():
                raise ValueError("订阅数据缺少必填字段")
            subscription_id = item.get("id")
            if not isinstance(subscription_id, str) or len(subscription_id) not in (16, 32) or any(c not in "0123456789abcdef" for c in subscription_id) or subscription_id in seen:
                raise ValueError("订阅 ID 无效或重复")
            subscription = validate_subscription(item, subscription_id)
            if subscription.currency not in currencies:
                raise ValueError("配置包含汇率源不支持的币种")
            seen.add(subscription_id)
            subscriptions.append(subscription)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            old = {row["id"]: (row["payment_date"], row["billing_cycle"]) for row in connection.execute("SELECT id, payment_date, billing_cycle FROM subscriptions")}
            for subscription in subscriptions:
                if old.get(subscription.id) == (subscription.payment_date, subscription.billing_cycle):
                    old.pop(subscription.id)
            for subscription_id in old:
                connection.execute("DELETE FROM renewals WHERE cycle_key LIKE ?", (subscription_id + ":%",))
            connection.execute("DELETE FROM state WHERE key = 'display_order'")
            connection.execute("DELETE FROM subscriptions")
            for subscription in subscriptions:
                self._write_subscription(connection, subscription)
            connection.execute("UPDATE settings SET value = ? WHERE id = 1", (json.dumps(asdict(settings)),))
        return Config(settings, subscriptions)

    @staticmethod
    def _write_subscription(connection, subscription: SubscriptionConfig):
        values = asdict(subscription)
        connection.execute("""INSERT INTO subscriptions (id, name, category, billing_cycle, payment_date, amount, currency, notify_enabled)
            VALUES (:id, :name, :category, :billing_cycle, :payment_date, :amount, :currency, :notify_enabled)""", values)

    def save_subscription(self, data: dict, subscription_id: str | None = None) -> SubscriptionConfig:
        with self.connect() as connection:
            if subscription_id:
                connection.execute("BEGIN IMMEDIATE")
                previous = connection.execute("SELECT * FROM subscriptions WHERE id = ?", (subscription_id,)).fetchone()
                if previous is None:
                    raise KeyError(subscription_id)
                # Editing subscription details must preserve a newer reminder preference.
                payload = {"notify_enabled": bool(previous["notify_enabled"]), **data}
                subscription = validate_subscription(payload, subscription_id)
                if subscription.currency not in self.supported_currencies():
                    raise ValueError("请选择汇率源支持的币种")
                connection.execute("""UPDATE subscriptions SET name=:name, category=:category, billing_cycle=:billing_cycle,
                    payment_date=:payment_date, amount=:amount, currency=:currency, notify_enabled=:notify_enabled WHERE id=:id""", asdict(subscription))
                if previous["category"] != subscription.category:
                    self._prune_order(connection, subscription_id)
                if previous["payment_date"] != subscription.payment_date or previous["billing_cycle"] != subscription.billing_cycle:
                    connection.execute("DELETE FROM renewals WHERE cycle_key LIKE ?", (subscription_id + ":%",))
            else:
                subscription = validate_subscription(data, uuid4().hex)
                if subscription.currency not in self.supported_currencies():
                    raise ValueError("请选择汇率源支持的币种")
                self._write_subscription(connection, subscription)
        return subscription

    def set_notify_enabled(self, subscription_id: str, enabled: bool) -> SubscriptionConfig:
        with self.connect() as connection:
            if not connection.execute("UPDATE subscriptions SET notify_enabled = ? WHERE id = ?", (enabled, subscription_id)).rowcount:
                raise KeyError(subscription_id)
            row = connection.execute("SELECT * FROM subscriptions WHERE id = ?", (subscription_id,)).fetchone()
            return SubscriptionConfig(**{**dict(row), "notify_enabled": bool(row["notify_enabled"])})

    def delete_subscription(self, subscription_id: str):
        with self.connect() as connection:
            if not connection.execute("DELETE FROM subscriptions WHERE id = ?", (subscription_id,)).rowcount:
                raise KeyError(subscription_id)
            connection.execute("DELETE FROM renewals WHERE cycle_key LIKE ?", (subscription_id + ":%",))
            self._prune_order(connection)

    @staticmethod
    def _write_state(connection, key: str, value):
        connection.execute("INSERT INTO state VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value, ensure_ascii=False)))

    def read_state(self, key: str, default: dict) -> dict:
        with self.connect() as connection:
            row = connection.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
            return json.loads(row[0]) if row else json.loads(json.dumps(default))

    def write_state(self, key: str, value: dict):
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

    def cleanup_renewals(self, active_keys: set[str]):
        with self.connect() as connection:
            expired = [(row[0],) for row in connection.execute("SELECT cycle_key FROM renewals") if row[0] not in active_keys]
            connection.executemany("DELETE FROM renewals WHERE cycle_key = ?", expired)
