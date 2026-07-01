from __future__ import annotations

from datetime import datetime, timezone

from .utils import clean_string, coerce_bool, parse_iso_datetime, to_float


LOSS_RESULT_STATUSES = {"loss"}
LOSS_STREAK_RESET_STATUSES = {"win", "breakeven", "flat"}


def _now_at(now_at=None):
    parsed = parse_iso_datetime(now_at)
    return parsed if parsed is not None else datetime.now(timezone.utc)


def _seconds_since(timestamp, *, now_dt):
    parsed = parse_iso_datetime(timestamp)
    if parsed is None:
        return None
    return max(0.0, (now_dt - parsed).total_seconds())


def _append_unique(items, value):
    cleaned = clean_string(value)
    if cleaned and cleaned not in items:
        items.append(cleaned)


def _risk_item(name, *, status, summary, details=None):
    return {
        "name": name,
        "status": status,
        "summary": summary,
        "details": details if isinstance(details, dict) else {},
    }


def _to_number(value, default=None):
    numeric = to_float(value)
    return numeric if numeric is not None else default


def _first_present(mapping, keys):
    mapping = mapping if isinstance(mapping, dict) else {}
    for key in keys:
        value = mapping.get(key)
        if value is not None and value != "":
            return value
    return None


def _policy_section(policy, key):
    section = policy.get(key)
    return section if isinstance(section, dict) else {}


def _nested_number(policy, section_key, field_key, *, legacy_key=None, default=0.0):
    section = _policy_section(policy, section_key)
    value = section.get(field_key)
    if value is None and legacy_key:
        value = policy.get(legacy_key)
    return _to_number(value, default=default) or 0.0


def _nested_int(policy, section_key, field_key, *, legacy_key=None, default=0):
    value = _nested_number(policy, section_key, field_key, legacy_key=legacy_key, default=default)
    return int(value or 0)


def _resolve_control_blockers(control_states):
    checks = {}
    blockers = []
    control_states = control_states if isinstance(control_states, dict) else {}

    blocked_controls = []
    for key in ("global", "auto_execution", "order_submission"):
        control = control_states.get(key) if isinstance(control_states.get(key), dict) else {}
        if control.get("effective_paused"):
            blocked_controls.append(
                {
                    "control_key": key,
                    "reason": clean_string(control.get("effective_reason")) or f"{key} is paused",
                }
            )

    if blocked_controls:
        summary = "; ".join(item["reason"] for item in blocked_controls)
        _append_unique(blockers, summary)
        checks["operator_controls"] = _risk_item(
            "operator_controls",
            status="blocked",
            summary=summary,
            details={"blocked_controls": blocked_controls},
        )
    else:
        checks["operator_controls"] = _risk_item(
            "operator_controls",
            status="ok",
            summary="operator controls allow execution advancement",
        )

    global_control = control_states.get("global") if isinstance(control_states.get("global"), dict) else {}
    if global_control.get("effective_paused"):
        reason = clean_string(global_control.get("effective_reason")) or "manual kill switch is active"
        checks["manual_kill_switch"] = _risk_item(
            "manual_kill_switch",
            status="blocked",
            summary=reason,
            details={"control_key": "global", "control": global_control},
        )
    else:
        checks["manual_kill_switch"] = _risk_item(
            "manual_kill_switch",
            status="ok",
            summary="manual kill switch is clear",
            details={"control_key": "global", "control": global_control},
        )

    return checks, blockers


