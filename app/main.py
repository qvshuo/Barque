"""Application startup and shutdown."""

from __future__ import annotations

import logging
import os
import signal
from pathlib import Path

from waitress import create_server

from app.database import Database
from app.scheduler import Scheduler
from app.web import create_app


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # HTTP client logs can contain Bark device keys in request URLs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    data_dir = Path(os.environ.get("BARQUE_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
    database = Database(data_dir)
    scheduler = Scheduler(database)
    app = create_app(database, scheduler, initial_password=os.environ.get("BARQUE_PASSWORD"))
    server = create_server(app, host="0.0.0.0", port=8080, threads=8)

    def shutdown(*_args):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    scheduler.start()
    logging.getLogger(__name__).info("Barque ready on :8080")
    try:
        server.run()
    finally:
        scheduler.stop()
        server.close()


if __name__ == "__main__":
    main()
