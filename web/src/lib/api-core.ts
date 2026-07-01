export const API_BASE_URL =
  (import.meta.env.VITE_TRADING_API_BASE_URL as string | undefined)?.trim() ||
  "http://127.0.0.1:8787";
export const OPERATOR_AUTH_TOKEN = (import.meta.env.VITE_TRADING_OPERATOR_TOKEN as string | undefined)?.trim() || "";

function buildRequestHeaders(extra: Record<string, string> = {}) {
  const headers: Record<string, string> = { ...extra };
  if (OPERATOR_AUTH_TOKEN) {
    headers["X-Trading-Operator-Token"] = OPERATOR_AUTH_TOKEN;
  }
  return headers;
}

type FetchOptions = {
  signal?: AbortSignal;
};

export async function getJson<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: buildRequestHeaders({
      Accept: "application/json",
    }),
    signal: options.signal,
  });

  if (!response.ok) {
    throw new Error(`Request failed for ${path}: ${response.status}`);
  }

  return (await response.json()) as T;
}

export async function getJsonAllowingStatuses<T>(
  path: string,
  allowedStatuses: number[],
  options: FetchOptions = {},
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: buildRequestHeaders({
      Accept: "application/json",
    }),
    signal: options.signal,
  });

  if (!response.ok && !allowedStatuses.includes(response.status)) {
    throw new Error(`Request failed for ${path}: ${response.status}`);
  }

  return (await response.json()) as T;
}

export async function postJson<T>(path: string, payload: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: buildRequestHeaders({
      Accept: "application/json",
      "Content-Type": "application/json",
    }),
    body: JSON.stringify(payload),
  });

  const body = (await response.json()) as T & { error?: string };
  if (!response.ok) {
    const message =
      typeof body === "object" && body && "error" in body && typeof body.error === "string"
        ? body.error
        : `Request failed for ${path}: ${response.status}`;
    throw new Error(message);
  }

  return body;
}

export function buildQuery(params: Record<string, string | number | boolean | null | undefined>) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    query.set(key, String(value));
  });
  const rendered = query.toString();
  return rendered ? `?${rendered}` : "";
}

export const CONTROL_ROOM_QUERY = new URLSearchParams({
  scan_limit: "50",
  proposal_limit: "8",
  execution_limit: "8",
  execution_action_limit: "12",
  auto_event_limit: "12",
  concept_event_limit: "8",
  timeline_limit: "24",
}).toString();
