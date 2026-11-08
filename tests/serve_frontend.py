"""Disposable local app for browser tests. No scheduler or outbound notifications."""

import tempfile
from pathlib import Path

from app.database import Database
from app.scheduler import Scheduler
from app.web import create_app

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="barque-browser-") as directory:
        database = Database(Path(directory))
        app = create_app(database, Scheduler(database), initial_password="browser-test-password")
        app.run(host="127.0.0.1", port=18083, threaded=True)
