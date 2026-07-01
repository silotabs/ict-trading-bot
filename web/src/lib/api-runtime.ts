import { API_BASE_URL, CONTROL_ROOM_QUERY, buildQuery, getJson, getJsonAllowingStatuses } from "./api-core";
import type {
  DashboardSnapshot,
  ExecutionIntentItem,
  ExecutionRiskCheckItem,
  ReadinessResponse,
  ShadowReviewSummary,
  SignalTraceItem,
} from "./api-types";

export async function fetchDashboardSnapshot(signal?: AbortSignal) {
  return getJson<DashboardSnapshot>(`/v1/control-room/snapshot?${CONTROL_ROOM_QUERY}`, { signal });
}

export async function fetchReadiness(signal?: AbortSignal) {
  return getJsonAllowingStatuses<ReadinessResponse>("/ready", [503], { signal });
}

export async function fetchSignalTraces(
  params: {
    limit?: number;
    symbol?: string;
    opportunity_state?: string;
    shadow_mode?: boolean;
    shadow_session_id?: string;
    signal?: AbortSignal;
  } = {},
) {
  const { signal, ...queryParams } = params;
  return getJson<{ items: SignalTraceItem[] }>(`/v1/signal-traces${buildQuery(queryParams)}`, { signal });
}

export async function fetchExecutionIntents(
  params: {
    limit?: number;
    symbol?: string;
    state?: string;
    terminal?: boolean;
    signal?: AbortSignal;
  } = {},
) {
  const { signal, ...queryParams } = params;
  return getJson<{ items: ExecutionIntentItem[] }>(`/v1/execution-intents${buildQuery(queryParams)}`, { signal });
}

export async function fetchExecutionRiskChecks(
  params: {
    limit?: number;
    symbol?: string;
    state?: string;
    runtime_key?: string;
    signal?: AbortSignal;
  } = {},
) {
  const { signal, ...queryParams } = params;
  return getJson<{ items: ExecutionRiskCheckItem[] }>(`/v1/execution-risk-checks${buildQuery(queryParams)}`, { signal });
}

export async function fetchShadowReviewSummary(
  params: {
    limit?: number;
    cluster_limit?: number;
    symbol?: string;
    shadow_session_id?: string;
    signal?: AbortSignal;
  } = {},
) {
  const { signal, ...queryParams } = params;
  return getJson<ShadowReviewSummary>(`/v1/shadow-review/summary${buildQuery(queryParams)}`, { signal });
}

export function subscribeControlRoom(handlers: {
  onOpen?: () => void;
  onSnapshot: (payload: DashboardSnapshot) => void;
  onError?: () => void;
}) {
  const stream = new EventSource(`${API_BASE_URL}/v1/control-room/stream?${CONTROL_ROOM_QUERY}`);

  stream.onopen = () => {
    handlers.onOpen?.();
  };

  stream.addEventListener("snapshot", (event) => {
    try {
      const payload = JSON.parse((event as MessageEvent<string>).data) as DashboardSnapshot;
      handlers.onSnapshot(payload);
    } catch {
      handlers.onError?.();
    }
  });

  stream.onerror = () => {
    handlers.onError?.();
  };

  return () => {
    stream.close();
  };
}
