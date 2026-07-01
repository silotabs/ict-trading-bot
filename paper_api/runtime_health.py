from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class RuntimeHealthDependencies:
    repositories: object
    resolve_control_state: object
    normalize_instrument: object
    age_seconds_from_iso: object
    clean_string: object
    coerce_bool: object
    first_present: object
    rules: dict
    thresholds: dict
    load_auto_execution_policy: object
    load_trade_management_policy: object
    strategy_version: str
    db_path: str
    tradingview_webhook_secret_configured: bool
    bybit_env: str
    bybit_market_base_url: str
    bybit_private_base_url: str
    bybit_private_submit_enabled: bool
    bybit_testnet_base_url: str
    bybit_testnet_submit_enabled: bool
    bybit_credentials_configured: bool
    operator_auth_configured: bool
    active_service_names: object = None


def build_operations_component(component_key, component_type, health, status, summary, details=None):
    return {
        "component_key": component_key,
        "component_type": component_type,
        "health": health,
        "status": status,
        "summary": summary,
        "details": details if isinstance(details, dict) else {},
    }


def build_control_component(deps, control_key):
    control = deps.resolve_control_state(control_key)
    if control["effective_paused"]:
        summary = control["effective_reason"] or f"{control_key} paused by control state"
        return build_operations_component(
            component_key=f"control:{control_key}",
            component_type="control",
            health="warning",
            status="paused",
            summary=summary,
            details={"control": control},
        )

    return build_operations_component(
        component_key=f"control:{control_key}",
        component_type="control",
        health="healthy",
        status="running",
        summary=f"{control_key} control is clear",
        details={"control": control},
    )


def build_submission_safety_component(deps):
    private_submit_enabled = bool(deps.bybit_private_submit_enabled)
    credentials_configured = bool(deps.bybit_credentials_configured)
    operator_auth_configured = bool(deps.operator_auth_configured)
    details = {
        "bybit_private_submit_enabled": private_submit_enabled,
        "bybit_credentials_configured": credentials_configured,
        "operator_auth_configured": operator_auth_configured,
        "operator_auth_header": "X-Trading-Operator-Token",
    }
    if not private_submit_enabled:
        return build_operations_component(
            component_key="submission_safety",
            component_type="submission_safety",
            health="healthy",
            status="disabled",
            summary="private venue submission is disabled",
            details=details,
        )
    if not credentials_configured or not operator_auth_configured:
        missing = []
        if not credentials_configured:
            missing.append("bybit credentials")
        if not operator_auth_configured:
            missing.append("operator auth token")
        return build_operations_component(
            component_key="submission_safety",
            component_type="submission_safety",
            health="error",
            status="misconfigured",
            summary=f"private venue submission enabled without {', '.join(missing)}",
            details=details,
        )
    return build_operations_component(
        component_key="submission_safety",
        component_type="submission_safety",
        health="healthy",
        status="guarded",
        summary="private venue submission is guarded by credentials and operator auth",
        details=details,
    )


