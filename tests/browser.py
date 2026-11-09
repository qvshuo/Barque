"""Browser regression against a disposable database: python -m tests.browser."""

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from app.database import Database
from app.scheduler import Scheduler
from app.web import create_app
from tests.fixtures import configuration

PASSWORD = "browser-test-password"
HEADERS = {"X-Barque-Request": "1"}


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="barque-browser-")
        database = Database(Path(cls.directory.name))
        cls.app = create_app(database, Scheduler(database), initial_password=PASSWORD)
        cls.server = make_server("127.0.0.1", 0, cls.app, threaded=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.playwright = sync_playwright().start()
        options = {"headless": True}
        if os.environ.get("BARQUE_TEST_CHROMIUM"):
            options["executable_path"] = os.environ["BARQUE_TEST_CHROMIUM"]
        cls.browser = cls.playwright.chromium.launch(**options)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.directory.cleanup()

    def setUp(self):
        self.context = self.browser.new_context(base_url=self.url, accept_downloads=True)
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.addCleanup(lambda: self.assertEqual(self.errors, []))
        self.api = self.context.request
        self.assertTrue(
            self.api.post("/api/auth/login", headers=HEADERS, data={"password": PASSWORD}).ok
        )
        self.assertTrue(
            self.api.put("/api/configuration", headers=HEADERS, data=configuration()).ok
        )
        for group in self.api.get("/api/dashboard").json()["category_groups"]:
            for item in group["subscription_items"]:
                if item["button_state"]["status_kind"] == "renewed":
                    self.assertTrue(
                        self.api.put(
                            "/api/renewal-status",
                            headers=HEADERS,
                            data={
                                "subscription_id": item["subscription_id"],
                                "payment_date": item["payment_date"],
                                "renewal_date": item["renewal_date"],
                                "renewed": False,
                            },
                        ).ok
                    )
        self.page.goto("/")

    def navigate(self, name):
        self.page.get_by_role("link", name=name, exact=True).click()
        expect(
            self.page.get_by_role(
                "heading", name=name if name != "首页" else "我的订阅", exact=True
            )
        ).to_be_visible()

    def save(self):
        self.page.get_by_role("button", name="保存", exact=True).click()
        expect(self.page.get_by_text("未保存", exact=True)).to_be_hidden()

    def test_filter_search_renewal_and_chart_removal(self):
        page = self.page
        self.assertEqual(page.locator("canvas,.recharts-wrapper").count(), 0)
        select = page.get_by_role("combobox", name="筛选分类")
        select.select_option(label="分类2")
        expect(page.get_by_role("region", name="分类1", exact=True)).to_be_hidden()
        renew = page.get_by_role("button", name="订阅2：标记已付", exact=True)
        renew.click()
        paid = page.get_by_role("button", name="订阅2：已付，点击撤销", exact=True)
        expect(paid).to_have_attribute("aria-pressed", "true")
        paid.click()
        expect(renew).to_have_attribute("aria-pressed", "false")
        select.select_option("")
        page.get_by_role("searchbox").fill("订阅7")
        expect(page.get_by_role("region", name="分类7", exact=True)).to_be_visible()
        expect(page.get_by_role("region", name="分类2", exact=True)).to_be_hidden()
        page.get_by_role("searchbox").fill("无匹配")
        expect(page.get_by_text("没有匹配的订阅", exact=True)).to_be_visible()

    def test_native_fields_guard_and_unknown_currency(self):
        self.navigate("订阅")
        group = self.page.get_by_role("group", name="订阅1", exact=True)
        group.get_by_label("计费周期", exact=True).select_option("quarter")
        group.get_by_label("付款日期", exact=True).fill("2024-01-30")
        group.get_by_role("switch", name="提醒").uncheck()
        group.get_by_label("币种", exact=True).fill("zzz")
        self.page.get_by_role("link", name="设置", exact=True).click()
        dialog = self.page.get_by_role("alertdialog")
        expect(dialog.locator("article")).to_be_visible()
        expect(dialog.get_by_role("button", name="继续编辑")).to_be_focused()
        self.page.keyboard.press("Escape")
        expect(dialog).not_to_have_attribute("open", "")
        self.save()
        item = self.api.get("/api/subscriptions").json()[0]
        self.assertEqual(
            (item["billing_cycle"], item["payment_date"], item["currency"], item["notify_enabled"]),
            ("quarter", "2024-01-30", "ZZZ", False),
        )
        self.page.reload()
        expect(self.page.get_by_label("付款日期", exact=True).first).to_have_value("2024-01-30")

    def test_background_refresh_recovers_and_preserves_filter(self):
        page = self.page
        page.get_by_role("combobox", name="筛选分类").select_option(label="分类2")
        page.get_by_role("searchbox").fill("订阅2")
        requests = []

        def refresh(route):
            requests.append(route.request.url)
            if len(requests) == 1:
                route.fulfill(status=503, body="offline")
            else:
                route.continue_()

        page.route("**/", refresh)
        page.evaluate("dispatchEvent(new Event('focus'));dispatchEvent(new Event('focus'))")
        page.wait_for_timeout(250)
        expect(page.get_by_role("heading", name="订阅2", exact=True)).to_be_visible()
        page.evaluate("dispatchEvent(new Event('focus'))")
        page.wait_for_timeout(250)
        expect(page.get_by_role("searchbox")).to_have_value("订阅2")
        expect(page.get_by_role("combobox", name="筛选分类")).to_have_value("分类2")
        self.assertEqual(len(requests), 2)

    def test_batch_add_order_delete_empty_category(self):
        self.navigate("订阅")
        page = self.page
        page.get_by_role("button", name="添加分类", exact=False).click()
        group = page.get_by_role("region", name="新分类", exact=True)
        group.get_by_label("分类", exact=True).fill("新增分类")
        group = page.get_by_role("region", name="新增分类", exact=True)
        group.get_by_role("button", name="添加订阅", exact=False).click()
        row = group.get_by_role("group", name="新订阅", exact=True)
        row.get_by_label("名称", exact=True).fill("新增订阅")
        row = group.get_by_role("group", name="新增订阅", exact=True)
        row.get_by_label("币种", exact=True).fill("USD")
        row.get_by_label("金额", exact=True).fill("12.34")
        self.save()
        result = self.api.get("/api/subscription-groups").json()
        self.assertEqual(result["categories"][-1]["subscriptions"][0]["amount"], 12.34)
        group.get_by_role("button", name="新增分类 分类 上移", exact=True).click()
        row.get_by_role("button", name="新增订阅 删除", exact=True).click()
        self.save()
        result = self.api.get("/api/subscription-groups").json()
        self.assertEqual(result["categories"][-2], {"name": "新增分类", "subscriptions": []})
        page.reload()
        expect(page.get_by_role("region", name="新增分类", exact=True)).to_be_visible()

    def test_bark_unsaved_success_failure_and_settings_save(self):
        self.navigate("设置")
        page = self.page
        reveal = page.locator("#reveal")
        for visible in (True, False):
            reveal.click()
            expect(page.get_by_label("Bark 地址", exact=True)).to_have_attribute(
                "type", "text" if visible else "password"
            )
            expect(reveal).to_have_attribute("aria-pressed", str(visible).lower())
            expect(reveal).to_have_attribute(
                "aria-label", "隐藏推送地址" if visible else "显示推送地址"
            )
            expect(reveal.locator("[data-eye-closed]")).to_be_visible() if visible else expect(
                reveal.locator("[data-eye-open]")
            ).to_be_visible()
        page.get_by_label("Bark 地址", exact=True).fill("https://example.com/unsaved-key")

        def notification(route):
            self.assertEqual(
                route.request.post_data_json, {"notify_url": "https://example.com/unsaved-key"}
            )
            route.fulfill(json={"message": "测试通知已发送"})

        page.route("**/api/test-notification", notification)
        page.get_by_role("button", name="测试通知", exact=True).click()
        expect(page.get_by_text("已发送", exact=True)).to_be_visible()
        page.unroute("**/api/test-notification")
        page.route(
            "**/api/test-notification",
            lambda route: route.fulfill(
                status=502, json={"error": "发送失败，请检查 Bark 地址和网络连接"}
            ),
        )
        page.get_by_role("button", name="测试通知", exact=True).click()
        expect(page.get_by_text("发送失败，请检查 Bark 地址和网络连接", exact=True)).to_be_visible()
        self.assertEqual(self.api.get("/api/settings").json()["notify_url"], "")
        page.get_by_label("时区", exact=True).fill("UTC")
        page.get_by_label("提醒时间", exact=True).fill("23:59")
        self.save()
        self.assertEqual(self.api.get("/api/settings").json()["reminder_time"], "23:59")

    def test_backup_restore_and_clear_save_error(self):
        self.navigate("设置")
        page = self.page
        with page.expect_download() as download:
            page.get_by_role("button", name="导出", exact=True).click()
        backup = json.loads(Path(download.value.path()).read_text())
        self.assertEqual(backup["version"], 1)
        page.get_by_label("时区", exact=True).fill("UTC")
        page.route(
            "**/api/settings",
            lambda route: route.fulfill(status=400, json={"error": "设置保存失败"}),
        )
        page.get_by_role("button", name="保存", exact=True).click()
        expect(page.get_by_text("设置保存失败", exact=True)).to_be_visible()
        page.get_by_label("时区", exact=True).fill("Asia/Shanghai")
        with page.expect_file_chooser() as chooser:
            page.get_by_role("button", name="导入", exact=True).click()
        chooser.value.set_files(
            {
                "name": "config.json",
                "mimeType": "application/json",
                "buffer": json.dumps(backup).encode(),
            }
        )
        page.get_by_role("button", name="确认导入", exact=True).click()
        expect(page.get_by_text("配置已导入并生效", exact=True)).to_be_visible()
        expect(page.get_by_text("设置保存失败", exact=True)).to_be_hidden()
        self.assertEqual(self.api.get("/api/configuration").json(), backup)

    def test_conflict_preserves_draft_and_reload_requires_confirmation(self):
        self.navigate("订阅")
        page = self.page
        page.get_by_label("名称", exact=True).first.fill("本地草稿")
        self.api.put(
            "/api/subscriptions/" + "1".zfill(32),
            headers=HEADERS,
            data={**configuration()["subscriptions"][0], "name": "其他窗口"},
        )
        page.get_by_role("button", name="保存", exact=True).click()
        reload = page.get_by_role("button", name="重新加载", exact=True)
        expect(reload).to_be_visible()
        expect(reload).to_have_class("btn reload")
        expect(reload).to_have_attribute("data-variant", "outline")
        expect(page.get_by_label("名称", exact=True).first).to_have_value("本地草稿")
        page.get_by_role("button", name="重新加载", exact=True).click()
        page.get_by_role("button", name="放弃更改", exact=True).click()
        expect(page.get_by_label("名称", exact=True).first).to_have_value("其他窗口")

    def test_navigation_history_refresh_and_legacy_urls(self):
        self.navigate("订阅")
        self.navigate("设置")
        self.page.go_back()
        expect(self.page.get_by_role("heading", name="订阅", exact=True)).to_be_visible()
        self.page.go_forward()
        expect(self.page.get_by_role("heading", name="设置", exact=True)).to_be_visible()
        self.page.reload()
        expect(self.page.get_by_role("heading", name="设置", exact=True)).to_be_visible()
        self.assertEqual(self.page.evaluate("scrollY"), 0)
        self.page.goto("/?page=subscriptions")
        expect(self.page.get_by_role("heading", name="订阅", exact=True)).to_be_visible()
        self.page.goto("/admin/")
        expect(self.page.get_by_role("heading", name="订阅", exact=True)).to_be_visible()

    def test_refresh_and_history_protect_unsaved_form(self):
        self.navigate("设置")
        self.page.get_by_label("时区", exact=True).fill("UTC")
        with self.page.expect_event("dialog") as event:
            self.page.evaluate("setTimeout(() => location.reload(), 0)")
        self.assertEqual(event.value.type, "beforeunload")
        event.value.dismiss()
        expect(self.page.get_by_label("时区", exact=True)).to_have_value("UTC")
        with self.page.expect_event("dialog") as event:
            self.page.evaluate("history.back()")
        self.assertEqual(event.value.type, "beforeunload")
        event.value.dismiss()
        expect(self.page.get_by_label("时区", exact=True)).to_have_value("UTC")

    def test_login_logout_and_expired_session(self):
        self.page.get_by_role("button", name="退出登录", exact=True).click()
        expect(self.page.get_by_label("密码", exact=True)).to_be_visible()
        self.page.get_by_label("密码", exact=True).fill("wrong")
        self.page.get_by_role("button", name="登录", exact=True).click()
        expect(self.page.get_by_text("密码不正确", exact=True)).to_be_visible()
        self.page.get_by_label("密码", exact=True).fill(PASSWORD)
        self.page.get_by_role("button", name="登录", exact=True).click()
        expect(self.page.get_by_role("heading", name="我的订阅", exact=True)).to_be_visible()
        self.context.clear_cookies()
        self.page.get_by_role("button", name="订阅1：标记已付", exact=True).click()
        expect(self.page.locator("#reauth article")).to_be_visible()

    def test_expired_session_preserves_draft_until_manual_save(self):
        self.navigate("设置")
        self.page.get_by_label("时区", exact=True).fill("UTC")
        self.context.clear_cookies()
        self.page.get_by_role("button", name="保存", exact=True).click()
        dialog = self.page.locator("#reauth")
        expect(dialog.locator("article")).to_be_visible()
        expect(self.page.get_by_label("时区", exact=True)).to_have_value("UTC")
        dialog.get_by_label("重新登录密码", exact=True).fill("wrong")
        dialog.get_by_role("button", name="登录", exact=True).click()
        expect(dialog.get_by_text("密码不正确", exact=True)).to_be_visible()
        dialog.get_by_label("重新登录密码", exact=True).fill(PASSWORD)
        dialog.get_by_role("button", name="登录", exact=True).click()
        expect(dialog).not_to_have_attribute("open", "")
        self.assertEqual(self.api.get("/api/settings").json()["timezone"], "Asia/Shanghai")
        self.save()
        self.assertEqual(self.api.get("/api/settings").json()["timezone"], "UTC")

    def test_subscription_draft_survives_reauthentication(self):
        self.navigate("订阅")
        self.page.get_by_label("名称", exact=True).first.fill("保留的订阅草稿")
        self.context.clear_cookies()
        self.page.get_by_role("button", name="保存", exact=True).click()
        dialog = self.page.locator("#reauth")
        expect(dialog.locator("article")).to_be_visible()
        dialog.get_by_role("button", name="继续编辑", exact=True).click()
        expect(self.page.get_by_label("名称", exact=True).first).to_have_value("保留的订阅草稿")
        self.page.get_by_role("button", name="重新登录", exact=True).click()
        dialog.get_by_label("重新登录密码", exact=True).fill(PASSWORD)
        dialog.get_by_role("button", name="登录", exact=True).click()
        expect(dialog).not_to_have_attribute("open", "")
        self.assertEqual(self.api.get("/api/subscriptions").json()[0]["name"], "订阅1")
        self.assertEqual(self.page.evaluate("localStorage.length"), 0)
        self.save()
        self.assertEqual(self.api.get("/api/subscriptions").json()[0]["name"], "保留的订阅草稿")

    def test_renewal_waits_for_inflight_background_refresh(self):
        pending = []

        def fragment(route):
            if not pending:
                pending.append(route)
            else:
                route.continue_()

        self.page.route("**/", fragment)
        self.page.evaluate("dispatchEvent(new Event('focus'))")
        self.page.wait_for_timeout(200)
        self.assertEqual(len(pending), 1)
        self.page.get_by_role("button", name="订阅1：标记已付", exact=True).click()
        self.assertNotEqual(
            self.api.get("/api/dashboard").json()["category_groups"][0]["subscription_items"][0][
                "button_state"
            ]["status_kind"],
            "renewed",
        )
        pending[0].fulfill(response=pending[0].fetch())
        expect(
            self.page.get_by_role("button", name="订阅1：已付，点击撤销", exact=True)
        ).to_be_visible()

    def test_concurrent_unauthorized_requests_share_dialog(self):
        self.navigate("设置")
        pending = []
        self.page.route("**/api/configuration", lambda route: pending.append(route))
        self.page.evaluate("""() => {
            window.modalCalls = 0;
            const original = HTMLDialogElement.prototype.showModal;
            HTMLDialogElement.prototype.showModal = function() {
                window.modalCalls++;
                return original.call(this);
            };
            document.querySelector('#export').click();
            document.querySelector('#export').click();
        }""")
        self.page.wait_for_timeout(100)
        self.assertEqual(len(pending), 2)
        self.page.get_by_label("时区", exact=True).fill("UTC")
        for route in pending:
            route.fulfill(status=401, json={"error": "请登录"})
        expect(self.page.locator("#reauth article")).to_be_visible()
        self.page.wait_for_timeout(100)
        self.assertEqual(self.page.evaluate("window.modalCalls"), 1)
        self.page.keyboard.press("Escape")
        expect(self.page.get_by_label("时区", exact=True)).to_have_value("UTC")

    def test_refresh_rejects_stale_renewal_state(self):
        pending = []
        writes = []
        self.page.route("**/", lambda route: pending.append(route))
        self.page.route("**/api/renewal-status", lambda route: writes.append(route))
        self.page.evaluate("dispatchEvent(new Event('focus'))")
        self.page.wait_for_timeout(200)
        self.assertEqual(len(pending), 1)
        button = self.page.get_by_role("button", name="订阅1：标记已付", exact=True)
        state = button.evaluate(
            "el => ({subscription_id:el.dataset.id, payment_date:el.dataset.payment, renewal_date:el.dataset.renewal, renewed:true})"
        )
        self.assertTrue(self.api.put("/api/renewal-status", headers=HEADERS, data=state).ok)
        button.click()
        pending[0].fulfill(response=pending[0].fetch())
        expect(self.page.get_by_text("订阅状态已更新，请重新操作", exact=True)).to_be_visible()
        expect(
            self.page.get_by_role("button", name="订阅1：已付，点击撤销", exact=True)
        ).to_be_enabled()
        self.assertEqual(writes, [])

    def test_failed_logout_preserves_unsaved_protection(self):
        self.navigate("设置")
        self.page.get_by_label("时区", exact=True).fill("UTC")
        self.page.route(
            "**/api/auth/logout",
            lambda route: route.fulfill(status=502, json={"error": "退出失败"}),
        )
        self.page.get_by_role("button", name="退出登录", exact=True).click()
        self.page.get_by_role("button", name="放弃更改", exact=True).click()
        expect(self.page.get_by_text("退出失败", exact=True)).to_be_visible()
        expect(self.page.get_by_label("时区", exact=True)).to_have_value("UTC")
        self.page.get_by_role("link", name="首页", exact=True).click()
        expect(self.page.get_by_role("alertdialog").locator("article")).to_be_visible()

    def test_duplicate_renewal_and_save_do_not_submit_twice(self):
        routes = []
        self.page.route("**/api/renewal-status", lambda route: routes.append(route))
        self.page.get_by_role("button", name="订阅1：标记已付", exact=True).click()
        self.page.evaluate(
            "document.querySelector('.renew').dispatchEvent(new MouseEvent('click',{bubbles:true}))"
        )
        self.assertEqual(len(routes), 1)
        routes[0].fulfill(response=routes[0].fetch())
        expect(
            self.page.get_by_role("button", name="订阅1：已付，点击撤销", exact=True)
        ).to_be_visible()
        self.navigate("设置")
        self.page.get_by_label("时区", exact=True).fill("UTC")
        routes.clear()
        self.page.route("**/api/settings", lambda route: routes.append(route))
        self.page.get_by_role("button", name="保存", exact=True).click()
        self.page.locator("#settings-form").evaluate(
            "form => form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))"
        )
        self.assertEqual(len(routes), 1)
        routes[0].fulfill(response=routes[0].fetch())
        expect(self.page.get_by_text("未保存", exact=True)).to_be_hidden()

    def test_mobile_dark_keyboard_validation_and_xss(self):
        self.page.set_viewport_size({"width": 375, "height": 812})
        self.page.emulate_media(color_scheme="dark")
        self.navigate("订阅")
        row = self.page.get_by_role("group", name="订阅1", exact=True)
        row.get_by_label("名称", exact=True).fill('<img src=x onerror="window.xss=1">')
        self.save()
        self.navigate("首页")
        expect(
            self.page.get_by_role("heading", name='<img src=x onerror="window.xss=1">', exact=True)
        ).to_be_visible()
        self.assertIsNone(self.page.evaluate("window.xss"))
        self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        self.navigate("设置")
        self.page.get_by_label("提前提醒", exact=True).fill("366")
        self.assertFalse(
            self.page.locator("#settings-form").evaluate("form => form.checkValidity()")
        )
        self.page.get_by_role("link", name="首页", exact=True).click()
        dialog = self.page.get_by_role("alertdialog")
        expect(dialog.get_by_role("button", name="继续编辑", exact=True)).to_be_focused()
        self.page.keyboard.press("Tab")
        expect(dialog.get_by_role("button", name="放弃更改", exact=True)).to_be_focused()
        self.page.keyboard.press("Tab")
        expect(dialog.get_by_role("button", name="继续编辑", exact=True)).to_be_focused()
        self.page.keyboard.press("Escape")
        expect(dialog).not_to_have_attribute("open", "")


if __name__ == "__main__":
    import logging

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    unittest.main()
