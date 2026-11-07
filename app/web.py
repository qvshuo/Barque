"""Same-origin JSON API and the compiled React application."""

from dataclasses import asdict
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from app.auth import Authentication, COOKIE_NAME, SESSION_SECONDS
from app.bark import send_bark_notification
from app.database import Database, SubscriptionConflictError
from app.renewals import build_toggle_response
from app.scheduler import Scheduler
from app.subscriptions import find_subscription_item

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def create_app(database: Database, scheduler: Scheduler, frontend_dist: Path | None = None, initial_password: str | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
    dist = frontend_dist or FRONTEND_DIST
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
        # The shell and its assets only render the password form before login.
        public = {"index", "assets", "icons", "auth_status", "login"}
        if request.endpoint not in public and not auth.authenticated(request.cookies.get(COOKIE_NAME)):
            return jsonify(error="请先输入访问密码"), 401

    @app.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(SubscriptionConflictError)
    def subscription_conflict(error):
        return jsonify(error=str(error)), 409

    @app.errorhandler(KeyError)
    def missing(_error):
        return jsonify(error="订阅不存在，请刷新后重试"), 404

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    def body():
        value = request.get_json()
        if not isinstance(value, dict):
            raise ValueError("请求内容必须是 JSON 对象")
        return value

    def session_response(token):
        response = jsonify(authenticated=True)
        response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True, secure=request.is_secure, samesite="Strict", path="/")
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
        response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="Strict")
        return response

    @app.get("/api/dashboard")
    def dashboard():
        config = database.get_config()
        return jsonify(title="Barque", **scheduler.get_dashboard(config))

    @app.put("/api/order")
    def move_item():
        data = body()
        database.move(data.get("kind"), data.get("target"), data.get("direction"))
        return "", 204

    @app.get("/api/currencies")
    def currencies():
        return jsonify([{"code": code, "name": name} for code, name in sorted(database.supported_currencies().items())])

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

    @app.get("/api/subscriptions")
    def subscriptions():
        return jsonify([asdict(subscription) for subscription in database.get_config().subscriptions])

    @app.get("/api/subscription-groups")
    def subscription_groups():
        return jsonify(database.get_subscription_groups())

    @app.put("/api/subscription-groups")
    def update_subscription_groups():
        request.max_content_length = 2 * 1024 * 1024
        groups = database.save_subscription_groups(body())
        scheduler.wake()
        return jsonify(groups)

    @app.post("/api/subscriptions")
    def add_subscription():
        subscription = database.save_subscription(body())
        scheduler.wake()
        return jsonify(asdict(subscription)), 201

    @app.put("/api/subscriptions/<subscription_id>")
    def update_subscription(subscription_id):
        subscription = database.save_subscription(body(), subscription_id)
        scheduler.wake()
        return jsonify(asdict(subscription))

    @app.put("/api/subscriptions/<subscription_id>/notifications")
    def update_notification_preference(subscription_id):
        enabled = body().get("enabled")
        if type(enabled) is not bool:
            raise ValueError("提醒开关必须为布尔值")
        subscription = database.set_notify_enabled(subscription_id, enabled)
        scheduler.wake()
        return jsonify(asdict(subscription))

    @app.delete("/api/subscriptions/<subscription_id>")
    def delete_subscription(subscription_id):
        database.delete_subscription(subscription_id)
        scheduler.wake()
        return "", 204

    @app.put("/api/renewal-status")
    def renewal_status():
        data = body()
        subscription_id, payment_date, renewal_date = (data.get(key) for key in ("subscription_id", "payment_date", "renewal_date"))
        if not all(isinstance(value, str) and value for value in (subscription_id, payment_date, renewal_date)) or type(data.get("renewed")) is not bool:
            raise ValueError("缺少有效的订阅、账期或续费状态")
        config = database.get_config()
        item = find_subscription_item(scheduler.get_dashboard(config), subscription_id, payment_date, renewal_date)
        if item is None:
            raise ValueError("该账期已失效，请刷新页面")
        database.set_renewed(f"{subscription_id}:{payment_date}:{renewal_date}", data["renewed"])
        return jsonify(build_toggle_response(item["days_left"], data["renewed"], config.app.remind_before_days))

    @app.post("/api/test-notification")
    def test_notification():
        body()
        config = database.get_config()
        if not config.app.notify_url:
            raise ValueError("请先保存 Bark 推送地址")
        if not send_bark_notification(config.app.notify_url, "Barque 测试通知", "通知配置成功，订阅续费提醒将在到期前发送。"):
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
        return send_from_directory(dist, "index.html", max_age=0)

    @app.get("/assets/<path:filename>")
    def assets(filename):
        compressed = (
            filename.endswith((".js", ".css"))
            and request.accept_encodings["gzip"] > 0
            and (dist / "assets" / (filename + ".gz")).is_file()
        )
        response = send_from_directory(dist / "assets", filename + ".gz" if compressed else filename, max_age=31536000)
        if compressed:
            response.headers["Content-Encoding"] = "gzip"
            response.headers["Content-Type"] = "text/css; charset=utf-8" if filename.endswith(".css") else "text/javascript; charset=utf-8"
        response.vary.add("Accept-Encoding")
        response.cache_control.immutable = True
        return response

    @app.get("/logo.png")
    @app.get("/favicon.ico")
    @app.get("/apple-touch-icon.png")
    def icons():
        return send_from_directory(dist, request.path.lstrip("/"))

    @app.after_request
    def response_headers(response):
        if request.endpoint not in {"assets", "icons"}:
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    return app