def _evaluate_market_data_freshness(policy, scan_result, now_dt):
    threshold = int(policy.get("market_data_stale_after_seconds") or 0)
    reference_at = (
        ((scan_result.get("context") or {}) if isinstance(scan_result.get("context"), dict) else {}).get("reference_at")
        or ((scan_result.get("paper_trade_payload") or {}) if isinstance(scan_result.get("paper_trade_payload"), dict) else {}).get("reference_at")
    )
    age_seconds = _seconds_since(reference_at, now_dt=now_dt)
    if threshold < 1 or age_seconds is None:
        return _risk_item(
            "market_data_freshness",
            status="ok",
            summary="market-data freshness check is within policy",
            details={"reference_at": clean_string(reference_at), "age_seconds": age_seconds, "threshold_seconds": threshold},
        ), []
    if age_seconds > threshold:
        reason = f"market data is stale ({int(age_seconds)}s > {threshold}s)"
        return _risk_item(
            "market_data_freshness",
            status="blocked",
            summary=reason,
            details={"reference_at": clean_string(reference_at), "age_seconds": age_seconds, "threshold_seconds": threshold},
        ), [reason]
    return _risk_item(
        "market_data_freshness",
        status="ok",
        summary="market-data freshness check is within policy",
        details={"reference_at": clean_string(reference_at), "age_seconds": age_seconds, "threshold_seconds": threshold},
    ), []


def _evaluate_daily_realized_loss(store, policy, now_dt):
    limit = _to_number(policy.get("max_daily_realized_loss"), default=0.0)
    from_at = now_dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    outcomes = store.list_paper_trade_outcomes(limit=500, created_at_from=from_at)

    realized_loss = 0.0
    for item in outcomes:
        pnl = _to_number(item.get("realized_pnl"))
        if pnl is not None and pnl < 0:
            realized_loss += abs(pnl)

    if limit > 0 and realized_loss >= limit:
        reason = f"max daily realized loss reached ({realized_loss:.2f}/{limit:.2f})"
        return _risk_item(
            "daily_realized_loss",
            status="blocked",
            summary=reason,
            details={"realized_loss": realized_loss, "limit": limit, "from_at": from_at},
        ), [reason]

    return _risk_item(
        "daily_realized_loss",
        status="ok",
        summary="daily realized loss is within policy",
        details={"realized_loss": realized_loss, "limit": limit, "from_at": from_at},
    ), []


def _evaluate_daily_order_count(store, policy, now_dt):
    limit = _nested_int(
        policy,
        "daily_order_count",
        "max_count",
        legacy_key="max_daily_order_count",
        default=0,
    )
    from_at = now_dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    proposals = []
    if hasattr(store, "list_order_proposals"):
        proposals = store.list_order_proposals(limit=1000)
    daily_orders = [
        item
        for item in proposals
        if (parse_iso_datetime(item.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc))
        >= now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    ]
    projected_count = len(daily_orders) + 1

    if limit > 0 and projected_count > limit:
        reason = f"max daily order count would be exceeded ({projected_count}/{limit})"
        return _risk_item(
            "daily_order_count",
            status="blocked",
            summary=reason,
            details={
                "current_count": len(daily_orders),
                "projected_count": projected_count,
                "limit": limit,
                "from_at": from_at,
            },
        ), [reason]

    return _risk_item(
        "daily_order_count",
        status="ok",
        summary="daily order count is within policy",
        details={
            "current_count": len(daily_orders),
            "projected_count": projected_count,
            "limit": limit,
            "from_at": from_at,
        },
    ), []


def _evaluate_loss_streak(store, policy, now_dt):
    config = policy.get("loss_streak") if isinstance(policy.get("loss_streak"), dict) else {}
    max_losses = int(config.get("max_consecutive_losses") or 0)
    cooldown_seconds = int(config.get("cooldown_seconds") or 0)
    outcomes = store.list_paper_trade_outcomes(limit=100)

    streak = 0
    last_loss_at = None
    for item in outcomes:
        status = clean_string(item.get("result_status")) or ""
        if status in LOSS_RESULT_STATUSES:
            streak += 1
            if last_loss_at is None:
                last_loss_at = clean_string(item.get("created_at"))
            continue
        if status in LOSS_STREAK_RESET_STATUSES:
            break

    if max_losses > 0 and streak >= max_losses and last_loss_at:
        age_seconds = _seconds_since(last_loss_at, now_dt=now_dt)
        if age_seconds is not None and age_seconds < cooldown_seconds:
            reason = (
                f"loss-streak cooldown is active ({streak} consecutive losses; "
                f"{int(cooldown_seconds - age_seconds)}s remaining)"
            )
            return _risk_item(
                "loss_streak_cooldown",
                status="blocked",
                summary=reason,
                details={
                    "consecutive_losses": streak,
                    "max_consecutive_losses": max_losses,
                    "cooldown_seconds": cooldown_seconds,
                    "last_loss_at": last_loss_at,
                    "age_seconds": age_seconds,
                },
            ), [reason]

    return _risk_item(
        "loss_streak_cooldown",
        status="ok",
        summary="loss-streak cooldown is not active",
        details={
            "consecutive_losses": streak,
            "max_consecutive_losses": max_losses,
            "cooldown_seconds": cooldown_seconds,
            "last_loss_at": last_loss_at,
        },
    ), []