def build_watchlist_component(deps, stale_after_seconds, now_dt=None):
    now_dt = now_dt if isinstance(now_dt, datetime) else datetime.now(timezone.utc)
    control = deps.resolve_control_state("scan_loop")
    records = deps.repositories.runtime_status.list_watchlist_state()
    record_map = {deps.normalize_instrument(item.get("instrument")): item for item in records}
    instrument_details = {}
    missing = []
    stale = []

    for instrument in deps.rules["allowed_instruments"]:
        record = record_map.get(instrument)
        if record is None:
            instrument_details[instrument] = {
                "status": "missing",
                "updated_at": None,
                "age_seconds": None,
            }
            missing.append(instrument)
            continue
        age_seconds = deps.age_seconds_from_iso(record.get("updated_at"), now_dt=now_dt)
        detail_status = "healthy"
        if age_seconds is None or age_seconds > stale_after_seconds:
            detail_status = "stale"
            stale.append(instrument)
        instrument_details[instrument] = {
            "status": detail_status,
            "updated_at": record.get("updated_at"),
            "age_seconds": age_seconds,
            "last_scan_signature": record.get("last_scan_signature"),
            "last_scan_decision": record.get("last_scan_decision"),
        }

    if control["effective_paused"]:
        return build_operations_component(
            component_key="watchlist_scan",
            component_type="watchlist_scan",
            health="warning",
            status="paused",
            summary=control["effective_reason"] or "watchlist scan paused by control state",
            details={
                "control": control,
                "threshold_seconds": stale_after_seconds,
                "instruments": instrument_details,
            },
        )

    if not records:
        return build_operations_component(
            component_key="watchlist_scan",
            component_type="watchlist_scan",
            health="warning",
            status="missing",
            summary="watchlist scan has not produced any persisted state yet",
            details={
                "threshold_seconds": stale_after_seconds,
                "instruments": instrument_details,
            },
        )

    if missing:
        return build_operations_component(
            component_key="watchlist_scan",
            component_type="watchlist_scan",
            health="warning",
            status="partial",
            summary=f"watchlist scan is missing persisted state for {', '.join(missing)}",
            details={
                "threshold_seconds": stale_after_seconds,
                "instruments": instrument_details,
            },
        )

    if stale:
        return build_operations_component(
            component_key="watchlist_scan",
            component_type="watchlist_scan",
            health="error",
            status="stale",
            summary=f"watchlist scan state is stale for {', '.join(stale)}",
            details={
                "threshold_seconds": stale_after_seconds,
                "instruments": instrument_details,
            },
        )

    latest_updated_at = max(
        (record.get("updated_at") for record in records if deps.clean_string(record.get("updated_at"))),
        default=None,
    )
    latest_age_seconds = deps.age_seconds_from_iso(latest_updated_at, now_dt=now_dt)
    return build_operations_component(
        component_key="watchlist_scan",
        component_type="watchlist_scan",
        health="healthy",
        status="healthy",
        summary="watchlist scan state is fresh",
        details={
            "threshold_seconds": stale_after_seconds,
            "latest_updated_at": latest_updated_at,
            "latest_age_seconds": latest_age_seconds,
            "instruments": instrument_details,
        },
    )


