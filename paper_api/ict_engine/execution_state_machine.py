from __future__ import annotations

from .evaluation import decision_allows_execution_plan
from .utils import clean_string


EXECUTION_INTENT_STATES = {
    "signal_detected",
    "execution_plan_created",
    "order_submission_pending",
    "order_submitted",
    "order_acknowledged",
    "partially_filled",
    "fully_filled",
    "cancelled",
    "rejected",
    "flattened",
    "reconciled",
}

TERMINAL_EXECUTION_INTENT_STATES = {
    "cancelled",
    "rejected",
    "flattened",
    "reconciled",
}

ACTIVE_EXECUTION_INTENT_STATES = EXECUTION_INTENT_STATES - TERMINAL_EXECUTION_INTENT_STATES

ALLOWED_TRANSITIONS = {
    "signal_detected": {"execution_plan_created", "cancelled", "rejected"},
    "execution_plan_created": {"order_submission_pending", "cancelled", "rejected"},
    "order_submission_pending": {"order_submitted", "cancelled", "rejected"},
    "order_submitted": {"order_acknowledged", "partially_filled", "fully_filled", "cancelled", "rejected"},
    "order_acknowledged": {"partially_filled", "fully_filled", "cancelled", "rejected"},
    "partially_filled": {"fully_filled", "cancelled", "flattened"},
    "fully_filled": {"flattened", "reconciled"},
    "cancelled": {"reconciled"},
    "rejected": {"reconciled"},
    "flattened": {"reconciled"},
    "reconciled": set(),
}


def build_execution_intent_key(*, source_path, symbol, scan_signature):
    source = clean_string(source_path) or "unknown"
    instrument = clean_string(symbol) or "unknown"
    signature = clean_string(scan_signature) or "unknown"
    return f"{source}:{instrument}:{signature}"


def normalize_execution_intent_state(value, default="signal_detected"):
    cleaned = clean_string(value)
    if cleaned in EXECUTION_INTENT_STATES:
        return cleaned
    return default


def execution_intent_is_terminal(state):
    return normalize_execution_intent_state(state, default="signal_detected") in TERMINAL_EXECUTION_INTENT_STATES


def decision_allows_execution_intent(decision):
    return decision_allows_execution_plan(decision)


def can_transition_execution_intent(current_state, next_state):
    current = normalize_execution_intent_state(current_state)
    target = normalize_execution_intent_state(next_state)
    if current == target:
        return True
    return target in ALLOWED_TRANSITIONS.get(current, set())


def transition_validation_error(current_state, next_state):
    current = normalize_execution_intent_state(current_state)
    target = normalize_execution_intent_state(next_state)
    if current == target:
        return None
    if target in ALLOWED_TRANSITIONS.get(current, set()):
        return None
    return f"invalid execution-intent transition: {current} -> {target}"


def map_sync_lifecycle_to_intent_state(lifecycle_status):
    lifecycle = clean_string(lifecycle_status) or "unknown"
    mapping = {
        "planned": "execution_plan_created",
        "submitted": "order_submitted",
        "working": "order_acknowledged",
        "partially_filled": "partially_filled",
        "filled": "fully_filled",
        "position_open": "fully_filled",
        "cancelled": "cancelled",
        "rejected": "rejected",
    }
    return mapping.get(lifecycle)
