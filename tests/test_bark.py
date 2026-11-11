import unittest
from unittest.mock import patch

import httpx

from app.bark import send_bark_notification


class BarkTests(unittest.TestCase):
    @patch("app.bark.httpx.get")
    def test_bark_query_and_message_url(self, get):
        get.return_value.json.return_value = {"code": 200}
        for query in (
            "",
            "?level=timeSensitive",
            "?level=critical",
            "?level=critical&call=1",
            "?custom=a%2Fb&custom=c+d",
        ):
            for path in ("/key", "/key/"):
                with self.subTest(query=query, path=path):
                    self.assertTrue(
                        send_bark_notification(
                            "https://example.com" + path + query, "A/B 标题", "正文?&/#"
                        )
                    )
                    get.assert_called_with(
                        "https://example.com/key/A%2FB%20%E6%A0%87%E9%A2%98/"
                        "%E6%AD%A3%E6%96%87%3F%26%2F%23" + query,
                        timeout=10,
                    )

    @patch("app.bark.httpx.get")
    def test_bark_application_errors(self, get):
        get.return_value.json.return_value = {"code": 400}
        self.assertFalse(send_bark_notification("https://example.com/key", "测试", "内容"))
        get.return_value.json.return_value = {"code": 200}
        self.assertTrue(send_bark_notification("https://example.com/key", "测试", "内容"))
        get.return_value.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error",
            request=httpx.Request("GET", "https://example.com"),
            response=httpx.Response(500),
        )
        self.assertFalse(send_bark_notification("https://example.com/key", "测试", "内容"))
        get.side_effect = httpx.ConnectError("offline")
        self.assertFalse(send_bark_notification("https://example.com/key", "测试", "内容"))
        get.side_effect = httpx.TimeoutException("timeout")
        self.assertFalse(send_bark_notification("https://example.com/key", "测试", "内容"))
        get.side_effect = httpx.InvalidURL("Invalid IDNA hostname")
        self.assertFalse(send_bark_notification("https://☃.com/key", "测试", "内容"))
