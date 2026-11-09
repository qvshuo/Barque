"""Offline currency catalog from the same Frankfurter v1 API as exchange rates."""

import json
from pathlib import Path

DEFAULT_CURRENCIES = json.loads(
    Path(__file__).with_name("currencies.json").read_text(encoding="utf-8")
)
