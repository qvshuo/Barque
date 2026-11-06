"""Manual renewal marking and UI button state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.storage import read_json, write_json_atomic


MIN_BUTTON_WINDOW_DAYS = 7


def _state_path(data_dir: Path) -> Path:
    return data_dir / "renewal_state.json"


def load_renewal_state(data_dir: Path) -> dict[str, Any]:
    data = read_json(_state_path(data_dir), {})
    # Support the legacy { "renewed_cycles": { ... } } layout.
    if "renewed_cycles" in data and isinstance(data["renewed_cycles"], dict):
        return dict(data["renewed_cycles"])
    return data if isinstance(data, dict) else {}


def save_renewal_state(data_dir: Path, state: dict[str, Any]) -> None:
    write_json_atomic(_state_path(data_dir), state)


def _cycle_key(subscription_id: str, payment_date: str, renewal_date: str) -> str:
    return f"{subscription_id}:{payment_date}:{renewal_date}"


def is_cycle_renewed(
    state: dict[str, Any], subscription_id: str, payment_date: str, renewal_date: str
) -> bool:
    return bool(state.get(_cycle_key(subscription_id, payment_date, renewal_date)))


def set_cycle_renewed(
    state: dict[str, Any],
    subscription_id: str,
    payment_date: str,
    renewal_date: str,
    renewed: bool,
) -> dict[str, Any]:
    key = _cycle_key(subscription_id, payment_date, renewal_date)
    if renewed:
        state[key] = True
    else:
        state.pop(key, None)
    return state


def button_window_days(remind_before_days: int) -> int:
    return max(MIN_BUTTON_WINDOW_DAYS, remind_before_days)


def build_button_state(days_left: int, cycle_renewed: bool, remind_before_days: int) -> dict[str, Any]:
    """Return the status chip and menu action data rendered by the frontend."""
    if cycle_renewed:
        status_kind, status_label = "renewed", "已续费"
        action_label, action_intent = "取消已续费", "unmark"
    elif days_left <= button_window_days(remind_before_days):
        status_kind, status_label = "renewal_pending", "即将到期"
        action_label, action_intent = "已续费", "mark"
    else:
        status_kind, status_label = "normal", "正常"
        action_label, action_intent = "已续费", "mark"

    return {
        "status_kind": status_kind,
        "status_label": status_label,
        "action_label": action_label,
        "action_intent": action_intent,
        "can_toggle": True,
    }


def build_toggle_response(days_left: int, renewed: bool, remind_before_days: int) -> dict[str, Any]:
    return build_button_state(days_left, renewed, remind_before_days) | {"renewed": renewed}


def cleanup_renewal_state(state: dict[str, Any], active_keys: set[str]) -> dict[str, Any]:
    cleaned = {key: value for key, value in state.items() if key in active_keys}
    if len(cleaned) != len(state):
        return cleaned
    return state