def _active_intents(store):
    return store.list_execution_intents(limit=500, terminal=False)


def _evaluate_intent_pressure(store, policy, intent_record):
    intent_record = intent_record if isinstance(intent_record, dict) else {}
    intent_payload = intent_record.get("intent") if isinstance(intent_record.get("intent"), dict) else {}
    intent_id = clean_string(intent_record.get("intent_id")) or clean_string(intent_payload.get("intent_id"))
    symbol = clean_string(intent_record.get("symbol")) or clean_string(intent_payload.get("symbol"))
    scan_signature = clean_string(intent_record.get("scan_signature")) or clean_string(intent_payload.get("scan_signature"))

    active_items = _active_intents(store)
    active_same_symbol = [item for item in active_items if clean_string(item.get("symbol")) == symbol]
    active_other_same_symbol = [item for item in active_same_symbol if clean_string(item.get("intent_id")) != intent_id]
    duplicates = [
        item for item in active_other_same_symbol
        if clean_string(item.get("scan_signature")) == scan_signature
    ]

    blockers = []
    checks = {}

    max_per_symbol = int(policy.get("max_active_intents_per_symbol") or 0)
    if max_per_symbol > 0 and (len(active_other_same_symbol) + 1) > max_per_symbol:
        reason = (
            f"max active intent count reached for {symbol} "
            f"({len(active_other_same_symbol) + 1}/{max_per_symbol})"
        )
        _append_unique(blockers, reason)
        checks["active_intents_per_symbol"] = _risk_item(
            "active_intents_per_symbol",
            status="blocked",
            summary=reason,
            details={"symbol": symbol, "active_count": len(active_other_same_symbol) + 1, "limit": max_per_symbol},
        )
    else:
        checks["active_intents_per_symbol"] = _risk_item(
            "active_intents_per_symbol",
            status="ok",
            summary="active intent count per symbol is within policy",
            details={"symbol": symbol, "active_count": len(active_other_same_symbol) + 1, "limit": max_per_symbol},
        )

    if duplicates:
        reason = "duplicate active intent already exists for this symbol and scan signature"
        _append_unique(blockers, reason)
        checks["duplicate_active_intent"] = _risk_item(
            "duplicate_active_intent",
            status="blocked",
            summary=reason,
            details={"symbol": symbol, "scan_signature": scan_signature, "duplicate_intent_ids": [item.get("intent_id") for item in duplicates]},
        )
    else:
        checks["duplicate_active_intent"] = _risk_item(
            "duplicate_active_intent",
            status="ok",
            summary="no duplicate active intent exists for this signal",
            details={"symbol": symbol, "scan_signature": scan_signature},
        )

    return checks, blockers, active_items


def _evaluate_open_exposure(store, policy, active_items):
    limit = _to_number(policy.get("max_open_exposure_notional"), default=0.0)
    total_notional = 0.0
    for item in active_items:
        proposal_id = clean_string(item.get("proposal_id"))
        if not proposal_id:
            continue
        proposal_record = store.get_order_proposal(proposal_id)
        if proposal_record is None:
            continue
        proposal = proposal_record.get("proposal") if isinstance(proposal_record.get("proposal"), dict) else {}
        request = proposal.get("request") if isinstance(proposal.get("request"), dict) else {}
        qty = _to_number(request.get("qty"), default=0.0) or 0.0
        price = _to_number(request.get("price"), default=0.0) or 0.0
        total_notional += qty * price

    if limit > 0 and total_notional >= limit:
        reason = f"max open exposure reached ({total_notional:.2f}/{limit:.2f})"
        return _risk_item(
            "open_exposure",
            status="blocked",
            summary=reason,
            details={"total_notional": total_notional, "limit": limit},
        ), [reason]

    return _risk_item(
        "open_exposure",
        status="ok",
        summary="open exposure is within policy",
        details={"total_notional": total_notional, "limit": limit},
    ), []