def build_public_market_component(deps, stale_after_seconds, now_dt=None):
    now_dt = now_dt if isinstance(now_dt, datetime) else datetime.now(timezone.utc)
    control = deps.resolve_control_state("scan_loop")
    records = [
        item
        for item in deps.repositories.runtime_status.list_operations_runtime()
        if deps.clean_string(item.get("runtime_key")).startswith("public_market:")
    ]
    if not records:
        return build_operations_component(
            component_key="public_market_event_path",
            component_type="public_market",
            health="warning",
            status="missing",
            summary="no public market event-path runtime has been recorded yet",
            details={"control": control, "threshold_seconds": stale_after_seconds},
        )

    record = records[0]
    state = record.get("state") if isinstance(record.get("state"), dict) else {}
    last_summary = record.get("last_summary") if isinstance(record.get("last_summary"), dict) else {}
    connection_status = deps.clean_string(state.get("connection_status")) or "unknown"
    event_path_state = deps.clean_string(state.get("event_path_state")) or (
        "receiving_events" if connection_status == "streaming" else "connected_no_flow" if connection_status == "connected" else "disconnected"
    )
    last_public_event_at = deps.clean_string(state.get("last_public_event_at"))
    last_confirmed_close_processed_at = deps.clean_string(state.get("last_confirmed_close_processed_at"))
    last_fallback_poll_at = deps.clean_string(state.get("last_fallback_poll_at"))
    last_fallback_carry_at = deps.clean_string(state.get("last_fallback_carry_at"))
    last_fallback_carry_reference_at = deps.clean_string(state.get("last_fallback_carry_reference_at"))
    fallback_reference_interval_seconds = state.get("fallback_reference_interval_seconds")
    next_fallback_due_at = deps.clean_string(state.get("next_fallback_due_at"))
    next_event_connect_due_at = deps.clean_string(state.get("next_event_connect_due_at"))
    fallback_interval_seconds = state.get("fallback_interval_seconds")
    fallback_active = bool(state.get("fallback_active"))
    consecutive_event_errors = int(state.get("consecutive_event_errors") or 0)
    event_reconnect_backoff_seconds = state.get("event_reconnect_backoff_seconds")
    event_age_seconds = deps.age_seconds_from_iso(last_public_event_at, now_dt=now_dt)
    processed_age_seconds = deps.age_seconds_from_iso(last_confirmed_close_processed_at, now_dt=now_dt)
    processed_reference_age_raw = deps.age_seconds_from_iso(
        deps.clean_string(state.get("last_confirmed_close_reference_at")),
        now_dt=now_dt,
        clamp_zero=False,
    )
    processed_reference_age_seconds = (
        max(0.0, processed_reference_age_raw) if processed_reference_age_raw is not None else None
    )
    processed_reference_in_future = bool(
        processed_reference_age_raw is not None and processed_reference_age_raw < 0
    )
    fallback_age_seconds = deps.age_seconds_from_iso(last_fallback_poll_at, now_dt=now_dt)
    fallback_carry_age_seconds = deps.age_seconds_from_iso(last_fallback_carry_at, now_dt=now_dt)
    fallback_carry_reference_age_raw = deps.age_seconds_from_iso(
        last_fallback_carry_reference_at,
        now_dt=now_dt,
        clamp_zero=False,
    )
    fallback_carry_reference_age_seconds = (
        max(0.0, fallback_carry_reference_age_raw) if fallback_carry_reference_age_raw is not None else None
    )
    fallback_carry_reference_in_future = bool(
        fallback_carry_reference_age_raw is not None and fallback_carry_reference_age_raw < 0
    )
    next_fallback_due_in_seconds = None
    next_fallback_overdue_seconds = None
    if next_fallback_due_at:
        try:
            next_due_dt = datetime.fromisoformat(next_fallback_due_at)
            if next_due_dt.tzinfo is None:
                next_due_dt = next_due_dt.replace(tzinfo=timezone.utc)
            next_delta_seconds = (
                next_due_dt.astimezone(timezone.utc) - now_dt.astimezone(timezone.utc)
            ).total_seconds()
            next_fallback_due_in_seconds = max(0.0, next_delta_seconds)
            next_fallback_overdue_seconds = max(0.0, -next_delta_seconds)
        except ValueError:
            next_fallback_due_in_seconds = None
            next_fallback_overdue_seconds = None
    fallback_interval_value = max(10, int(fallback_interval_seconds or 0)) if fallback_interval_seconds else None
    fallback_reference_interval_value = (
        max(10, int(fallback_reference_interval_seconds or 0))
        if fallback_reference_interval_seconds
        else None
    )
    fallback_grace_seconds = (
        max(5, min(30, int(round(fallback_interval_value * 0.5))))
        if fallback_interval_value is not None
        else stale_after_seconds
    )
    fallback_fresh_window_seconds = max(
        stale_after_seconds,
        int(fallback_interval_seconds or 0),
    )
    fallback_reference_fresh_window_seconds = max(
        fallback_fresh_window_seconds,
        int(fallback_reference_interval_value or 0)
        + int(fallback_interval_value or 0)
        + int(fallback_grace_seconds or 0),
    )
    primary_reference_interval_value = fallback_reference_interval_value or 300
    primary_grace_seconds = max(fallback_grace_seconds, 30)
    primary_fresh_window_seconds = max(
        stale_after_seconds,
        primary_reference_interval_value + primary_grace_seconds,
    )
    primary_fresh = (
        event_path_state == "receiving_events"
        and event_age_seconds is not None
        and processed_age_seconds is not None
        and event_age_seconds <= primary_fresh_window_seconds
        and processed_age_seconds <= primary_fresh_window_seconds
    )
    fallback_recent = (
        last_fallback_carry_at is not None
        and fallback_age_seconds is not None
        and (fallback_carry_reference_age_seconds is not None or fallback_carry_age_seconds is not None)
        and fallback_age_seconds <= fallback_fresh_window_seconds
        and (
            fallback_reference_interval_value is None
            or (
                fallback_carry_reference_age_seconds is not None
                and fallback_carry_reference_age_seconds <= fallback_reference_fresh_window_seconds
            )
            or (
                fallback_carry_reference_age_seconds is None
                and fallback_carry_age_seconds is not None
                and fallback_carry_age_seconds <= fallback_fresh_window_seconds
            )
        )
        and (
            next_fallback_overdue_seconds is None
            or next_fallback_overdue_seconds <= fallback_grace_seconds
        )
    )

    details = {
        "runtime_key": record.get("runtime_key"),
        "control": control,
        "threshold_seconds": stale_after_seconds,
        "connection_status": connection_status,
        "event_path_state": event_path_state,
        "updated_at": record.get("updated_at"),
        "heartbeat_at": record.get("heartbeat_at"),
        "last_public_event_at": last_public_event_at,
        "last_public_event_age_seconds": event_age_seconds,
        "last_confirmed_close_processed_at": last_confirmed_close_processed_at,
        "last_confirmed_close_processed_age_seconds": processed_age_seconds,
        "last_confirmed_close_reference_at": deps.clean_string(state.get("last_confirmed_close_reference_at")),
        "last_confirmed_close_reference_age_seconds": processed_reference_age_seconds,
        "last_confirmed_close_reference_in_future": processed_reference_in_future,
        "last_confirmed_close_reference_ms": state.get("last_confirmed_close_reference_ms"),
        "last_fallback_poll_at": last_fallback_poll_at,
        "last_fallback_poll_age_seconds": fallback_age_seconds,
        "last_fallback_carry_at": last_fallback_carry_at,
        "last_fallback_carry_age_seconds": fallback_carry_age_seconds,
        "last_fallback_carry_reference_at": last_fallback_carry_reference_at,
        "last_fallback_carry_reference_age_seconds": fallback_carry_reference_age_seconds,
        "last_fallback_carry_reference_in_future": fallback_carry_reference_in_future,
        "fallback_reference_interval_seconds": fallback_reference_interval_seconds,
        "fallback_interval_seconds": fallback_interval_seconds,
        "fallback_grace_seconds": fallback_grace_seconds,
        "fallback_fresh_window_seconds": fallback_fresh_window_seconds,
        "fallback_reference_fresh_window_seconds": fallback_reference_fresh_window_seconds,
        "primary_fresh_window_seconds": primary_fresh_window_seconds,
        "next_fallback_due_at": next_fallback_due_at,
        "next_fallback_due_in_seconds": next_fallback_due_in_seconds,
        "next_fallback_overdue_seconds": next_fallback_overdue_seconds,
        "fallback_active": fallback_active,
        "reconnect_count": int(state.get("reconnect_count") or 0),
        "consecutive_event_errors": consecutive_event_errors,
        "event_reconnect_backoff_seconds": event_reconnect_backoff_seconds,
        "next_event_connect_due_at": next_event_connect_due_at,
        "last_error": deps.clean_string(state.get("last_error")),
        "last_summary": last_summary,
    }

    if control["effective_paused"]:
        return build_operations_component(
            component_key="public_market_event_path",
            component_type="public_market",
            health="warning",
            status="paused",
            summary=control["effective_reason"] or "public market event path is paused by control state",
            details=details,
        )
    if primary_fresh:
        return build_operations_component(
            component_key="public_market_event_path",
            component_type="public_market",
            health="healthy",
            status="healthy_primary",
            summary="public candle-close event path is healthy",
            details=details,
        )
    if fallback_recent:
        return build_operations_component(
            component_key="public_market_event_path",
            component_type="public_market",
            health="warning",
            status="degraded_fallback",
            summary="public candle-close event path is degraded and fallback polling is currently carrying scans",
            details=details,
        )
    return build_operations_component(
        component_key="public_market_event_path",
        component_type="public_market",
        health="error",
        status="not_ready",
        summary=(
            "public candle-close stream is connected but no confirmed public close flow is healthy yet"
            if event_path_state == "connected_no_flow"
            else "public candle-close event path is degraded and fallback polling has not yet carried a confirmed scan"
            if fallback_active and last_fallback_carry_at is None
            else "public candle-close event path is not healthy enough and fallback polling is not carrying scans"
        ),
        details=details,
    )


