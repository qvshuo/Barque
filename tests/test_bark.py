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

    def test_bark_application_errors(self):
        for payload in ({"code": 400}, {"message": "invalid"}, []):
            with self.subTest(payload=payload), patch("app.bark.httpx.get") as get:
                get.return_value.json.return_value = payload
                self.assertFalse(send_bark_notification("https://example.com/key", "测试", "内容"))

    def test_bark_http_errors(self):
        url = "https://example.com/key"
        errors = (
            httpx.HTTPStatusError(
                "error", request=httpx.Request("GET", url), response=httpx.Response(500)
            ),
            httpx.ConnectError("offline"),
            httpx.TimeoutException("timeout"),
            httpx.InvalidURL("Invalid IDNA hostname"),
        )
        for error in errors:
            with (
                self.subTest(error=type(error).__name__),
                patch("app.bark.httpx.get", side_effect=error),
            ):
                self.assertFalse(send_bark_notification(url, "测试", "内容"))