def _order_preview_from(scan_result, intent_record, order_preview=None):
    candidates = []
    if isinstance(order_preview, dict):
        candidates.append(order_preview)
    if isinstance(intent_record, dict):
        candidates.extend(
            item
            for item in (
                intent_record.get("order_preview"),
                intent_record.get("proposal"),
                intent_record.get("execution_plan"),
                (intent_record.get("intent") or {}).get("order_preview")
                if isinstance(intent_record.get("intent"), dict)
                else None,
            )
            if isinstance(item, dict)
        )
    if isinstance(scan_result, dict):
        candidates.extend(
            item
            for item in (
                scan_result.get("order_preview"),
                scan_result.get("execution_plan"),
            )
            if isinstance(item, dict)
        )

    levels = (
        scan_result.get("context", {}).get("auto_execution_levels")
        if isinstance(scan_result.get("context"), dict)
        else {}
    )
    levels = levels if isinstance(levels, dict) else {}

    for candidate in candidates:
        proposal = candidate.get("proposal") if isinstance(candidate.get("proposal"), dict) else candidate
        request = proposal.get("request") if isinstance(proposal.get("request"), dict) else {}
        futures = proposal.get("futures") if isinstance(proposal.get("futures"), dict) else {}
        symbol = (
            clean_string(_first_present(request, ["symbol"]))
            or clean_string(proposal.get("symbol"))
            or clean_string(futures.get("symbol"))
            or clean_string(scan_result.get("instrument") if isinstance(scan_result, dict) else None)
            or clean_string(intent_record.get("symbol") if isinstance(intent_record, dict) else None)
        )
        qty = _to_number(
            _first_present(request, ["qty", "quantity", "size"])
            or _first_present(proposal, ["qty", "quantity", "size"])
            or _first_present(futures, ["qty", "quantity", "size"])
        )
        price = _to_number(
            _first_present(request, ["price", "entry_price"])
            or _first_present(proposal, ["price", "entry_price"])
            or levels.get("entry_price")
        )
        notional = abs(qty * price) if qty is not None and price is not None else None
        return {
            "symbol": symbol,
            "qty": qty,
            "price": price,
            "notional": notional,
            "source": "order_preview",
        }

    symbol = (
        clean_string(scan_result.get("instrument") if isinstance(scan_result, dict) else None)
        or clean_string(intent_record.get("symbol") if isinstance(intent_record, dict) else None)
    )
    return {
        "symbol": symbol,
        "qty": None,
        "price": _to_number(levels.get("entry_price")),
        "notional": None,
        "source": "unavailable",
    }