def _build_runtime_components(
    deps,
    *,
    control_key,
    component_type,
    records,
    stale_after_seconds,
    policy_result=None,
    summary_label=None,
    status_fields=None,
):
    now_dt = datetime.now(timezone.utc)
    control = deps.resolve_control_state(control_key)
    status_fields = status_fields or {}
    if policy_result is not None and not policy_result["ok"]:
        return [
            build_operations_component(
                component_key=component_type,
                component_type=component_type,
                health="error",
                status="policy_error",
                summary=f"{component_type.replace('_', '-')} policy could not be loaded",
                details={
                    "control": control,
                    "policy_errors": policy_result["errors"],
                    "policy_path": policy_result["path"],
                    "threshold_seconds": stale_after_seconds,
                },
            )
        ]

    if not records:
        details = {"control": control, "threshold_seconds": stale_after_seconds}
        if policy_result is not None:
            details["policy_path"] = policy_result["path"]
        return [
            build_operations_component(
                component_key=component_type,
                component_type=component_type,
                health="warning",
                status="missing",
                summary=f"no {component_type.replace('_', ' ')} runtime has been recorded yet",
                details=details,
            )
        ]

    components = []
    for record in records:
        runtime_key = deps.clean_string(record.get("runtime_key")) or "default"
        age_seconds = deps.age_seconds_from_iso(record.get("updated_at"), now_dt=now_dt)
        state = record.get("state") if isinstance(record.get("state"), dict) else {}
        last_error = state.get("last_error") if isinstance(state.get("last_error"), dict) else None
        details = {
            "runtime_key": runtime_key,
            "control": control,
            "threshold_seconds": stale_after_seconds,
            "updated_at": record.get("updated_at"),
            "heartbeat_at": record.get("heartbeat_at"),
            "last_scan_at": record.get("last_scan_at"),
            "age_seconds": age_seconds,
            "last_summary": record.get("last_summary"),
            "last_error": last_error,
        }
        if policy_result is not None:
            details["policy_path"] = policy_result["path"]
        details.update(status_fields(runtime_key, record) if callable(status_fields) else {})

        if control["effective_paused"]:
            component = build_operations_component(
                component_key=f"{component_type}:{runtime_key}",
                component_type=component_type,
                health="warning",
                status="paused",
                summary=control["effective_reason"] or f"{summary_label or component_type} runtime {runtime_key} is paused",
                details=details,
            )
        elif age_seconds is None:
            component = build_operations_component(
                component_key=f"{component_type}:{runtime_key}",
                component_type=component_type,
                health="warning",
                status="unknown",
                summary=f"{summary_label or component_type} runtime {runtime_key} has no usable heartbeat timestamp",
                details=details,
            )
        elif age_seconds > stale_after_seconds:
            component = build_operations_component(
                component_key=f"{component_type}:{runtime_key}",
                component_type=component_type,
                health="error",
                status="stale",
                summary=f"{summary_label or component_type} runtime {runtime_key} is stale",
                details=details,
            )
        elif last_error:
            component = build_operations_component(
                component_key=f"{component_type}:{runtime_key}",
                component_type=component_type,
                health="warning",
                status="degraded",
                summary=f"{summary_label or component_type} runtime {runtime_key} reported an error on its last cycle",
                details=details,
            )
        else:
            component = build_operations_component(
                component_key=f"{component_type}:{runtime_key}",
                component_type=component_type,
                health="healthy",
                status="healthy",
                summary=f"{summary_label or component_type} runtime {runtime_key} is healthy",
                details=details,
            )
        components.append(component)
    return components


