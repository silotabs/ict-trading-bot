from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Protocol


class ShadowReviewSummarizer(Protocol):
    def __call__(self, trace_records, *, cluster_limit=10, only_false_negative_candidates=False):
        ...


def default_shadow_review_summarizer(trace_records, *, cluster_limit=10, only_false_negative_candidates=False):
    summarize_shadow_review = import_module("shadow_review").summarize_shadow_review

    return summarize_shadow_review(
        trace_records,
        cluster_limit=cluster_limit,
        only_false_negative_candidates=only_false_negative_candidates,
    )


@dataclass
class SignalTraceRepository:
    store: object
    shadow_review_summarizer: ShadowReviewSummarizer = default_shadow_review_summarizer

    def create(self, trace):
        return self.store.create_signal_trace(trace)

    def list(self, **filters):
        return self.store.list_signal_traces(**filters)

    def get(self, trace_id):
        return self.store.get_signal_trace(trace_id)

    def list_records(self, **filters):
        blocker_reason_contains = filters.pop("blocker_reason_contains", None)
        items = self.list(**filters)
        records = []
        for item in items:
            record = self.get(item.get("trace_id"))
            if record is None:
                continue
            if blocker_reason_contains:
                needle = str(blocker_reason_contains).strip().lower()
                blocker_reasons = (
                    ((record.get("trace") or {}).get("blocker_reasons"))
                    if isinstance(record.get("trace"), dict)
                    else []
                )
                joined = " ".join(str(value) for value in (blocker_reasons or [])).lower()
                if needle not in joined:
                    continue
            records.append(record)
        return records

    def summarize_shadow_review(self, *, cluster_limit=10, only_false_negative_candidates=False, **filters):
        records = self.list_records(**filters)
        return self.shadow_review_summarizer(
            records,
            cluster_limit=cluster_limit,
            only_false_negative_candidates=only_false_negative_candidates,
        )


@dataclass
class ExecutionIntentRepository:
    store: object

    def create_or_get(self, intent):
        return self.store.create_or_get_execution_intent(intent)

    def list(self, **filters):
        return self.store.list_execution_intents(**filters)

    def get(self, intent_id):
        return self.store.get_execution_intent(intent_id)

    def transition(self, intent_id, next_state, **kwargs):
        return self.store.transition_execution_intent(intent_id, next_state, **kwargs)

    def list_events(self, **filters):
        return self.store.list_execution_intent_events(**filters)

    def get_event(self, event_id):
        return self.store.get_execution_intent_event(event_id)


@dataclass
class ExecutionRiskCheckRepository:
    store: object

    def create(self, risk_check):
        return self.store.create_execution_risk_check(risk_check)

    def list(self, **filters):
        return self.store.list_execution_risk_checks(**filters)

    def get(self, risk_check_id):
        return self.store.get_execution_risk_check(risk_check_id)


@dataclass
class RuntimeStatusRepository:
    store: object

    def list_watchlist_state(self):
        return self.store.list_watchlist_state()

    def list_supervisor_runtime(self):
        return self.store.list_supervisor_runtime()

    def list_private_stream_runtime(self):
        return self.store.list_private_stream_runtime()

    def list_auto_execution_runtime(self):
        return self.store.list_auto_execution_runtime()

    def list_trade_management_runtime(self):
        return self.store.list_trade_management_runtime()

    def list_operations_runtime(self):
        return self.store.list_operations_runtime()


@dataclass
class TradingRepositories:
    signal_traces: SignalTraceRepository
    execution_intents: ExecutionIntentRepository
    execution_risk_checks: ExecutionRiskCheckRepository
    runtime_status: RuntimeStatusRepository


def build_runtime_repositories(store, *, shadow_review_summarizer=default_shadow_review_summarizer):
    return TradingRepositories(
        signal_traces=SignalTraceRepository(store, shadow_review_summarizer=shadow_review_summarizer),
        execution_intents=ExecutionIntentRepository(store),
        execution_risk_checks=ExecutionRiskCheckRepository(store),
        runtime_status=RuntimeStatusRepository(store),
    )
