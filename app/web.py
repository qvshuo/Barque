"""Same-origin JSON API, server-rendered pages and local static assets."""

import gzip
import hashlib
import os
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory, url_for
from werkzeug.exceptions import HTTPException

from app.auth import COOKIE_NAME, SESSION_SECONDS, Authentication
from app.bark import send_bark_notification
from app.config import validate_settings
from app.currencies import DEFAULT_CURRENCIES
from app.database import Database, SubscriptionConflictError
from app.renewals import build_toggle_response, cycle_key
from app.scheduler import Scheduler
from app.subscriptions import find_subscription_item

STATIC_DIR = Path(__file__).resolve().parent / "static"
CYCLES = {"week": "每周", "month": "每月", "quarter": "每季度", "year": "每年"}


def create_app(
    database: Database,
    scheduler: Scheduler,
    static_dir: Path | None = None,
    initial_password: str | None = None,
) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
    dist = static_dir or STATIC_DIR

    @lru_cache(maxsize=64)
    def asset_version(filename):
        return hashlib.sha256((dist / filename).read_bytes()).hexdigest()[:16]

    def asset(filename):
        return url_for("assets", filename=filename, v=asset_version(filename))

    def money(value, currency="CNY"):
        # Formatting only; renewal and conversion calculations stay in the business modules.
        symbol = {"CNY": "¥", "USD": "US$", "EUR": "€", "GBP": "£", "JPY": "JP¥", "HKD": "HK$"}.get(
            currency, currency + " "
        )
        digits = (
            0
            if currency
            in {
                "JPY",
                "KRW",
                "VND",
                "CLP",
                "ISK",
                "XAF",
                "XOF",
                "XPF",
                "BIF",
                "DJF",
                "GNF",
                "KMF",
                "PYG",
                "RWF",
                "UGX",
                "VUV",
            }
            else 3
            if currency in {"BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"}
            else 2
        )
        return f"{symbol}{value:,.{digits}f}"

    app.jinja_env.filters["money"] = money
    app.jinja_env.globals.update(asset=asset, cycles=CYCLES)
    auth = Authentication(database, initial_password)

    @app.before_request
    def same_origin_mutations():
        if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
            # JSON plus a custom header requires a same-origin request or a CORS preflight.
            # No cross-origin requests are enabled by this service.
            if request.headers.get("X-Barque-Request") != "1" or not request.is_json:
                return jsonify(error="请求必须来自 Barque 界面并使用 JSON"), 403
            if request.headers.get("Sec-Fetch-Site") == "cross-site":
                return jsonify(error="不允许跨站修改"), 403

    @app.before_request
    def require_password():
        # Public pages render only the password form before login.
        public = {"index", "assets", "icons", "auth_status", "login"}
        if request.endpoint not in public and not auth.authenticated(
            request.cookies.get(COOKIE_NAME)
        ):
            return jsonify(error="请先输入访问密码"), 401

    @app.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(SubscriptionConflictError)
    def subscription_conflict(error):
        return jsonify(error=str(error)), 409

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.endpoint == "index":
            return render_template("error.html", page="error"), error.code
        return jsonify(error=error.description), error.code

    def body():
        value = request.get_json()
        if not isinstance(value, dict):
            raise ValueError("请求内容必须是 JSON 对象")
        return value

    def session_response(token):
        response = jsonify(authenticated=True)
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=SESSION_SECONDS,
            httponly=True,
            secure=request.is_secure or os.environ.get("BARQUE_SECURE_COOKIE") == "1",
            samesite="Strict",
            path="/",
        )
        return response

    @app.get("/api/auth/session")
    def auth_status():
        return jsonify(authenticated=auth.authenticated(request.cookies.get(COOKIE_NAME)))

    @app.post("/api/auth/login")
    def login():
        try:
            token = auth.login(body().get("password"))
        except PermissionError as exc:
            response = jsonify(error=str(exc))
            response.headers["Retry-After"] = "60"
            return response, 429
        if token is None:
            return jsonify(error="密码不正确"), 401
        return session_response(token)

    @app.post("/api/auth/logout")
    def logout():
        body()
        auth.logout(request.cookies.get(COOKIE_NAME))
        response = jsonify(authenticated=False)
        response.delete_cookie(
            COOKIE_NAME,
            path="/",
            httponly=True,
            secure=request.is_secure or os.environ.get("BARQUE_SECURE_COOKIE") == "1",
            samesite="Strict",
        )
        return response

    @app.get("/api/settings")
    def settings():
        return jsonify(asdict(database.get_config().app))

    @app.put("/api/settings")
    def update_settings():
        settings = database.update_settings(body())
        scheduler.wake()
        return jsonify(asdict(settings))

    @app.get("/api/configuration")
    def export_configuration():
        return jsonify(database.export_config())

    @app.put("/api/configuration")
    def import_configuration():
        request.max_content_length = 2 * 1024 * 1024
        config = database.import_config(body())
        scheduler.wake()
        return jsonify(asdict(config.app))

    @app.get("/api/subscription-groups")
    def subscription_groups():
        return jsonify(database.get_subscription_groups())

    @app.put("/api/subscription-groups")
    def update_subscription_groups():
        request.max_content_length = 2 * 1024 * 1024
        groups = database.save_subscription_groups(body())
        scheduler.wake()
        return jsonify(groups)

    @app.put("/api/renewal-status")
    def renewal_status():
        data = body()
        subscription_id, payment_date, renewal_date = (
            data.get(key) for key in ("subscription_id", "payment_date", "renewal_date")
        )
        if (
            not all(
                isinstance(value, str) and value
                for value in (subscription_id, payment_date, renewal_date)
            )
            or type(data.get("renewed")) is not bool
        ):
            raise ValueError("缺少有效的订阅、账期或续费状态")
        config = database.get_config()
        item = find_subscription_item(
            scheduler.get_dashboard(config), subscription_id, payment_date, renewal_date
        )
        if item is None:
            raise ValueError("该账期已失效，请刷新页面")
        database.set_renewed(
            cycle_key(subscription_id, payment_date, renewal_date), data["renewed"]
        )
        return jsonify(
            build_toggle_response(item["days_left"], data["renewed"], config.app.remind_before_days)
        )

    @app.post("/api/test-notification")
    def test_notification():
        data = body()
        settings = validate_settings(
            {**asdict(database.get_config().app), "notify_url": data.get("notify_url", "")}
        )
        if not settings.notify_url:
            raise ValueError("请输入 Bark 推送地址")
        if not send_bark_notification(
            settings.notify_url, "Barque 测试通知", "通知配置成功，订阅续费提醒将在到期前发送。"
        ):
            return jsonify(error="发送失败，请检查 Bark 地址和网络连接"), 502
        return jsonify(message="测试通知已发送")

    @app.get("/health")
    def health():
        database.get_config()
        return jsonify(status="ok")

    @app.get("/")
    @app.get("/admin")
    @app.get("/admin/")
    def index():
        if not auth.authenticated(request.cookies.get(COOKIE_NAME)):
            return render_template("login.html", page="login")
        page = request.args.get(
            "page", "subscriptions" if request.path.startswith("/admin") else "home"
        )
        if page == "settings":
            return render_template(
                "settings.html", page=page, settings=asdict(database.get_config().app)
            )
        if page == "subscriptions":
            blank = dict(
                id="",
                name="",
                billing_cycle="month",
                payment_date="",
                amount=0,
                currency="",
                notify_enabled=True,
            )
            return render_template(
                "subscriptions.html",
                page=page,
                groups=database.get_subscription_groups(),
                currencies=sorted(DEFAULT_CURRENCIES.items()),
                blank_group={"name": "", "subscriptions": []},
                blank_subscription=blank,
            )
        dashboard_data = scheduler.get_dashboard(database.get_config())
        missing_rates = any(
            item["amount_cny"] is None
            for group in dashboard_data["category_groups"]
            for item in group["subscription_items"]
        )
        return render_template(
            "dashboard.html"
            if request.headers.get("X-Barque-Fragment") == "dashboard"
            else "home.html",
            page="home",
            dashboard=dashboard_data,
            missing_rates=missing_rates,
        )

    @app.get("/assets/<path:filename>")
    def assets(filename):
        compressed = (
            filename.endswith((".js", ".css"))
            and not request.headers.get("Range")
            and request.accept_encodings["gzip"] > 0
            and request.accept_encodings["gzip"] >= request.accept_encodings["identity"]
            and (dist / (filename + ".gz")).is_file()
        )
        response = send_from_directory(
            dist, filename + ".gz" if compressed else filename, max_age=0
        )
        if compressed:
            response.headers["Content-Encoding"] = "gzip"
            response.headers["Content-Type"] = (
                "text/css; charset=utf-8"
                if filename.endswith(".css")
                else "text/javascript; charset=utf-8"
            )
        if filename.endswith((".js", ".css")):
            response.vary.add("Accept-Encoding")
        # Only the URL for this exact content can receive immutable caching.
        if response.status_code in {200, 304} and request.args.get("v") == asset_version(filename):
            response.cache_control.max_age = 31536000
            response.cache_control.immutable = True
            response.cache_control.no_cache = None
        return response

    @app.get("/logo.png")
    @app.get("/favicon.ico")
    @app.get("/apple-touch-icon.png")
    def icons():
        filename = "logo.webp" if request.path == "/logo.png" else request.path.lstrip("/")
        return send_from_directory(dist, filename, max_age=0)

    @app.after_request
    def response_headers(response):
        if request.endpoint not in {"assets", "icons"} or response.status_code >= 400:
            response.headers["Cache-Control"] = "no-store"
        compressible = response.mimetype in {
            "text/html",
            "text/css",
            "text/javascript",
            "application/javascript",
            "application/json",
            "image/svg+xml",
        }
        encodings = request.accept_encodings
        names = {name.lower() for name, _quality in encodings}
        identity_allowed = not (
            ("identity" in names and encodings["identity"] == 0)
            or ("*" in names and encodings["*"] == 0 and "identity" not in names)
        )
        if (
            response.status_code == 200
            and not response.headers.get("Content-Encoding")
            and not identity_allowed
            and not (compressible and encodings["gzip"] > 0)
        ):
            response.close()
            response = jsonify(error="不支持请求的内容编码")
            response.status_code = 406
            response.headers["Cache-Control"] = "no-store"
            compressible = True
        if compressible:
            response.vary.add("Accept-Encoding")
            if (
                response.status_code == 200
                and not response.headers.get("Content-Encoding")
                and not response.headers.get("Content-Range")
                and request.accept_encodings["gzip"] > 0
                and (not identity_allowed or encodings["gzip"] >= encodings["identity"])
            ):
                response.direct_passthrough = False
                data = response.get_data()
                response.set_data(gzip.compress(data, compresslevel=6, mtime=0))
                response.headers["Content-Encoding"] = "gzip"
                if response.get_etag()[0]:
                    response.set_etag(response.get_etag()[0], weak=True)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    return app