def build_supervisor_components(deps, stale_after_seconds):
    return _build_runtime_components(
        deps,
        control_key="supervisor",
        component_type="supervisor",
        records=deps.repositories.runtime_status.list_supervisor_runtime(),
        stale_after_seconds=stale_after_seconds,
        summary_label="supervisor",
    )


def build_private_stream_components(deps, stale_after_seconds, now_dt=None):
    now_dt = now_dt if isinstance(now_dt, datetime) else datetime.now(timezone.utc)
    control = deps.resolve_control_state("private_stream")
    records = deps.repositories.runtime_status.list_private_stream_runtime()
    if not records:
        return [
            build_operations_component(
                component_key="private_stream",
                component_type="private_stream",
                health="warning",
                status="missing",
                summary="no private stream runtime has been recorded yet",
                details={"control": control, "threshold_seconds": stale_after_seconds},
            )
        ]

    components = []
    for record in records:
        runtime_key = deps.clean_string(record.get("runtime_key")) or "default"
        connection_status = deps.clean_string(record.get("connection_status")) or "unknown"
        state = record.get("state") if isinstance(record.get("state"), dict) else {}
        last_message_at = deps.clean_string(record.get("last_message_at")) or deps.clean_string(state.get("last_message_at"))
        age_seconds = deps.age_seconds_from_iso(last_message_at or record.get("updated_at"), now_dt=now_dt)
        details = {
            "runtime_key": runtime_key,
            "control": control,
            "threshold_seconds": stale_after_seconds,
            "connection_status": connection_status,
            "updated_at": record.get("updated_at"),
            "heartbeat_at": record.get("heartbeat_at"),
            "connected_at": record.get("connected_at"),
            "last_message_at": last_message_at,
            "age_seconds": age_seconds,
            "subscriptions": record.get("subscriptions"),
            "state": state,
        }
        if control["effective_paused"]:
            component = build_operations_component(
                component_key=f"private_stream:{runtime_key}",
                component_type="private_stream",
                health="warning",
                status="paused",
                summary=control["effective_reason"] or f"private stream {runtime_key} is paused",
                details=details,
            )
        elif connection_status == "configuration_error":
            component = build_operations_component(
                component_key=f"private_stream:{runtime_key}",
                component_type="private_stream",
                health="error",
                status="configuration_error",
                summary=f"private stream {runtime_key} is missing required configuration",
                details=details,
            )
        elif connection_status == "disconnected":
            component = build_operations_component(
                component_key=f"private_stream:{runtime_key}",
                component_type="private_stream",
                health="error",
                status="disconnected",
                summary=f"private stream {runtime_key} is disconnected",
                details=details,
            )
        elif connection_status in {"connecting", "connected"}:
            component = build_operations_component(
                component_key=f"private_stream:{runtime_key}",
                component_type="private_stream",
                health="warning",
                status=connection_status,
                summary=f"private stream {runtime_key} is {connection_status}",
                details=details,
            )
        elif age_seconds is None:
            component = build_operations_component(
                component_key=f"private_stream:{runtime_key}",
                component_type="private_stream",
                health="warning",
                status="unknown",
                summary=f"private stream {runtime_key} has no usable heartbeat timestamp",
                details=details,
            )
        elif age_seconds > stale_after_seconds:
            component = build_operations_component(
                component_key=f"private_stream:{runtime_key}",
                component_type="private_stream",
                health="error",
                status="stale",
                summary=f"private stream {runtime_key} is stale",
                details=details,
            )
        else:
            component = build_operations_component(
                component_key=f"private_stream:{runtime_key}",
                component_type="private_stream",
                health="healthy",
                status=connection_status if connection_status == "streaming" else "healthy",
                summary=f"private stream {runtime_key} is healthy",
                details=details,
            )
        components.append(component)
    return components