def _evaluate_max_order_size(policy, scan_result, intent_record, order_preview=None):
    limit_notional = _nested_number(
        policy,
        "maximum_order_size",
        "max_notional",
        legacy_key="max_order_notional",
        default=0.0,
    )
    limit_qty = _nested_number(
        policy,
        "maximum_order_size",
        "max_qty",
        legacy_key="max_order_qty",
        default=0.0,
    )
    section = _policy_section(policy, "maximum_order_size")
    require_preview = bool(section.get("require_order_preview"))
    preview = _order_preview_from(scan_result, intent_record, order_preview=order_preview)

    if limit_notional <= 0 and limit_qty <= 0:
        return _risk_item(
            "max_order_size",
            status="ok",
            summary="maximum order-size check is not configured",
            details={"max_notional": limit_notional, "max_qty": limit_qty, "order_preview": preview},
        ), []

    if require_preview and (preview.get("qty") is None or (limit_notional > 0 and preview.get("notional") is None)):
        reason = "order-size preview is required before execution advancement"
        return _risk_item(
            "max_order_size",
            status="blocked",
            summary=reason,
            details={"max_notional": limit_notional, "max_qty": limit_qty, "order_preview": preview},
        ), [reason]

    if limit_qty > 0 and preview.get("qty") is not None and abs(preview["qty"]) > limit_qty:
        reason = f"max order quantity exceeded ({abs(preview['qty']):.8g}/{limit_qty:.8g})"
        return _risk_item(
            "max_order_size",
            status="blocked",
            summary=reason,
            details={"max_notional": limit_notional, "max_qty": limit_qty, "order_preview": preview},
        ), [reason]

    if limit_notional > 0 and preview.get("notional") is not None and preview["notional"] > limit_notional:
        reason = f"max order notional exceeded ({preview['notional']:.2f}/{limit_notional:.2f})"
        return _risk_item(
            "max_order_size",
            status="blocked",
            summary=reason,
            details={"max_notional": limit_notional, "max_qty": limit_qty, "order_preview": preview},
        ), [reason]

    return _risk_item(
        "max_order_size",
        status="ok",
        summary="maximum order size is within policy",
        details={"max_notional": limit_notional, "max_qty": limit_qty, "order_preview": preview},
    ), []


def _proposal_notional_from_record(proposal_record):
    proposal_record = proposal_record if isinstance(proposal_record, dict) else {}
    proposal = proposal_record.get("proposal") if isinstance(proposal_record.get("proposal"), dict) else proposal_record
    request = proposal.get("request") if isinstance(proposal.get("request"), dict) else {}
    qty = _to_number(_first_present(request, ["qty", "quantity", "size"]) or proposal.get("qty"), default=0.0) or 0.0
    price = _to_number(_first_present(request, ["price", "entry_price"]) or proposal.get("price"), default=0.0) or 0.0
    return abs(qty * price)


def _evaluate_symbol_exposure(store, policy, active_items, scan_result, intent_record, order_preview=None):
    limit = _nested_number(
        policy,
        "symbol_exposure",
        "max_intraday_position_exposure",
        legacy_key="max_intraday_position_exposure_per_symbol",
        default=0.0,
    )
    preview = _order_preview_from(scan_result, intent_record, order_preview=order_preview)
    target_symbol = clean_string(preview.get("symbol"))
    exposures = {}

    if hasattr(store, "list_execution_state"):
        for item in store.list_execution_state(limit=1000):
            symbol = clean_string(item.get("symbol"))
            if not symbol:
                continue
            size = _to_number(item.get("position_size"), default=0.0) or 0.0
            avg_price = _to_number(item.get("position_avg_price"), default=0.0) or 0.0
            exposures[symbol] = exposures.get(symbol, 0.0) + abs(size * avg_price)

    for item in active_items:
        proposal_id = clean_string(item.get("proposal_id"))
        symbol = clean_string(item.get("symbol"))
        if not proposal_id or not symbol:
            continue
        proposal_record = store.get_order_proposal(proposal_id) if hasattr(store, "get_order_proposal") else None
        exposures[symbol] = exposures.get(symbol, 0.0) + _proposal_notional_from_record(proposal_record)

    if target_symbol and preview.get("notional") is not None:
        exposures[target_symbol] = exposures.get(target_symbol, 0.0) + abs(preview["notional"])

    target_exposure = exposures.get(target_symbol, 0.0) if target_symbol else 0.0
    if limit > 0 and target_symbol and target_exposure > limit:
        reason = f"max intraday exposure reached for {target_symbol} ({target_exposure:.2f}/{limit:.2f})"
        return _risk_item(
            "symbol_exposure",
            status="blocked",
            summary=reason,
            details={
                "symbol": target_symbol,
                "projected_exposure": target_exposure,
                "limit": limit,
                "exposures": exposures,
                "order_preview": preview,
            },
        ), [reason]

    return _risk_item(
        "symbol_exposure",
        status="ok",
        summary="intraday symbol exposure is within policy",
        details={
            "symbol": target_symbol,
            "projected_exposure": target_exposure,
            "limit": limit,
            "exposures": exposures,
            "order_preview": preview,
        },
    ), []


