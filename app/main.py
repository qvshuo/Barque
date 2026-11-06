"""Application startup, data initialization and shutdown."""

from __future__ import annotations

import atexit
import logging
import os
import signal
from pathlib import Path

from app.config import load_config
from app.exchange import DEFAULT_CACHE
from app.scheduler import Scheduler
from app.storage import write_json_atomic
from app.web import create_app


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("BARQUE_DATA_DIR", BASE_DIR / "data"))
CONFIG_PATH = Path(os.environ.get("BARQUE_CONFIG", DATA_DIR / "subscriptions.toml"))
WEB_PORT = 8080

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

scheduler = Scheduler(CONFIG_PATH, DATA_DIR)
app = create_app(CONFIG_PATH, DATA_DIR, scheduler)


def ensure_data_files() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    notification_log = DATA_DIR / "notification_log.json"
    exchange_rates = DATA_DIR / "exchange_rates.json"
    renewal_state = DATA_DIR / "renewal_state.json"
    if not notification_log.exists():
        write_json_atomic(notification_log, {"notifications": []})
    if not exchange_rates.exists():
        write_json_atomic(exchange_rates, DEFAULT_CACHE)
    if not renewal_state.exists():
        write_json_atomic(renewal_state, {"renewed_cycles": {}})


def shutdown(*_args, exit_process: bool = False) -> None:
    scheduler.stop()
    if exit_process:
        raise SystemExit(0)


def main() -> None:
    ensure_data_files()
    config = load_config(CONFIG_PATH)
    logger.info("Barque starting with %s subscriptions", len(config.subscriptions))
    scheduler.sync_exchange_rates(config)
    scheduler.start()
    atexit.register(shutdown)
    signal.signal(signal.SIGTERM, lambda *_args: shutdown(exit_process=True))
    signal.signal(signal.SIGINT, lambda *_args: shutdown(exit_process=True))
    app.run(host="0.0.0.0", port=WEB_PORT)


if __name__ == "__main__":
    main()
