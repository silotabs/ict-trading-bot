from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone


FALSE_NEGATIVE_STATES = {"near_miss", "awaiting_confirmation"}


def _clean(value):
    text = str(value).strip() if value is not None else ""
    return text or None


def _append_unique(items, value):
    cleaned = _clean(value)
    if cleaned and cleaned not in items:
        items.append(cleaned)


def _trace_payload(record):
    trace = record.get("trace") if isinstance(record.get("trace"), dict) else {}
    return trace if isinstance(trace, dict) else {}


def _cluster_key(record):
    trace = _trace_payload(record)
    blocker_reasons = trace.get("blocker_reasons") if isinstance(trace.get("blocker_reasons"), list) else []
    primary = _clean(record.get("primary_blocker_reason")) or _clean(blocker_reasons[0]) or "unclassified blocker"
    return primary


def summarize_shadow_review(trace_records, *, cluster_limit=10, only_false_negative_candidates=False):
    items = [item for item in (trace_records or []) if isinstance(item, dict)]
    if only_false_negative_candidates:
        items = [
            item
            for item in items
            if not bool(item.get("execution_eligible"))
            and _clean(item.get("opportunity_state")) in FALSE_NEGATIVE_STATES
        ]

    by_decision = Counter()
    by_opportunity_state = Counter()
    by_blocker_class = Counter()
    by_symbol = Counter()
    by_session_state = Counter()
    by_shadow_session = Counter()
    blocker_clusters = defaultdict(
        lambda: {
            "count": 0,
            "decisions": Counter(),
            "opportunity_states": Counter(),
            "symbols": Counter(),
            "session_states": Counter(),
        }
    )
    reference_timestamps = []

    for item in items:
        decision = _clean(item.get("decision")) or "unset"
        opportunity_state = _clean(item.get("opportunity_state")) or "unset"
        blocker_class = _clean(item.get("blocker_class")) or "unset"
        symbol = _clean(item.get("symbol")) or "unset"
        session_state = _clean(item.get("session_state")) or "unset"
        shadow_session_id = _clean(item.get("shadow_session_id")) or "none"
        reference_timestamp = _clean(item.get("reference_timestamp"))

        by_decision[decision] += 1
        by_opportunity_state[opportunity_state] += 1
        by_blocker_class[blocker_class] += 1
        by_symbol[symbol] += 1
        by_session_state[session_state] += 1
        by_shadow_session[shadow_session_id] += 1
        if reference_timestamp:
            reference_timestamps.append(reference_timestamp)

        cluster = blocker_clusters[_cluster_key(item)]
        cluster["count"] += 1
        cluster["decisions"][decision] += 1
        cluster["opportunity_states"][opportunity_state] += 1
        cluster["symbols"][symbol] += 1
        cluster["session_states"][session_state] += 1

    sorted_clusters = sorted(
        blocker_clusters.items(),
        key=lambda item: (-item[1]["count"], item[0]),
    )
    blocker_cluster_items = []
    for reason, detail in sorted_clusters[: max(1, int(cluster_limit or 10))]:
        blocker_cluster_items.append(
            {
                "reason": reason,
                "count": detail["count"],
                "top_decisions": dict(detail["decisions"].most_common(3)),
                "top_opportunity_states": dict(detail["opportunity_states"].most_common(3)),
                "top_symbols": dict(detail["symbols"].most_common(3)),
                "top_session_states": dict(detail["session_states"].most_common(3)),
            }
        )

    false_negative_count = sum(
        1
        for item in items
        if not bool(item.get("execution_eligible"))
        and _clean(item.get("opportunity_state")) in FALSE_NEGATIVE_STATES
    )

    return {
        "computed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "trace_count": len(items),
        "false_negative_candidate_count": false_negative_count,
        "by_decision": dict(by_decision),
        "by_opportunity_state": dict(by_opportunity_state),
        "by_blocker_class": dict(by_blocker_class),
        "by_symbol": dict(by_symbol),
        "by_session_state": dict(by_session_state),
        "by_shadow_session": dict(by_shadow_session),
        "blocker_clusters": blocker_cluster_items,
        "reference_window": {
            "from": min(reference_timestamps) if reference_timestamps else None,
            "to": max(reference_timestamps) if reference_timestamps else None,
        },
    }
