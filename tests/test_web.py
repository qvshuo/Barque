"""HTTP rendering, authentication, content negotiation and cache regression."""

import gzip
import hashlib
import json
import re
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from app.config import AppConfig
from app.database import Database
from app.scheduler import Scheduler
from app.web import STATIC_DIR, create_app


class WebTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Database(Path(directory.name))
        self.scheduler = Scheduler(self.db)
        self.app = create_app(self.db, self.scheduler, initial_password="test-password")
        self.client = self.app.test_client()
        self.headers = {"X-Barque-Request": "1"}
        self.client.post(
            "/api/auth/login", json={"password": "test-password"}, headers={"X-Barque-Request": "1"}
        )

    def get(self, path, **kwargs):
        response = self.client.get(path, **kwargs)
        self.addCleanup(response.close)
        return response

    def head(self, path, **kwargs):
        response = self.client.head(path, **kwargs)
        self.addCleanup(response.close)
        return response

    @patch("app.bark.httpx.get")
    def test_test_bark_uses_unsaved_input(self, send):
        send.return_value.json.return_value = {"code": 200}
        url = "https://example.com/new-key?level=critical&call=1"
        response = self.client.post(
            "/api/test-notification",
            json={"notify_url": url},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("/new-key/", send.call_args.args[0])
        self.assertTrue(send.call_args.args[0].endswith("?level=critical&call=1"))
        self.assertEqual(self.db.get_config().app.notify_url, "")
        response = self.client.post(
            "/api/test-notification", json={"notify_url": "invalid"}, headers=self.headers
        )
        self.assertEqual(response.status_code, 400)

    def test_bark_query_settings_and_backup_roundtrip(self):
        for query in ("", "?level=timeSensitive", "?level=critical", "?level=critical&call=1"):
            with self.subTest(query=query):
                url = "https://example.com/key" + query
                settings = asdict(replace(AppConfig(), notify_url=url))
                response = self.client.put("/api/settings", json=settings, headers=self.headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json["notify_url"], url)
                backup = self.client.get("/api/configuration").json
                self.db.update_settings(asdict(AppConfig()))
                response = self.client.put("/api/configuration", json=backup, headers=self.headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.client.get("/api/settings").json["notify_url"], url)
                self.assertEqual(self.client.get("/api/configuration").json, backup)
        for url in (
            "ftp://example.com/key?level=critical",
            "https:///key?level=critical",
            "https://user:password@example.com/key?level=critical",
            "https://example.com:invalid/key?level=critical",
            "https://example.com/key?level=critical#fragment",
            "https://example.com/key?level=critical call=1",
            "https://example.com/key?value=" + "x" * 2048,
        ):
            with self.subTest(url=url):
                response = self.client.put(
                    "/api/settings",
                    json=asdict(replace(AppConfig(), notify_url=url)),
                    headers=self.headers,
                )
                self.assertEqual(response.status_code, 400)

    def test_production_assets_match_sources(self):
        from tools.prepare_assets import prepare

        prepare(check=True)

    def test_server_rendered_pages_and_unauthenticated_isolation(self):
        for path, text in [
            ("/", "概览"),
            ("/?page=subscriptions", "订阅"),
            ("/?page=settings", "Bark 地址"),
            ("/admin/", "订阅"),
        ]:
            response = self.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(text, response.text)
            self.assertIn("no-store", response.headers["Cache-Control"])
            self.assertNotIn("SpendingChart", response.text)
        anonymous = self.app.test_client()
        for path in ["/", "/?page=settings", "/admin/", "/?page=subscriptions"]:
            response = anonymous.get(path)
            self.assertIn('id="login-form"', response.text)
            self.assertNotIn("Bark 地址", response.text)
        self.assertEqual(anonymous.get("/api/settings").status_code, 401)

    def test_gzip_dynamic_head_and_api_contract(self):
        for path in ["/", "/?page=settings", "/?page=subscriptions", "/api/configuration"]:
            identity = self.get(path, headers={"Accept-Encoding": "identity"})
            packed = self.get(path, headers={"Accept-Encoding": "gzip"})
            if packed.headers.get("Content-Encoding") == "gzip":
                self.assertLess(len(packed.data), len(identity.data))
                self.assertEqual(gzip.decompress(packed.data), identity.data)
            else:
                self.assertNotIn("Content-Encoding", packed.headers)
                self.assertEqual(packed.data, identity.data)
            self.assertEqual(int(packed.headers["Content-Length"]), len(packed.data))
            self.assertIn("Accept-Encoding", packed.headers["Vary"])
            head = self.head(path, headers={"Accept-Encoding": "gzip"})
            self.assertEqual(head.data, b"")
            self.assertEqual(head.headers["Content-Length"], packed.headers["Content-Length"])
            self.assertEqual(
                head.headers.get("Content-Encoding"), packed.headers.get("Content-Encoding")
            )
            self.assertEqual(identity.headers["Cache-Control"], "no-store")
        dashboard = self.scheduler.get_dashboard(self.db.get_config())
        self.assertEqual(set(dashboard), {"summary", "category_groups"})
        self.assertIn("yearly_estimated_cny", dashboard["summary"])

    def test_small_response_does_not_expand_with_gzip(self):
        plain = self.get("/api/auth/session", headers={"Accept-Encoding": "identity"})
        response = self.get("/api/auth/session", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Content-Encoding", response.headers)
        self.assertEqual(response.data, plain.data)
        self.assertEqual(int(response.headers["Content-Length"]), len(response.data))
        self.assertIn("Accept-Encoding", response.headers["Vary"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        head = self.head("/api/auth/session", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(head.data, b"")
        self.assertNotIn("Content-Encoding", head.headers)
        self.assertEqual(head.headers["Content-Length"], response.headers["Content-Length"])

    def test_static_precompression_negotiation_head_and_cache(self):
        for filename in ["app.js", "app.css", "vendor/basecoat-1.1.0.min.css"]:
            digest = hashlib.sha256((STATIC_DIR / filename).read_bytes()).hexdigest()[:16]
            path = f"/assets/{filename}?v={digest}"
            plain = self.get(path, headers={"Accept-Encoding": "identity"})
            packed = self.get(path, headers={"Accept-Encoding": "gzip"})
            self.assertEqual(gzip.decompress(packed.data), plain.data)
            self.assertEqual(packed.mimetype, plain.mimetype)
            self.assertEqual(packed.headers["Content-Encoding"], "gzip")
            self.assertEqual(int(packed.headers["Content-Length"]), len(packed.data))
            self.assertIn("immutable", packed.headers["Cache-Control"])
            self.assertIn("max-age=31536000", packed.headers["Cache-Control"])
            self.assertIn("Accept-Encoding", packed.headers["Vary"])
            head = self.head(path, headers={"Accept-Encoding": "gzip"})
            self.assertEqual(head.data, b"")
            self.assertEqual(head.headers["Content-Length"], packed.headers["Content-Length"])
            self.assertEqual(head.headers["ETag"], packed.headers["ETag"])
            for enc in ["identity", "gzip;q=0", "gzip;q=0.5, identity;q=1"]:
                response = self.get(path, headers={"Accept-Encoding": enc})
                self.assertNotIn("Content-Encoding", response.headers)
                self.assertEqual(response.data, plain.data)
            for original, encoding in [(plain, "identity"), (packed, "gzip")]:
                response = self.get(
                    path,
                    headers={
                        "If-None-Match": original.headers["ETag"],
                        "Accept-Encoding": encoding,
                    },
                )
                self.assertEqual(response.status_code, 304)
                self.assertEqual(response.data, b"")
                self.assertIn("Accept-Encoding", response.headers["Vary"])
            for suffix in ["", "?v=outdated"]:
                response = self.get(f"/assets/{filename}{suffix}")
                self.assertNotIn("immutable", response.headers["Cache-Control"])
                self.assertIn("max-age=0", response.headers["Cache-Control"])
            response = self.get(path, headers={"Range": "bytes=0-15", "Accept-Encoding": "gzip"})
            self.assertEqual(response.status_code, 206)
            self.assertEqual(response.data, plain.data[:16])
            self.assertNotIn("Content-Encoding", response.headers)

    def test_binary_no_gzip_error_no_cache_traversal_and_integrity(self):
        for path in ["/logo.png", "/favicon.ico", "/apple-touch-icon.png", "/assets/logo.webp"]:
            response = self.get(path, headers={"Accept-Encoding": "gzip"})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("Content-Encoding", response.headers)
            self.assertNotIn("immutable", response.headers["Cache-Control"])
        for path in ["/assets/../../app/auth.py", "/assets/missing.js", "/api/missing"]:
            response = self.get(path)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        html = self.get("/").text
        for filename, version in re.findall(r'/assets/([^"?]+)\?v=([0-9a-f]+)', html):
            self.assertEqual(
                version, hashlib.sha256((STATIC_DIR / filename).read_bytes()).hexdigest()[:16]
            )
        for path in STATIC_DIR.rglob("*.gz"):
            self.assertEqual(gzip.decompress(path.read_bytes()), path.with_suffix("").read_bytes())

    def test_forbidden_identity_and_unsupported_content_codings(self):
        for path in ["/", "/assets/logo.webp", "/api/auth/session"]:
            response = self.get(path, headers={"Accept-Encoding": "br, identity;q=0"})
            self.assertEqual(response.status_code, 406)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        response = self.get("/", headers={"Accept-Encoding": "gzip;q=0, *;q=0"})
        self.assertEqual(response.status_code, 406)
        response = self.get("/api/auth/session", headers={"Accept-Encoding": "gzip, identity;q=0"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(gzip.decompress(response.data)), {"authenticated": True})

    def test_page_load_failure_has_safe_retry_and_preserves_api_errors(self):
        with patch(
            "app.scheduler.Scheduler.get_dashboard", side_effect=RuntimeError("private failure")
        ):
            with self.assertLogs(self.app.logger, level="ERROR"):
                response = self.get("/")
            self.assertEqual(response.status_code, 500)
            self.assertIn("无法加载页面", response.text)
            self.assertIn("重试", response.text)
            self.assertNotIn("private failure", response.text)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(self.get("/").status_code, 200)

    def test_escaped_html_and_fragment_protects_secrets(self):
        groups = self.db.get_subscription_groups()
        item = {
            "id": "a" * 32,
            "name": '<script>alert("x")</script>',
            "category": '<img src=x onerror="alert(1)">',
            "billing_cycle": "month",
            "payment_date": "2024-01-31",
            "amount": 12.34,
            "currency": "CNY",
            "notify_enabled": True,
        }
        groups["categories"] = [{"name": item["category"], "subscriptions": [item]}]
        self.db.save_subscription_groups(groups)
        response = self.get("/")
        self.assertIn("&lt;script&gt;", response.text)
        self.assertNotIn('<script>alert("x")</script>', response.text)
        fragment = self.get("/", headers={"X-Barque-Fragment": "dashboard"})
        self.assertNotIn("<!doctype", fragment.text)
        self.assertIn('id="dashboard"', fragment.text)
        anonymous = self.app.test_client().get("/", headers={"X-Barque-Fragment": "dashboard"})
        self.assertNotIn('id="dashboard"', anonymous.text)
        self.assertEqual(anonymous.headers["Cache-Control"], "no-store")


if __name__ == "__main__":
    unittest.main()