def build_auto_execution_components(deps, stale_after_seconds):
    policy_result = deps.load_auto_execution_policy()
    if not policy_result["ok"]:
        return [
            build_operations_component(
                component_key="auto_execution",
                component_type="auto_execution",
                health="error",
                status="policy_error",
                summary="auto-execution policy could not be loaded",
                details={
                    "control": deps.resolve_control_state("auto_execution"),
                    "policy_errors": policy_result["errors"],
                    "policy_path": policy_result["path"],
                    "threshold_seconds": stale_after_seconds,
                },
            )
        ]

    policy = policy_result["policy"] or {}
    if deps.coerce_bool(policy.get("enabled")) is not True:
        return [
            build_operations_component(
                component_key="auto_execution",
                component_type="auto_execution",
                health="healthy",
                status="disabled",
                summary="auto execution policy is disabled",
                details={
                    "control": deps.resolve_control_state("auto_execution"),
                    "policy_path": policy_result["path"],
                    "threshold_seconds": stale_after_seconds,
                    "policy_enabled": False,
                },
            )
        ]

    return _build_runtime_components(
        deps,
        control_key="auto_execution",
        component_type="auto_execution",
        records=deps.repositories.runtime_status.list_auto_execution_runtime(),
        stale_after_seconds=stale_after_seconds,
        policy_result=policy_result,
        summary_label="auto execution",
        status_fields=lambda _runtime_key, record: {
            "submitted": deps.first_present(
                record.get("last_summary") if isinstance(record.get("last_summary"), dict) else {},
                ["submitted", "submission_count"],
            )
            or 0,
        },
    )


def build_trade_management_components(deps, stale_after_seconds):
    policy_result = deps.load_trade_management_policy()
    if not policy_result["ok"]:
        return [
            build_operations_component(
                component_key="trade_management",
                component_type="trade_management",
                health="error",
                status="policy_error",
                summary="trade-management policy could not be loaded",
                details={
                    "control": deps.resolve_control_state("trade_management"),
                    "policy_errors": policy_result["errors"],
                    "policy_path": policy_result["path"],
                    "threshold_seconds": stale_after_seconds,
                },
            )
        ]

    policy = policy_result["policy"] or {}
    if deps.coerce_bool(policy.get("enabled")) is not True:
        return [
            build_operations_component(
                component_key="trade_management",
                component_type="trade_management",
                health="healthy",
                status="disabled",
                summary="trade management policy is disabled",
                details={
                    "control": deps.resolve_control_state("trade_management"),
                    "policy_path": policy_result["path"],
                    "threshold_seconds": stale_after_seconds,
                    "policy_enabled": False,
                },
            )
        ]

    return _build_runtime_components(
        deps,
        control_key="trade_management",
        component_type="trade_management",
        records=deps.repositories.runtime_status.list_trade_management_runtime(),
        stale_after_seconds=stale_after_seconds,
        policy_result=policy_result,
        summary_label="trade management",
        status_fields=lambda _runtime_key, record: {
            "actions_applied": deps.first_present(
                record.get("last_summary") if isinstance(record.get("last_summary"), dict) else {},
                ["actions_applied"],
            )
            or 0,
        },
    )


