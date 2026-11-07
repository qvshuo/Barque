"""Persistence, API and scheduler regression tests without network access."""

import json
import tempfile
import unittest
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from app.config import AppConfig, SubscriptionConfig
from app.database import Database
from app.renewals import build_button_state
from app.scheduler import Scheduler
from app.subscriptions import add_cycles, next_renewal_date
from app.web import create_app

HEADERS = {"X-Barque-Request": "1"}


class BarqueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name)
        self.db = Database(self.data_dir)
        catalog = patch("app.exchange.ExchangeService.sync_supported_currencies")
        catalog.start()
        self.addCleanup(catalog.stop)
        clock = patch("app.scheduler.local_now", return_value=datetime(2026, 11, 7, 12, 0))
        clock.start()
        self.addCleanup(clock.stop)
        self.scheduler = Scheduler(self.db)
        self.app = create_app(self.db, self.scheduler, initial_password="123456")
        self.app.testing = True
        self.client = self.app.test_client()
        self.client.post("/api/auth/login", json={"password": "123456"}, headers=HEADERS)
        self.payload = {"name": "iCloud+", "category": "云服务", "billing_cycle": "month", "payment_date": date.today().isoformat(), "amount": 21, "currency": "CNY", "notify_enabled": True}

    def request(self, method, path, data):
        return self.client.open(path, method=method, json=data, headers=HEADERS)

    def add(self):
        response = self.request("POST", "/api/subscriptions", self.payload)
        self.assertEqual(response.status_code, 201, response.json)
        return response.json

    def test_static_gzip_negotiation_and_cache(self):
        import gzip
        dist = self.data_dir / "frontend"
        assets = dist / "assets"
        assets.mkdir(parents=True)
        content = b"body { color: black; }" * 100
        (assets / "app-test.css").write_bytes(content)
        (assets / "app-test.css.gz").write_bytes(gzip.compress(content))
        app = create_app(self.db, self.scheduler, frontend_dist=dist, initial_password="123456")
        with app.test_client() as client:
            for encoding, compressed in (("gzip", True), ("gzip;q=0", False), ("identity", False)):
                response = client.get("/assets/app-test.css", headers={"Accept-Encoding": encoding})
                self.addCleanup(response.close)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers.get("Content-Encoding"), "gzip" if compressed else None)
                self.assertEqual(gzip.decompress(response.data) if compressed else response.data, content)
                self.assertEqual(response.mimetype, "text/css")
                self.assertIn("Accept-Encoding", response.vary)
                self.assertTrue(response.cache_control.immutable)
            response = client.get("/assets/missing.css", headers={"Accept-Encoding": "gzip"})
            self.assertEqual(response.status_code, 404)

    def test_manual_order_persists_and_stays_inside_category(self):
        first = self.add()
        second = self.db.save_subscription({**self.payload, "name": "Second"})
        third = self.db.save_subscription({**self.payload, "name": "Third", "category": "Other"})
        self.assertEqual(self.request("PUT", "/api/order", {"kind": "subscription", "target": second.id, "direction": "forward"}).status_code, 204)
        self.assertEqual([item.id for item in Database(self.data_dir).get_config().subscriptions], [second.id, first["id"], third.id])
        self.db.move("category", "Other", "forward")
        self.assertEqual([item.id for item in self.db.get_config().subscriptions], [third.id, second.id, first["id"]])
        self.db.move("subscription", second.id, "forward")
        self.assertEqual([item.id for item in self.db.get_config().subscriptions], [third.id, second.id, first["id"]])
        self.assertEqual(self.request("PUT", "/api/order", {"kind": [], "target": third.id, "direction": "forward"}).status_code, 400)
        config = self.db.get_config()
        self.db.import_config({"version": 1, "settings": asdict(config.app), "subscriptions": [asdict(item) for item in config.subscriptions]})
        self.assertEqual([item.id for item in self.db.get_config().subscriptions], [third.id, second.id, first["id"]])

    def test_order_drops_deleted_categories_and_appends_recategorized_items(self):
        first = self.db.save_subscription({**self.payload, "category": "A"})
        second = self.db.save_subscription({**self.payload, "category": "B"})
        third = self.db.save_subscription({**self.payload, "category": "C"})
        self.db.move("category", "B", "backward")
        self.db.delete_subscription(first.id)
        new = self.db.save_subscription({**self.payload, "category": "A"})
        self.assertEqual([item.category for item in self.db.get_config().subscriptions], ["C", "B", "A"])
        extra = self.db.save_subscription({**self.payload, "category": "B"})
        self.db.save_subscription({**self.payload, "category": "B"}, third.id)
        self.assertEqual([item.id for item in self.db.get_config().subscriptions], [second.id, extra.id, third.id, new.id])

    def test_fresh_install_needs_no_configuration(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        dashboard = self.client.get("/api/dashboard").json
        self.assertEqual(dashboard["title"], "Barque")
        self.assertEqual(dashboard["summary"]["total_subscription_count"], 0)
        self.assertTrue(self.db.path.exists())

    def test_crud_persists_and_has_stable_identity(self):
        subscription = self.add()
        settings = {**asdict(AppConfig()), "timezone": "Europe/London"}
        self.assertEqual(self.request("PUT", "/api/settings", settings).status_code, 200)
        self.assertTrue(self.scheduler.wake_event.is_set())
        response = self.request("PUT", f"/api/subscriptions/{subscription['id']}", {**self.payload, "name": "iCloud Family"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["id"], subscription["id"])
        reopened = Database(self.data_dir)
        self.assertEqual(reopened.get_config().app.timezone, "Europe/London")
        self.assertEqual(reopened.get_config().subscriptions[0].name, "iCloud Family")
        self.assertEqual(self.request("DELETE", f"/api/subscriptions/{subscription['id']}", {}).status_code, 204)
        self.assertEqual(self.request("DELETE", f"/api/subscriptions/{subscription['id']}", {}).status_code, 404)
        self.assertEqual(reopened.get_config().subscriptions, [])

    def test_validation_is_atomic(self):
        for invalid in ({"amount": -1}, {"amount": float('inf')}, {"amount": True}, {"billing_cycle": []}, {"payment_date": "2026-02-30"}, {"currency": "人民币"}, {"notify_enabled": "yes"}):
            response = self.request("POST", "/api/subscriptions", {**self.payload, **invalid})
            self.assertEqual(response.status_code, 400, response.json)
        self.assertEqual(self.db.get_config().subscriptions, [])
        before = self.db.get_config().app
        for invalid in ({"timezone": "Invalid/Timezone"}, {"remind_before_days": True}, {"check_interval_seconds": 0}, {"notify_url": "javascript:alert(1)"}):
            response = self.request("PUT", "/api/settings", {**asdict(before), **invalid})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.db.get_config().app, before)
        self.assertEqual(self.request("POST", "/api/subscriptions", []).status_code, 400)
        self.assertEqual(self.client.post('/api/subscriptions', json=self.payload).status_code, 403)
        self.assertEqual(self.client.post('/api/subscriptions', json=self.payload, headers={**HEADERS, 'Sec-Fetch-Site': 'cross-site'}).status_code, 403)

    def test_renewals_are_idempotent_and_survive_rename(self):
        subscription = self.add()
        dashboard = self.client.get("/api/dashboard").json
        item = dashboard["category_groups"][0]["subscription_items"][0]
        cycle = {key: item[key] for key in ("subscription_id", "payment_date", "renewal_date")}
        for _ in range(2):
            response = self.request("PUT", "/api/renewal-status", {**cycle, "renewed": True})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["status_kind"], "renewed")
        self.assertEqual(len(self.db.load_renewals()), 1)
        self.request("PUT", f"/api/subscriptions/{subscription['id']}", {**self.payload, "name": "Renamed"})
        dashboard = self.client.get("/api/dashboard").json
        self.assertEqual(dashboard["summary"]["expiring_subscription_count"], 0)
        self.assertEqual(dashboard["category_groups"][0]["subscription_items"][0]["button_state"]["status_kind"], "renewed")
        self.assertEqual(self.request("PUT", "/api/renewal-status", {**cycle, "renewed": False}).status_code, 200)
        self.assertEqual(self.db.load_renewals(), {})
        self.assertEqual(self.request("PUT", "/api/renewal-status", {**cycle, "renewal_date": "1900-01-01", "renewed": True}).status_code, 400)

    def test_reminders_wait_for_configured_local_time(self):
        self.add()
        self.db.update_settings({**asdict(AppConfig()), "notify_url": "https://api.day.app/example", "reminder_time": "09:30"})
        with patch("app.scheduler.send_bark_notification", return_value=True) as notify:
            with patch("app.scheduler.local_now", return_value=datetime(2026, 11, 7, 9, 29)):
                self.scheduler.run_once()
                notify.assert_not_called()
            with patch("app.scheduler.local_now", return_value=datetime(2026, 11, 7, 9, 30)):
                self.scheduler.run_once()
                self.scheduler.run_once()
                notify.assert_called_once()
        self.assertEqual(self.request("PUT", "/api/settings", {**asdict(AppConfig()), "reminder_time": "25:00"}).status_code, 400)

    def test_scheduler_deduplicates_and_respects_marked_and_disabled(self):
        self.add()
        self.db.update_settings({**asdict(AppConfig()), "notify_url": "https://api.day.app/example"})
        with patch("app.scheduler.send_bark_notification", return_value=True) as notify:
            self.scheduler.run_once()
            self.scheduler.run_once()
            self.assertEqual(notify.call_count, 1)
        self.db.write_state("notification_log", {"notifications": []})
        subscription = self.db.get_config().subscriptions[0]
        today = date.today().isoformat()
        self.db.set_renewed(f"{subscription.id}:{today}:{today}", True)
        with patch("app.scheduler.send_bark_notification", return_value=True) as notify:
            self.scheduler.run_once()
            notify.assert_not_called()
        self.db.set_renewed(f"{subscription.id}:{today}:{today}", False)
        self.db.save_subscription({**self.payload, "notify_enabled": False}, subscription.id)
        with patch("app.scheduler.send_bark_notification", return_value=True) as notify:
            self.scheduler.run_once()
            notify.assert_not_called()

    def test_reminder_preference_and_payment_mark_are_independent(self):
        subscription = self.add()
        item = self.scheduler.get_dashboard()["category_groups"][0]["subscription_items"][0]
        cycle = {key: item[key] for key in ("subscription_id", "payment_date", "renewal_date")}
        path = f"/api/subscriptions/{subscription['id']}/notifications"
        self.assertEqual(self.request("PUT", path, {"enabled": False}).status_code, 200)
        self.assertEqual(self.scheduler.get_dashboard()["summary"]["monthly_due_cny"], 21)
        self.assertEqual(self.request("PUT", "/api/renewal-status", {**cycle, "renewed": True}).status_code, 200)
        self.assertFalse(self.db.get_config().subscriptions[0].notify_enabled)
        marked = self.db.load_renewals()
        self.assertEqual(self.request("PUT", path, {"enabled": True}).status_code, 200)
        self.assertEqual(self.db.load_renewals(), marked)
        self.assertEqual(self.scheduler.get_dashboard()["summary"]["monthly_due_cny"], 0)
        self.db.update_settings({**asdict(AppConfig()), "notify_url": "https://api.day.app/example"})
        with patch("app.scheduler.send_bark_notification", return_value=True) as notify:
            self.scheduler.run_once()
            notify.assert_not_called()
        self.assertEqual(self.request("PUT", "/api/renewal-status", {**cycle, "renewed": False}).status_code, 200)
        self.assertTrue(self.db.get_config().subscriptions[0].notify_enabled)
        with patch("app.scheduler.send_bark_notification", return_value=True) as notify:
            self.scheduler.run_once()
            notify.assert_called_once()
            self.request("PUT", path, {"enabled": False})
            self.request("PUT", path, {"enabled": True})
            self.scheduler.run_once()
            notify.assert_called_once()
        for invalid in (None, "false", 0):
            self.assertEqual(self.request("PUT", path, {"enabled": invalid}).status_code, 400)
        self.assertTrue(self.db.get_config().subscriptions[0].notify_enabled)
        self.assertEqual(self.request("PUT", "/api/subscriptions/missing/notifications", {"enabled": False}).status_code, 404)

    def test_next_cycle_resets_payment_and_preserves_notification_preference(self):
        subscription = self.add()
        today = date.fromisoformat(self.payload["payment_date"])
        future = add_cycles(today, "month", 1)
        self.db.set_renewed(f"{subscription['id']}:{today}:{today}", True)
        self.db.update_settings({**asdict(AppConfig()), "notify_url": "https://api.day.app/example"})
        with patch("app.scheduler.today_in_timezone", return_value=future), patch("app.scheduler.send_bark_notification", return_value=True) as notify:
            dashboard = self.scheduler.run_once()
            self.assertNotEqual(dashboard["category_groups"][0]["subscription_items"][0]["button_state"]["status_kind"], "renewed")
            self.assertEqual(self.db.load_renewals(), {})
            self.assertTrue(self.db.get_config().subscriptions[0].notify_enabled)
            notify.assert_called_once()
        self.db.set_notify_enabled(subscription['id'], False)
        self.db.write_state("notification_log", {"notifications": []})
        with patch("app.scheduler.today_in_timezone", return_value=future), patch("app.scheduler.send_bark_notification", return_value=True) as notify:
            self.scheduler.run_once()
            notify.assert_not_called()

    def test_new_reminder_preference_survives_stale_edits_and_checks(self):
        subscription = self.add()
        self.db.update_settings({**asdict(AppConfig()), "notify_url": "https://api.day.app/example"})
        config = self.db.get_config()
        dashboard = self.scheduler.get_dashboard(config)
        self.db.set_notify_enabled(subscription['id'], False)
        details = {key: value for key, value in self.payload.items() if key != "notify_enabled"}
        response = self.request("PUT", f"/api/subscriptions/{subscription['id']}", {**details, "name": "Renamed"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["notify_enabled"])
        with patch("app.scheduler.send_bark_notification", return_value=True) as notify:
            self.scheduler.send_due_notifications(config, dashboard)
            notify.assert_not_called()

    def test_notification_test_and_failure(self):
        self.assertEqual(self.request("POST", "/api/test-notification", {}).status_code, 400)
        self.db.update_settings({**asdict(AppConfig()), "notify_url": "https://api.day.app/example"})
        with patch("app.web.send_bark_notification", return_value=True):
            self.assertEqual(self.request("POST", "/api/test-notification", {}).status_code, 200)
        with patch("app.web.send_bark_notification", return_value=False):
            self.assertEqual(self.request("POST", "/api/test-notification", {}).status_code, 502)

    def test_entire_application_requires_a_password(self):
        visitor = self.app.test_client()
        for path in ("/api/dashboard", "/api/settings", "/api/subscriptions", "/health"):
            self.assertEqual(visitor.get(path).status_code, 401, path)
        self.assertEqual(visitor.put("/api/settings", json=asdict(AppConfig()), headers=HEADERS).status_code, 401)
        self.assertEqual(visitor.get("/api/auth/session").json, {"authenticated": False})
        self.assertEqual(visitor.get("/admin").location, "/")
        self.assertEqual(visitor.post("/api/auth/login", json={"password": "incorrect"}, headers=HEADERS).status_code, 401)
        response = visitor.post("/api/auth/login", json={"password": "123456"}, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", response.headers["Set-Cookie"])
        self.assertEqual(visitor.get("/api/dashboard").status_code, 200)
        self.assertTrue(self.db.read_state("access", {})["password_hash"].startswith("scrypt:"))
        self.assertEqual(visitor.post("/api/auth/setup", json={"password": "changed"}, headers=HEADERS).status_code, 404)

    def test_sessions_survive_restart_and_logout_revokes_token(self):
        cookie = self.client.get_cookie("barque_session")
        reopened = create_app(Database(self.data_dir), Scheduler(self.db), initial_password="123456")
        visitor = reopened.test_client()
        visitor.set_cookie("barque_session", cookie.value)
        self.assertEqual(visitor.get("/api/dashboard").status_code, 200)
        self.assertEqual(visitor.post("/api/auth/logout", json={}, headers=HEADERS).status_code, 200)
        self.assertEqual(self.client.get("/api/dashboard").status_code, 401)
        self.assertEqual(visitor.post("/api/auth/login", json={"password": "123456"}, headers=HEADERS).status_code, 200)
        with self.db.connect() as connection:
            connection.execute("UPDATE sessions SET expires_at = 0")
        self.assertEqual(visitor.get("/api/dashboard").status_code, 401)

    def test_compose_password_change_revokes_all_sessions(self):
        cookie = self.client.get_cookie("barque_session")
        app = create_app(self.db, self.scheduler, initial_password="654321")
        visitor = app.test_client()
        visitor.set_cookie("barque_session", cookie.value)
        self.assertEqual(visitor.get("/api/dashboard").status_code, 401)
        self.assertEqual(visitor.post("/api/auth/login", json={"password": "123456"}, headers=HEADERS).status_code, 401)
        self.assertEqual(visitor.post("/api/auth/login", json={"password": "654321"}, headers=HEADERS).status_code, 200)
        self.assertEqual(visitor.put("/api/auth/password", json={}, headers=HEADERS).status_code, 404)

    def test_compose_password_required_and_login_rate_limit(self):
        for invalid in (None, "", "short"):
            with self.assertRaises(ValueError):
                create_app(self.db, self.scheduler, initial_password=invalid)
        visitor = self.app.test_client()
        for _ in range(10):
            self.assertEqual(visitor.post("/api/auth/login", json={"password": "wrong"}, headers=HEADERS).status_code, 401)
        self.assertEqual(visitor.post("/api/auth/login", json={"password": "wrong"}, headers=HEADERS).status_code, 429)

    def test_removed_title_is_ignored_for_existing_databases_and_api_writes(self):
        with self.db.connect() as connection:
            connection.execute("UPDATE settings SET value = ? WHERE id = 1", (json.dumps({**asdict(AppConfig()), "title": "Legacy custom title"}),))
        self.assertEqual(self.client.get("/api/dashboard").json["title"], "Barque")
        self.assertNotIn("title", self.client.get("/api/settings").json)
        response = self.request("PUT", "/api/settings", {**asdict(AppConfig()), "title": "New custom title"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("title", response.json)
        self.assertEqual(self.client.get("/api/dashboard").json["title"], "Barque")

    def test_configuration_export_import_is_atomic_and_preserves_matching_renewal(self):
        subscription = self.add()
        item = self.scheduler.get_dashboard()["category_groups"][0]["subscription_items"][0]
        key = f"{subscription['id']}:{item['payment_date']}:{item['renewal_date']}"
        self.db.set_renewed(key, True)
        exported = self.client.get("/api/configuration").json
        self.assertEqual(exported["version"], 1)
        self.assertEqual(exported["subscriptions"][0]["id"], subscription["id"])
        self.assertNotIn("password", exported)
        original = self.db.get_config()
        invalid = {**exported, "subscriptions": [exported["subscriptions"][0], {**exported["subscriptions"][0], "id": "bad"}]}
        self.assertEqual(self.request("PUT", "/api/configuration", invalid).status_code, 400)
        self.assertEqual(self.db.get_config(), original)
        self.assertTrue(self.db.load_renewals()[key])
        self.db.update_settings({**asdict(AppConfig()), "timezone": "Europe/London"})
        self.assertEqual(self.request("PUT", "/api/configuration", exported).status_code, 200)
        self.assertEqual(self.db.get_config(), original)
        self.assertTrue(self.db.load_renewals()[key])
        changed = {**exported, "subscriptions": [{**exported["subscriptions"][0], "billing_cycle": "year"}]}
        self.assertEqual(self.request("PUT", "/api/configuration", changed).status_code, 200)
        self.assertNotIn(key, self.db.load_renewals())
        self.assertEqual(self.request("PUT", "/api/configuration", {**exported, "settings": {}}).status_code, 400)

    def test_currency_catalog_and_default_window(self):
        self.assertEqual(AppConfig().remind_before_days, 7)
        currencies = self.client.get("/api/currencies").json
        codes = [item["code"] for item in currencies]
        self.assertEqual(codes, sorted(codes))
        self.assertIn("CNY", codes)
        for code in ("BTC", "AAA"):
            self.assertEqual(self.request("POST", "/api/subscriptions", {**self.payload, "currency": code}).status_code, 400)

    def test_due_badge_uses_the_configured_notification_window(self):
        self.assertEqual(build_button_state(7, False, 3)["status_kind"], "normal")
        self.assertEqual(build_button_state(4, False, 3)["status_kind"], "normal")
        self.assertEqual(build_button_state(3, False, 3)["status_kind"], "renewal_pending")
        self.assertEqual(build_button_state(0, False, 0)["status_kind"], "renewal_pending")
        self.assertEqual(build_button_state(1, False, 0)["status_kind"], "normal")
        self.assertEqual(build_button_state(10, False, 14)["status_kind"], "renewal_pending")
        self.assertEqual(build_button_state(100, True, 3)["status_kind"], "renewed")

    def test_stale_subscription_snapshot_does_not_send(self):
        subscription = self.add()
        self.db.update_settings({**asdict(AppConfig()), "notify_url": "https://api.day.app/example"})
        config = self.db.get_config()
        dashboard = self.scheduler.get_dashboard(config)
        self.db.save_subscription({**self.payload, "name": "Changed"}, subscription["id"])
        with patch("app.scheduler.send_bark_notification", return_value=True) as notify:
            self.scheduler.send_due_notifications(config, dashboard)
            notify.assert_not_called()

    def test_historical_billing_dates_preserve_calendar_anchors(self):
        from app.subscriptions import current_period_start
        self.assertEqual(next_renewal_date(date(1900, 1, 31), "month", date(2024, 2, 1)), date(2024, 2, 29))
        self.assertEqual(current_period_start(date(1900, 1, 31), "month", date(2024, 2, 29)), date(2024, 1, 31))
        self.assertEqual(next_renewal_date(date(1900, 1, 1), "week", date(2026, 11, 7)), date(2026, 11, 9))

    def test_calendar_anchors(self):
        self.assertEqual(next_renewal_date(date(2024, 2, 29), "year", date(2026, 1, 1)), date(2026, 2, 28))
        self.assertEqual(add_cycles(date(2026, 1, 31), "month", 2), date(2026, 3, 31))
        self.assertEqual(add_cycles(date(2026, 1, 31), "quarter", 1), date(2026, 4, 30))

    def test_old_files_are_ignored_on_fresh_install(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "subscriptions.toml").write_text("invalid TOML")
            for filename in ("renewal_state.json", "notification_log.json", "exchange_rates.json"):
                (path / filename).write_text("invalid JSON")
            database = Database(path)
            self.assertEqual(database.get_config().app, AppConfig())
            self.assertEqual(database.get_config().subscriptions, [])
            self.assertEqual(database.load_renewals(), {})
            self.assertEqual(database.read_state("notification_log", {}), {})
            self.assertEqual(database.read_state("exchange_rates", {}), {})
            self.assertEqual(Database(path).get_config().app, AppConfig())


class CurrencySyncTests(unittest.TestCase):
    def test_catalog_sync_caches_success_and_retains_last_catalog_on_failure(self):
        from app.exchange import ExchangeService
        import httpx
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory))
            exchange = ExchangeService(database, "Asia/Shanghai", "")
            catalog = {"USD": "US Dollar", "CNY": "Chinese Renminbi", "EUR": "Euro"}
            response = httpx.Response(200, json=catalog, request=httpx.Request("GET", "https://api.frankfurter.dev/v1/currencies"))
            with patch("app.exchange.httpx.get", return_value=response) as get:
                self.assertEqual(exchange.sync_supported_currencies(date(2026, 11, 7)), catalog)
                exchange.sync_supported_currencies(date(2026, 11, 7))
                get.assert_called_once()
            with patch("app.exchange.httpx.get", side_effect=httpx.ConnectError("offline")):
                self.assertEqual(exchange.sync_supported_currencies(date(2026, 11, 8)), catalog)
                self.assertEqual(database.read_state("currency_catalog", {})["date"], "2026-11-07")
            self.assertEqual(database.supported_currencies(), catalog)


if __name__ == "__main__":
    unittest.main()