def _evaluate_execution_state_freshness(store, policy, now_dt):
    threshold = int(policy.get("execution_state_stale_after_seconds") or 0)
    if threshold < 1:
        return _risk_item("execution_state_freshness", status="ok", summary="execution-state freshness check is within policy"), []

    active_items = _active_intents(store)
    stale_items = []
    for item in active_items:
        proposal_id = clean_string(item.get("proposal_id"))
        if not proposal_id:
            continue
        execution_state = store.get_execution_state(proposal_id)
        if execution_state is None:
            stale_items.append({"proposal_id": proposal_id, "reason": "missing execution state"})
            continue
        age_seconds = _seconds_since(execution_state.get("updated_at"), now_dt=now_dt)
        if age_seconds is None or age_seconds > threshold:
            stale_items.append({"proposal_id": proposal_id, "reason": "stale execution state", "age_seconds": age_seconds})

    if stale_items:
        reason = "stale execution-state lockout is active"
        return _risk_item(
            "execution_state_freshness",
            status="blocked",
            summary=reason,
            details={"threshold_seconds": threshold, "stale_items": stale_items},
        ), [reason]

    return _risk_item(
        "execution_state_freshness",
        status="ok",
        summary="execution-state freshness check is within policy",
        details={"threshold_seconds": threshold},
    ), []


def _evaluate_automatic_kill_switch(policy, checks):
    section = _policy_section(policy, "automatic_kill_switch")
    enabled = coerce_bool(section.get("enabled")) is True
    trigger_checks = section.get("trigger_checks")
    if not isinstance(trigger_checks, list) or not trigger_checks:
        trigger_checks = ["daily_realized_loss", "loss_streak_cooldown"]

    triggered = [
        {
            "check": name,
            "summary": clean_string((checks.get(name) or {}).get("summary")),
        }
        for name in trigger_checks
        if isinstance(checks.get(name), dict) and checks[name].get("status") == "blocked"
    ]

    if enabled and triggered:
        reason = f"automatic kill switch triggered by {triggered[0]['check']}"
        return _risk_item(
            "automatic_kill_switch",
            status="blocked",
            summary=reason,
            details={"enabled": enabled, "trigger_checks": trigger_checks, "triggered": triggered},
        ), [reason]

    return _risk_item(
        "automatic_kill_switch",
        status="ok",
        summary="automatic kill switch is clear",
        details={"enabled": enabled, "trigger_checks": trigger_checks, "triggered": triggered},
    ), []


def _evaluate_cancel_on_disconnect(policy, runtime_state):
    section = _policy_section(policy, "cancel_on_disconnect")
    enabled = coerce_bool(section.get("enabled")) is True
    block_new_orders = section.get("block_new_orders_when_disconnected")
    block_new_orders = True if block_new_orders is None else coerce_bool(block_new_orders) is not False
    runtime_state = runtime_state if isinstance(runtime_state, dict) else {}
    stream_state = runtime_state.get("private_stream")
    stream_state = stream_state if isinstance(stream_state, dict) else {}
    ready = stream_state.get("ready")
    reason_text = clean_string(stream_state.get("reason")) or "private stream disconnect state is unknown"

    if enabled and block_new_orders and ready is False:
        reason = f"cancel-on-disconnect guard is active: {reason_text}"
        return _risk_item(
            "cancel_on_disconnect",
            status="blocked",
            summary=reason,
            details={
                "enabled": enabled,
                "block_new_orders_when_disconnected": block_new_orders,
                "cancel_open_orders": coerce_bool(section.get("cancel_open_orders")) is True,
                "private_stream": stream_state,
            },
        ), [reason]

    return _risk_item(
        "cancel_on_disconnect",
        status="ok",
        summary="cancel-on-disconnect guard permits execution advancement",
        details={
            "enabled": enabled,
            "block_new_orders_when_disconnected": block_new_orders,
            "cancel_open_orders": coerce_bool(section.get("cancel_open_orders")) is True,
            "private_stream": stream_state,
        },
    ), []


