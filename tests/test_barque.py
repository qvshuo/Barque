import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from waitress.adjustments import Adjustments
from waitress.proxy_headers import proxy_headers_middleware

from app.bark import send_bark_notification
from app.config import AppConfig, SubscriptionConfig
from app.database import Database, SubscriptionConflictError
from app.exchange import ExchangeService
from app.main import main
from app.scheduler import Scheduler
from app.subscriptions import (
    add_cycles,
    build_subscription_item,
    current_period_start,
    next_renewal_date,
)
from app.web import create_app


def subscription(**values):
    return SubscriptionConfig(
        **{
            **dict(
                name="测试",
                category="软件",
                billing_cycle="month",
                payment_date="2024-01-31",
                amount=10,
                currency="CNY",
                id="a" * 32,
            ),
            **values,
        }
    )


class BillingTests(unittest.TestCase):
    def test_calendar_boundaries(self):
        cases = [
            ("2024-01-31", "month", "2024-02-01", "2024-02-29"),
            ("2024-01-31", "month", "2024-03-01", "2024-03-31"),
            ("2023-01-31", "month", "2023-02-28", "2023-02-28"),
            ("2024-02-29", "year", "2025-02-28", "2025-02-28"),
            ("2024-02-29", "year", "2028-02-28", "2028-02-29"),
            ("2000-02-29", "year", "2100-02-28", "2100-02-28"),
            ("2024-01-31", "quarter", "2024-05-01", "2024-07-31"),
            ("2024-12-30", "week", "2025-01-01", "2025-01-06"),
            ("2026-01-31", "month", "2025-12-01", "2026-01-31"),
            ("2024-01-31", "month", "2044-03-01", "2044-03-31"),
        ]
        for anchor, cycle, today, expected in cases:
            with self.subTest(anchor=anchor, cycle=cycle, today=today):
                self.assertEqual(
                    next_renewal_date(date.fromisoformat(anchor), cycle, date.fromisoformat(today)),
                    date.fromisoformat(expected),
                )

    def test_progress_and_reminder_edges(self):
        def convert(amount, currency, cache):
            return amount

        for today, days, status, progress in [
            ("2024-02-21", 8, "active", 72.41),
            ("2024-02-22", 7, "expiring", 75.86),
            ("2024-02-29", 0, "expiring", 100),
            ("2024-03-01", 30, "active", 3.23),
        ]:
            with self.subTest(today=today):
                item = build_subscription_item(
                    subscription(), 7, {}, convert, date.fromisoformat(today)
                )
                self.assertEqual(
                    (item["days_left"], item["status"], item["progress_percent"]),
                    (days, status, progress),
                )
        item = build_subscription_item(
            subscription(payment_date="2025-01-31"), 7, {}, convert, date(2024, 12, 31)
        )
        self.assertEqual(item["progress_percent"], 0)

    def test_renewal_mark_is_independent_per_cycle(self):
        key = f"{'a' * 32}:2024-01-31:2024-02-29"

        def convert(*args):
            return None

        paid = build_subscription_item(
            subscription(currency="ZZZ"), 7, {}, convert, date(2024, 2, 29), {key: True}
        )
        next_item = build_subscription_item(
            subscription(), 7, {}, convert, date(2024, 3, 1), {key: True}
        )
        self.assertEqual(paid["button_state"]["status_kind"], "renewed")
        self.assertEqual(next_item["button_state"]["status_kind"], "normal")
        self.assertIsNone(paid["amount_cny"])
        self.assertEqual(paid["renewal_date"], "2024-02-29")

    def test_zero_day_reminder_and_anchored_periods(self):
        def convert(amount, currency, cache):
            return amount

        for cycle in ("week", "month", "quarter", "year"):
            for count in (1, 2, 12, 48, 100):
                with self.subTest(cycle=cycle, count=count):
                    anchor = date(2000, 2, 29)
                    due = add_cycles(anchor, cycle, count)
                    self.assertEqual(next_renewal_date(anchor, cycle, due), due)
                    self.assertEqual(
                        current_period_start(anchor, cycle, due),
                        add_cycles(anchor, cycle, count - 1),
                    )
        before = build_subscription_item(subscription(), 0, {}, convert, date(2024, 2, 28))
        due = build_subscription_item(subscription(), 0, {}, convert, date(2024, 2, 29))
        self.assertEqual(before["status"], "active")
        self.assertEqual(due["status"], "expiring")


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(Path(self.temp.name))
        self.scheduler = Scheduler(self.db)
        self.app = create_app(self.db, self.scheduler, initial_password="test-password")
        self.client = self.app.test_client()
        self.headers = {"X-Barque-Request": "1"}
        self.client.post(
            "/api/auth/login", json={"password": "test-password"}, headers=self.headers
        )

    def save(self, data):
        groups = self.db.get_subscription_groups()
        groups["categories"] = [{"name": data["category"], "subscriptions": [data]}]
        return self.db.save_subscription_groups(groups)

    def test_currency_format_decoupled_and_json_roundtrip(self):
        self.save(asdict(subscription(currency="zzz")))
        item = self.db.get_config().subscriptions[0]
        self.assertEqual(item.currency, "ZZZ")
        data = self.db.export_config()
        self.assertEqual(data["version"], 1)
        self.db.save_subscription_groups({**self.db.get_subscription_groups(), "categories": []})
        self.db.import_config(data)
        self.assertEqual(self.db.export_config(), data)
        reopened = Database(Path(self.temp.name))
        self.assertEqual(reopened.export_config(), data)
        groups = self.db.get_subscription_groups()
        groups["categories"][0]["subscriptions"][0]["currency"] = "ABC"
        self.db.save_subscription_groups(groups)
        with self.assertRaises(SubscriptionConflictError):
            self.db.save_subscription_groups(groups)
        with self.assertRaises(ValueError):
            self.save(asdict(subscription(currency="C1Y")))
        with self.assertRaises(ValueError):
            self.db.write_state("subscriptions", {})

    def test_notification_retry_and_pending_recovery(self):
        with patch("app.database.time.time", return_value=1000):
            self.assertTrue(self.db.claim_notification("cycle"))
            self.assertFalse(self.db.claim_notification("cycle"))
        with patch("app.database.time.time", return_value=1301):
            self.assertTrue(self.db.claim_notification("cycle"))
            self.db.finish_notification("cycle", False)
            self.assertFalse(self.db.claim_notification("cycle"))
        with patch("app.database.time.time", return_value=1362):
            self.assertTrue(self.db.claim_notification("cycle"))
            self.db.finish_notification("cycle", True)
        with patch("app.database.time.time", return_value=2000):
            self.assertFalse(self.db.claim_notification("cycle"))
            self.assertFalse(Database(Path(self.temp.name)).claim_notification("cycle"))
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM notification_attempts").fetchone()
            self.assertEqual((row["status"], row["attempts"]), ("success", 3))

    def test_concurrent_claim_only_one_sender(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            claimed = list(pool.map(lambda _: self.db.claim_notification("same-cycle"), range(8)))
        self.assertEqual(sum(claimed), 1)

    @patch("app.web.send_bark_notification", return_value=True)
    def test_test_bark_uses_unsaved_input(self, send):
        response = self.client.post(
            "/api/test-notification",
            json={"notify_url": "https://example.com/new-key"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(send.call_args.args[0], "https://example.com/new-key")
        self.assertEqual(self.db.get_config().app.notify_url, "")
        response = self.client.post(
            "/api/test-notification", json={"notify_url": "invalid"}, headers=self.headers
        )
        self.assertEqual(response.status_code, 400)

    def test_security_headers_and_proxy_cookie(self):
        for trust in (False, True):
            with self.subTest(trust_proxy=trust):

                def create_server(application, expected_secure=trust, **options):
                    settings = Adjustments(**options)
                    application.wsgi_app = proxy_headers_middleware(
                        application.wsgi_app,
                        trusted_proxy=settings.trusted_proxy,
                        trusted_proxy_headers=settings.trusted_proxy_headers,
                        clear_untrusted=settings.clear_untrusted_proxy_headers,
                    )

                    def check_request():
                        response = application.test_client().post(
                            "/api/auth/login",
                            json={"password": "test-password"},
                            headers={
                                **self.headers,
                                "X-Forwarded-Proto": "https",
                                "X-Forwarded-Host": "attacker.invalid",
                            },
                            environ_base={"REMOTE_ADDR": "127.0.0.1"},
                        )
                        self.assertEqual(response.status_code, 200)
                        cookie = response.headers["Set-Cookie"]
                        for flag in ("HttpOnly", "SameSite=Strict"):
                            self.assertIn(flag, cookie)
                        self.assertEqual("Secure" in cookie, expected_secure)
                        self.assertEqual(
                            "Strict-Transport-Security" in response.headers, expected_secure
                        )
                        self.assertIn("Content-Security-Policy", response.headers)

                    return Mock(run=Mock(side_effect=check_request))

                application = create_app(self.db, self.scheduler, initial_password="test-password")
                with (
                    patch.dict(
                        os.environ,
                        {"BARQUE_TRUST_PROXY": "1" if trust else "0", "BARQUE_SECURE_COOKIE": "0"},
                    ),
                    patch("app.main.Database", return_value=self.db),
                    patch("app.main.Scheduler"),
                    patch("app.main.create_app", return_value=application),
                    patch("app.main.create_server", side_effect=create_server),
                    patch("app.main.signal.signal"),
                    patch("app.main.logging.basicConfig"),
                ):
                    main()
        self.assertEqual(
            self.client.put(
                "/api/settings", data=b"x", content_type="application/octet-stream"
            ).status_code,
            403,
        )

    def test_json_import_failure_is_atomic_and_old_exports_still_work(self):
        self.save(asdict(subscription()))
        before = self.db.export_config()
        invalid = {
            **before,
            "subscriptions": [
                *before["subscriptions"],
                {**before["subscriptions"][0], "id": "invalid"},
            ],
        }
        with self.assertRaises(ValueError):
            self.db.import_config(invalid)
        self.assertEqual(self.db.export_config(), before)
        legacy = {key: value for key, value in before.items() if key != "categories"}
        legacy["subscriptions"][0]["id"] = "b" * 16
        self.db.import_config(legacy)
        self.assertEqual(self.db.export_config()["subscriptions"][0]["id"], "b" * 16)

    @patch("app.scheduler.today_in_timezone", return_value=date(2024, 2, 22))
    @patch("app.scheduler.local_now", return_value=datetime(2024, 2, 22, 9))
    @patch("app.scheduler.send_bark_notification", side_effect=[False, True])
    @patch("app.scheduler.ExchangeService.sync_once_per_day", side_effect=RuntimeError("offline"))
    def test_exchange_failure_does_not_block_reminder_and_retry(self, rates, send, now, today):
        self.save(asdict(subscription(currency="ZZZ")))
        self.db.update_settings(asdict(replace(AppConfig(), notify_url="https://example.com/key")))
        with patch("app.database.time.time", return_value=1000):
            self.scheduler.run_once()
        with patch("app.database.time.time", return_value=1061):
            self.scheduler.run_once()
            self.scheduler.run_once()
        self.assertEqual(send.call_count, 2)

    @patch("app.scheduler.today_in_timezone", return_value=date(2024, 2, 22))
    @patch("app.scheduler.ExchangeService.sync_once_per_day")
    @patch("app.scheduler.send_bark_notification", return_value=True)
    def test_reminder_time_boundary_and_disabled_or_paid(self, send, rates, today):
        self.db.update_settings(asdict(replace(AppConfig(), notify_url="https://example.com/key")))
        self.save(asdict(subscription()))
        item = self.db.get_config().subscriptions[0]
        with patch("app.scheduler.local_now", return_value=datetime(2024, 2, 22, 8, 59)):
            self.scheduler.run_once()
        send.assert_not_called()
        self.save(asdict(replace(item, notify_enabled=False)))
        with patch("app.scheduler.local_now", return_value=datetime(2024, 2, 22, 9)):
            self.scheduler.run_once()
        send.assert_not_called()
        self.save(asdict(item))
        key = f"{item.id}:2024-01-31:2024-02-29"
        self.db.set_renewed(key, True)
        with patch("app.scheduler.local_now", return_value=datetime(2024, 2, 22, 9)):
            self.scheduler.run_once()
        send.assert_not_called()
        self.db.set_renewed(key, False)
        with patch("app.scheduler.local_now", return_value=datetime(2024, 2, 22, 9)):
            self.scheduler.run_once()
        send.assert_called_once()

    @patch("app.exchange.httpx.get", side_effect=httpx.ConnectError("offline"))
    def test_failed_rates_keep_successful_cache(self, get):
        cache = {
            "date": "2024-01-01",
            "updated_at": "2024-01-01T00:00:00",
            "rates": {"CNY": 1, "USD": 0.14},
        }
        self.db.write_state("exchange_rates", cache)
        service = ExchangeService(self.db, "UTC")
        result = service.sync_once_per_day(date(2024, 1, 2), {"USD"})
        self.assertEqual(result, cache)
        self.assertEqual(self.db.read_state("exchange_rates", {}), cache)
        self.assertAlmostEqual(service.amount_to_cny(10, "USD", result), 71.43)

    @patch("app.exchange.httpx.get")
    def test_unknown_currency_does_not_poison_rates_request(self, get):
        get.return_value.json.return_value = {"rates": {"USD": 0.14}}
        service = ExchangeService(self.db, "UTC")
        cache = service.sync_once_per_day(date(2024, 1, 1), {"USD", "ZZZ"})
        self.assertEqual(get.call_args.kwargs["params"]["to"], "USD")
        self.assertIsNone(service.amount_to_cny(10, "ZZZ", cache))
        self.assertAlmostEqual(service.amount_to_cny(10, "USD", cache), 71.43)


class BarkTests(unittest.TestCase):
    @patch("app.bark.httpx.get")
    def test_bark_application_errors(self, get):
        get.return_value.json.return_value = {"code": 400}
        self.assertFalse(send_bark_notification("https://example.com/key", "测试", "内容"))
        get.return_value.json.return_value = {"code": 200}
        self.assertTrue(send_bark_notification("https://example.com/key", "测试", "内容"))
        get.side_effect = httpx.ConnectError("offline")
        self.assertFalse(send_bark_notification("https://example.com/key", "测试", "内容"))
        get.side_effect = httpx.InvalidURL("Invalid IDNA hostname")
        self.assertFalse(send_bark_notification("https://☃.com/key", "测试", "内容"))


if __name__ == "__main__":
    unittest.main()