def determine_operations_overall_health(components):
    if any(item.get("health") == "error" for item in components):
        return "error"
    if any(item.get("health") == "warning" for item in components):
        return "warning"
    return "healthy"


def _service_expectations(deps):
    active_service_names = deps.active_service_names
    if not isinstance(active_service_names, set):
        active_service_names = {
            clean_name
            for clean_name in (
                deps.clean_string(item)
                for item in (active_service_names or [])
            )
            if clean_name
        }
    if not active_service_names:
        return {
            "scan_loop_expected": True,
            "supervisor_expected": True,
            "private_stream_expected": True,
            "auto_execution_expected": True,
            "trade_management_expected": True,
            "planned_services": [],
        }

    auto_policy_result = deps.load_auto_execution_policy()
    trade_policy_result = deps.load_trade_management_policy()
    auto_policy = auto_policy_result.get("policy") if auto_policy_result.get("ok") else {}
    trade_policy = trade_policy_result.get("policy") if trade_policy_result.get("ok") else {}
    auto_enabled = deps.coerce_bool((auto_policy or {}).get("enabled")) is True
    trade_enabled = deps.coerce_bool((trade_policy or {}).get("enabled")) is True
    auto_requires_stream = deps.coerce_bool((auto_policy or {}).get("require_private_stream")) is True
    trade_requires_stream = deps.coerce_bool((trade_policy or {}).get("require_private_stream")) is True

    return {
        "scan_loop_expected": "scan_loop" in active_service_names,
        "supervisor_expected": "supervisor_loop" in active_service_names,
        "private_stream_expected": (
            "private_stream_loop" in active_service_names
            or (auto_enabled and auto_requires_stream)
            or (trade_enabled and trade_requires_stream)
        ),
        "auto_execution_expected": "auto_execute_loop" in active_service_names or auto_enabled,
        "trade_management_expected": "trade_management_loop" in active_service_names or trade_enabled,
        "planned_services": sorted(active_service_names),
    }


def _component_expected_for_readiness(component, expectations):
    component_key = component.get("component_key")
    component_type = component.get("component_type")
    if component_key == "submission_safety":
        return True
    if component_key in {"watchlist_scan", "public_market_event_path"}:
        return bool(expectations.get("scan_loop_expected"))
    if component_type == "supervisor":
        return bool(expectations.get("supervisor_expected"))
    if component_type == "private_stream":
        return bool(expectations.get("private_stream_expected"))
    if component_key == "auto_execution":
        return bool(expectations.get("auto_execution_expected"))
    if component_key == "trade_management":
        return bool(expectations.get("trade_management_expected"))
    return False