def evaluate_execution_risk(
    *,
    store,
    policy,
    scan_result,
    intent_record,
    runtime_key=None,
    now_at=None,
    control_states=None,
    runtime_state=None,
    order_preview=None,
):
    now_dt = _now_at(now_at)
    policy = policy if isinstance(policy, dict) else {}
    scan_result = scan_result if isinstance(scan_result, dict) else {}
    intent_record = intent_record if isinstance(intent_record, dict) else {}

    checks = {}
    blocker_reasons = []

    control_checks, control_blockers = _resolve_control_blockers(control_states)
    checks.update(control_checks)
    blocker_reasons.extend(control_blockers)

    market_check, market_blockers = _evaluate_market_data_freshness(policy, scan_result, now_dt)
    checks["market_data_freshness"] = market_check
    blocker_reasons.extend(market_blockers)

    daily_check, daily_blockers = _evaluate_daily_realized_loss(store, policy, now_dt)
    checks["daily_realized_loss"] = daily_check
    blocker_reasons.extend(daily_blockers)

    order_count_check, order_count_blockers = _evaluate_daily_order_count(store, policy, now_dt)
    checks["daily_order_count"] = order_count_check
    blocker_reasons.extend(order_count_blockers)

    streak_check, streak_blockers = _evaluate_loss_streak(store, policy, now_dt)
    checks["loss_streak_cooldown"] = streak_check
    blocker_reasons.extend(streak_blockers)

    intent_checks, intent_blockers, active_items = _evaluate_intent_pressure(store, policy, intent_record)
    checks.update(intent_checks)
    blocker_reasons.extend(intent_blockers)

    order_size_check, order_size_blockers = _evaluate_max_order_size(
        policy,
        scan_result,
        intent_record,
        order_preview=order_preview,
    )
    checks["max_order_size"] = order_size_check
    blocker_reasons.extend(order_size_blockers)

    exposure_check, exposure_blockers = _evaluate_open_exposure(store, policy, active_items)
    checks["open_exposure"] = exposure_check
    blocker_reasons.extend(exposure_blockers)

    symbol_exposure_check, symbol_exposure_blockers = _evaluate_symbol_exposure(
        store,
        policy,
        active_items,
        scan_result,
        intent_record,
        order_preview=order_preview,
    )
    checks["symbol_exposure"] = symbol_exposure_check
    blocker_reasons.extend(symbol_exposure_blockers)

    sync_check, sync_blockers = _evaluate_execution_state_freshness(store, policy, now_dt)
    checks["execution_state_freshness"] = sync_check
    blocker_reasons.extend(sync_blockers)

    automatic_check, automatic_blockers = _evaluate_automatic_kill_switch(policy, checks)
    checks["automatic_kill_switch"] = automatic_check
    blocker_reasons.extend(automatic_blockers)

    disconnect_check, disconnect_blockers = _evaluate_cancel_on_disconnect(policy, runtime_state)
    checks["cancel_on_disconnect"] = disconnect_check
    blocker_reasons.extend(disconnect_blockers)

    state = "blocked" if blocker_reasons else "allow"
    summary = blocker_reasons[0] if blocker_reasons else "risk checks allow execution advancement"

    intent_payload = intent_record.get("intent") if isinstance(intent_record.get("intent"), dict) else {}
    return {
        "checked_at": now_dt.replace(microsecond=0).isoformat(),
        "runtime_key": clean_string(runtime_key),
        "intent_id": clean_string(intent_record.get("intent_id")) or clean_string(intent_payload.get("intent_id")),
        "proposal_id": clean_string(intent_record.get("proposal_id")) or clean_string(intent_payload.get("proposal_id")),
        "symbol": clean_string(intent_record.get("symbol")) or clean_string(intent_payload.get("symbol")),
        "state": state,
        "summary": summary,
        "blocker_reasons": blocker_reasons,
        "checks": checks,
    }
