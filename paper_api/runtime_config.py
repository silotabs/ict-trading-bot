from __future__ import annotations

import json
from pathlib import Path


def _load_json_document(path, *, label):
    path = Path(path)
    if not path.exists():
        return {
            "ok": False,
            "path": str(path),
            "errors": [f"{label} file not found: {path}"],
            "document": None,
        }

    try:
        raw = json.loads(path.read_text())
    except OSError as exc:
        return {
            "ok": False,
            "path": str(path),
            "errors": [f"failed to read {label}: {exc}"],
            "document": None,
        }
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "path": str(path),
            "errors": [f"invalid JSON in {label}: {exc.msg}"],
            "document": None,
        }

    if not isinstance(raw, dict):
        return {
            "ok": False,
            "path": str(path),
            "errors": [f"{label} must be a JSON object"],
            "document": None,
        }

    return {
        "ok": True,
        "path": str(path),
        "errors": [],
        "document": raw,
    }


def load_execution_spec(path, *, clean_string):
    result = _load_json_document(path, label="execution spec")
    raw = result["document"]
    if raw is None:
        return {
            "ok": False,
            "path": result["path"],
            "errors": result["errors"],
            "spec": None,
        }

    errors = []
    if clean_string(raw.get("venue")) != "bybit":
        errors.append("execution spec venue must be bybit")
    if clean_string(raw.get("category")) not in {"linear", "inverse"}:
        errors.append("execution spec category must be linear or inverse")
    if clean_string(raw.get("account_type")) is None:
        errors.append("execution spec account_type is required")
    if clean_string(raw.get("balance_coin")) is None:
        errors.append("execution spec balance_coin is required")
    if not isinstance(raw.get("risk"), dict):
        errors.append("execution spec risk section is required")
    if not isinstance(raw.get("execution"), dict):
        errors.append("execution spec execution section is required")
    if not isinstance(raw.get("instruments"), dict) or not raw.get("instruments"):
        errors.append("execution spec instruments section is required")

    return {
        "ok": not errors,
        "path": result["path"],
        "errors": errors,
        "spec": raw,
    }


def load_auto_execution_policy(
    path,
    *,
    clean_string,
    normalize_instrument,
    allowed_instruments,
):
    result = _load_json_document(path, label="auto-execution policy")
    raw = result["document"]
    if raw is None:
        return {
            "ok": False,
            "path": result["path"],
            "errors": result["errors"],
            "policy": None,
        }

    errors = []
    instruments = raw.get("instruments")
    if not isinstance(instruments, list) or not instruments:
        errors.append("auto-execution policy instruments section is required")
    else:
        normalized_instruments = [normalize_instrument(item) for item in instruments]
        unsupported = [
            item for item in normalized_instruments if item not in set(allowed_instruments or [])
        ]
        if unsupported:
            errors.append(
                f"auto-execution policy contains unsupported instruments: {', '.join(unsupported)}"
            )
        raw["instruments"] = [item for item in normalized_instruments if item]

    category = clean_string(raw.get("category"))
    if category not in {"linear"}:
        errors.append("auto-execution policy category must be linear")

    entry_model = clean_string(raw.get("entry_model"))
    if entry_model not in {"fvg_midpoint"}:
        errors.append("auto-execution policy entry_model must be fvg_midpoint")

    stop_model = clean_string(raw.get("stop_model"))
    if stop_model not in {"sweep_or_fvg_boundary"}:
        errors.append("auto-execution policy stop_model must be sweep_or_fvg_boundary")

    target_model = clean_string(raw.get("target_model"))
    if target_model not in {"nearest_opposing_liquidity"}:
        errors.append("auto-execution policy target_model must be nearest_opposing_liquidity")

    return {
        "ok": not errors,
        "path": result["path"],
        "errors": errors,
        "policy": raw,
    }


def load_trade_management_policy(path):
    result = _load_json_document(path, label="trade-management policy")
    raw = result["document"]
    if raw is None:
        return {
            "ok": False,
            "path": result["path"],
            "errors": result["errors"],
            "policy": None,
        }

    errors = []
    working_orders = raw.get("working_orders")
    if not isinstance(working_orders, dict):
        errors.append("trade-management policy working_orders section is required")
    else:
        try:
            if int(working_orders.get("stale_after_seconds", 0)) < 1:
                errors.append("working_orders.stale_after_seconds must be >= 1")
        except (TypeError, ValueError):
            errors.append("working_orders.stale_after_seconds must be an integer")

    open_positions = raw.get("open_positions")
    if not isinstance(open_positions, dict):
        errors.append("trade-management policy open_positions section is required")
    else:
        break_even = open_positions.get("break_even")
        if not isinstance(break_even, dict):
            errors.append("open_positions.break_even section is required")
        else:
            try:
                if float(break_even.get("trigger_rr", 0)) <= 0:
                    errors.append("open_positions.break_even.trigger_rr must be > 0")
            except (TypeError, ValueError):
                errors.append("open_positions.break_even.trigger_rr must be numeric")
            try:
                if int(break_even.get("buffer_ticks", 0)) < 0:
                    errors.append("open_positions.break_even.buffer_ticks must be >= 0")
            except (TypeError, ValueError):
                errors.append("open_positions.break_even.buffer_ticks must be an integer")

    try:
        if int(raw.get("max_actions_per_cycle", 0)) < 1:
            errors.append("trade-management policy max_actions_per_cycle must be >= 1")
    except (TypeError, ValueError):
        errors.append("trade-management policy max_actions_per_cycle must be an integer")

    try:
        if int(raw.get("cooldown_seconds_per_proposal", 0)) < 0:
            errors.append("trade-management policy cooldown_seconds_per_proposal must be >= 0")
    except (TypeError, ValueError):
        errors.append("trade-management policy cooldown_seconds_per_proposal must be an integer")

    return {
        "ok": not errors,
        "path": result["path"],
        "errors": errors,
        "policy": raw,
    }


