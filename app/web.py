"""Flask application, HTTP endpoints and template filters."""

from pathlib import Path

from flask import Flask, jsonify, render_template, request

from app.config import load_config
from app.renewals import build_toggle_response, load_renewal_state, save_renewal_state, set_cycle_renewed
from app.scheduler import Scheduler
from app.subscriptions import find_subscription_item


def create_app(config_path: Path, data_dir: Path, scheduler: Scheduler) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        config = load_config(config_path)
        dashboard = scheduler.get_dashboard(config)
        return render_template("index.html", title=config.app.title, dashboard=dashboard)

    @app.post("/renewal-status/toggle")
    def toggle_renewal_status():
        subscription_id = request.form.get("subscription_id", "").strip()
        payment_date = request.form.get("payment_date", "").strip()
        renewal_date = request.form.get("renewal_date", "").strip()

        if not subscription_id or not payment_date or not renewal_date:
            return jsonify({"error": "missing parameters"}), 400

        config = load_config(config_path)
        dashboard = scheduler.get_dashboard(config)
        item = find_subscription_item(dashboard, subscription_id, payment_date, renewal_date)
        if item is None or not item["button_state"]["can_toggle"]:
            return jsonify({"error": "subscription not toggleable"}), 400

        renewed_cycles = load_renewal_state(data_dir)
        current_key = f"{subscription_id}:{payment_date}:{renewal_date}"
        current = bool(renewed_cycles.get(current_key))
        renewed = not current
        state = set_cycle_renewed(renewed_cycles, subscription_id, payment_date, renewal_date, renewed)
        save_renewal_state(data_dir, state)

        return jsonify(build_toggle_response(item["days_left"], renewed, config.app.remind_before_days))

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.template_filter("cycle_label")
    def cycle_label(value: str) -> str:
        return {"week": "每周", "month": "每月", "quarter": "每季度", "year": "每年"}.get(value, value)

    return app