def build_operations_status(
    deps,
    *,
    watchlist_stale_after_seconds=None,
    supervisor_stale_after_seconds=None,
    private_stream_stale_after_seconds=None,
    public_market_stale_after_seconds=None,
    auto_execution_stale_after_seconds=None,
    trade_management_stale_after_seconds=None,
):
    def coerce_threshold(value, default):
        if value is None:
            return default
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return default

    watchlist_stale_after_seconds = coerce_threshold(
        watchlist_stale_after_seconds,
        deps.thresholds["watchlist_stale_after_seconds"],
    )
    supervisor_stale_after_seconds = coerce_threshold(
        supervisor_stale_after_seconds,
        deps.thresholds["supervisor_stale_after_seconds"],
    )
    private_stream_stale_after_seconds = coerce_threshold(
        private_stream_stale_after_seconds,
        deps.thresholds["private_stream_stale_after_seconds"],
    )
    public_market_stale_after_seconds = coerce_threshold(
        public_market_stale_after_seconds,
        deps.thresholds.get("public_market_stale_after_seconds", 120),
    )
    auto_execution_stale_after_seconds = coerce_threshold(
        auto_execution_stale_after_seconds,
        deps.thresholds["auto_execution_stale_after_seconds"],
    )
    trade_management_stale_after_seconds = coerce_threshold(
        trade_management_stale_after_seconds,
        deps.thresholds["trade_management_stale_after_seconds"],
    )
    now_dt = datetime.now(timezone.utc)
    components = [
        build_submission_safety_component(deps),
        build_control_component(deps, "global"),
        build_control_component(deps, "order_submission"),
        build_control_component(deps, "auto_execution"),
        build_control_component(deps, "trade_management"),
        build_watchlist_component(deps, watchlist_stale_after_seconds, now_dt=now_dt),
        build_public_market_component(deps, public_market_stale_after_seconds, now_dt=now_dt),
    ]
    components.extend(build_supervisor_components(deps, supervisor_stale_after_seconds))
    components.extend(build_private_stream_components(deps, private_stream_stale_after_seconds, now_dt=now_dt))
    components.extend(build_auto_execution_components(deps, auto_execution_stale_after_seconds))
    components.extend(build_trade_management_components(deps, trade_management_stale_after_seconds))

    counts_by_health = {"healthy": 0, "warning": 0, "error": 0}
    for item in components:
        counts_by_health[item["health"]] = counts_by_health.get(item["health"], 0) + 1
    overall_health = determine_operations_overall_health(components)

    return {
        "scanned_at": now_dt.replace(microsecond=0).isoformat(),
        "thresholds": {
            "watchlist_stale_after_seconds": watchlist_stale_after_seconds,
            "supervisor_stale_after_seconds": supervisor_stale_after_seconds,
            "private_stream_stale_after_seconds": private_stream_stale_after_seconds,
            "public_market_stale_after_seconds": public_market_stale_after_seconds,
            "auto_execution_stale_after_seconds": auto_execution_stale_after_seconds,
            "trade_management_stale_after_seconds": trade_management_stale_after_seconds,
        },
        "overall": {
            "health": overall_health,
            "component_count": len(components),
            "alert_count": counts_by_health.get("warning", 0) + counts_by_health.get("error", 0),
            "counts_by_health": counts_by_health,
        },
        "components": components,
    }


def build_health_payload(deps):
    global_control = deps.resolve_control_state("global")
    return {
        "status": "ok",
        "service": "paper-trading-api",
        "strategy_version": deps.strategy_version,
        "db_path": deps.db_path,
        "tradingview_webhook_secret_configured": bool(deps.tradingview_webhook_secret_configured),
        "bybit_env": deps.bybit_env,
        "bybit_market_base_url": deps.bybit_market_base_url,
        "bybit_private_base_url": deps.bybit_private_base_url,
        "bybit_private_submit_enabled": deps.bybit_private_submit_enabled,
        "bybit_testnet_base_url": deps.bybit_testnet_base_url,
        "bybit_testnet_submit_enabled": deps.bybit_testnet_submit_enabled,
        "bybit_credentials_configured": deps.bybit_credentials_configured,
        "operator_auth_configured": bool(deps.operator_auth_configured),
        "global_control_paused": global_control["effective_paused"],
        "global_control_reason": global_control["effective_reason"],
    }


def build_readiness_payload(deps):
    operations = build_operations_status(deps)
    service_expectations = _service_expectations(deps)
    critical_components = [
        item
        for item in operations["components"]
        if _component_expected_for_readiness(item, service_expectations)
    ]
    blockers = [
        {
            "component_key": item.get("component_key"),
            "status": item.get("status"),
            "summary": item.get("summary"),
        }
        for item in critical_components
        if item.get("status") not in {"healthy", "healthy_primary", "disabled", "streaming"}
    ]
    public_market_component = next(
        (item for item in critical_components if item.get("component_key") == "public_market_event_path"),
        None,
    )
    if blockers:
        if (
            len(blockers) == 1
            and public_market_component is not None
            and public_market_component.get("status") == "degraded_fallback"
        ):
            status = "degraded_fallback"
        else:
            status = "not_ready"
    else:
        status = "healthy_primary"
    return {
        "status": status,
        "service": "paper-trading-api",
        "checked_at": operations.get("scanned_at"),
        "critical_component_count": len(critical_components),
        "blocker_count": len(blockers),
        "blockers": blockers,
        "service_expectations": service_expectations,
        "operations": {
            "overall": operations.get("overall"),
            "components": critical_components,
        },
    }