def load_risk_control_policy(path):
    result = _load_json_document(path, label="risk-control policy")
    raw = result["document"]
    if raw is None:
        return {
            "ok": False,
            "path": result["path"],
            "errors": result["errors"],
            "policy": None,
        }

    errors = []
    for key in (
        "max_daily_realized_loss",
        "max_open_exposure_notional",
        "max_active_intents_per_symbol",
        "max_order_notional",
        "max_order_qty",
        "max_daily_order_count",
        "max_intraday_position_exposure_per_symbol",
        "market_data_stale_after_seconds",
        "execution_state_stale_after_seconds",
    ):
        try:
            if float(raw.get(key, 0)) < 0:
                errors.append(f"risk-control policy {key} must be >= 0")
        except (TypeError, ValueError):
            errors.append(f"risk-control policy {key} must be numeric")

    maximum_order_size = raw.get("maximum_order_size")
    if maximum_order_size is not None:
        if not isinstance(maximum_order_size, dict):
            errors.append("risk-control policy maximum_order_size must be an object")
        else:
            for key in ("max_notional", "max_qty"):
                try:
                    if float(maximum_order_size.get(key, 0)) < 0:
                        errors.append(f"maximum_order_size.{key} must be >= 0")
                except (TypeError, ValueError):
                    errors.append(f"maximum_order_size.{key} must be numeric")

    daily_order_count = raw.get("daily_order_count")
    if daily_order_count is not None:
        if not isinstance(daily_order_count, dict):
            errors.append("risk-control policy daily_order_count must be an object")
        else:
            try:
                if int(daily_order_count.get("max_count", 0)) < 0:
                    errors.append("daily_order_count.max_count must be >= 0")
            except (TypeError, ValueError):
                errors.append("daily_order_count.max_count must be an integer")

    symbol_exposure = raw.get("symbol_exposure")
    if symbol_exposure is not None:
        if not isinstance(symbol_exposure, dict):
            errors.append("risk-control policy symbol_exposure must be an object")
        else:
            try:
                if float(symbol_exposure.get("max_intraday_position_exposure", 0)) < 0:
                    errors.append("symbol_exposure.max_intraday_position_exposure must be >= 0")
            except (TypeError, ValueError):
                errors.append("symbol_exposure.max_intraday_position_exposure must be numeric")

    automatic_kill_switch = raw.get("automatic_kill_switch")
    if automatic_kill_switch is not None and not isinstance(automatic_kill_switch, dict):
        errors.append("risk-control policy automatic_kill_switch must be an object")

    cancel_on_disconnect = raw.get("cancel_on_disconnect")
    if cancel_on_disconnect is not None and not isinstance(cancel_on_disconnect, dict):
        errors.append("risk-control policy cancel_on_disconnect must be an object")

    loss_streak = raw.get("loss_streak")
    if not isinstance(loss_streak, dict):
        errors.append("risk-control policy loss_streak section is required")
    else:
        try:
            if int(loss_streak.get("max_consecutive_losses", 0)) < 0:
                errors.append("loss_streak.max_consecutive_losses must be >= 0")
        except (TypeError, ValueError):
            errors.append("loss_streak.max_consecutive_losses must be an integer")
        try:
            if int(loss_streak.get("cooldown_seconds", 0)) < 0:
                errors.append("loss_streak.cooldown_seconds must be >= 0")
        except (TypeError, ValueError):
            errors.append("loss_streak.cooldown_seconds must be an integer")

    return {
        "ok": not errors,
        "path": result["path"],
        "errors": errors,
        "policy": raw,
    }


def load_liquidity_context_policy(path):
    result = _load_json_document(path, label="liquidity-context policy")
    raw = result["document"]
    if raw is None:
        return {
            "ok": False,
            "path": result["path"],
            "errors": result["errors"],
            "policy": None,
        }

    return {
        "ok": True,
        "path": result["path"],
        "errors": [],
        "policy": raw,
    }
