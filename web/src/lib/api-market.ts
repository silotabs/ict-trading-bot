import { buildQuery, getJson } from "./api-core";
import type { KlinesPayload, TickerPayload } from "./api-types";

export async function fetchTicker(symbol: string, signal?: AbortSignal) {
  return getJson<TickerPayload>(`/v1/market/bybit/ticker?symbol=${encodeURIComponent(symbol)}`, { signal });
}

export async function fetchKlines(
  symbol: string,
  options: {
    interval?: string;
    limit?: number;
    signal?: AbortSignal;
  } = {},
) {
  const { interval = "5m", limit = 240, signal } = options;
  return getJson<KlinesPayload>(
    `/v1/market/bybit/klines${buildQuery({
      symbol,
      interval,
      limit,
    })}`,
    { signal },
  );
}
