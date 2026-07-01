import type { Candle, ExecutionStateItem, IctStructurePayload, ProposalItem } from "../lib/api";

export type StructureFocus = "sweep" | "mss" | "fvg" | "displacement" | "levels";

export type TerminalChartProps = {
  symbol: string;
  candles: Candle[];
  proposal: ProposalItem | null;
  execution: ExecutionStateItem | null;
  structure: IctStructurePayload | null;
  selectedStructureFocus: StructureFocus | null;
  structureFocusSource: "lens" | "event" | "none";
  onFocusStructure: (focus: StructureFocus) => void;
  selectedMarkerId: string | null;
  selectedTimeframe: string;
  ictContext: {
    biasTimeframe: string;
    setupTimeframe: string;
    executionTimeframe: string;
    sessionLabel: string;
    sessionValid: boolean;
    direction: string;
    decision: string;
    dominantBlocker: string;
    operatorSignal: string;
  };
  workflow: {
    steps: Array<{
      id: string;
      title: string;
      status: "complete" | "active" | "waiting" | "blocked";
      detail: string;
    }>;
    nextAction: string;
  };
  markers: Array<{
    id: string;
    at: string;
    label: string;
    tone: "good" | "warn" | "danger" | "neutral";
    detail: string;
  }>;
  status: {
    signal: string;
    tradeState: string;
    session: string;
    verdict: string;
    operatorSignal: string;
  };
};

export function formatMaybeNumber(value: string | number | null | undefined) {
  const numeric = Number(value ?? NaN);
  if (!Number.isFinite(numeric)) {
    return "-";
  }

  return formatPrice(numeric);
}

export function formatRelativeTime(value: string | null | undefined) {
  if (!value) {
    return "waiting";
  }

  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) {
    return "waiting";
  }

  const deltaSeconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000));
  if (deltaSeconds < 10) {
    return "just now";
  }
  if (deltaSeconds < 60) {
    return `${deltaSeconds}s ago`;
  }
  const deltaMinutes = Math.round(deltaSeconds / 60);
  if (deltaMinutes < 60) {
    return `${deltaMinutes}m ago`;
  }
  const deltaHours = Math.round(deltaMinutes / 60);
  return `${deltaHours}h ago`;
}

export function formatPrice(value: number) {
  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits: value > 1000 ? 2 : 2,
  }).format(value);
}

export function labelFromCandle(candle: Candle) {
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(candle.start_at));
}

export function levelAnnotation(label: string, y: number, stroke: string, width: number) {
  return (
    <g key={`${label}-${y}`}>
      <rect x={width - 62} y={y - 11} width="54" height="18" rx="8" fill="#071019" stroke={stroke} strokeWidth="1" />
      <text x={width - 35} y={y + 2.5} fill={stroke} fontSize="10" fontWeight="700" textAnchor="middle">
        {label}
      </text>
    </g>
  );
}

export function toneClasses(label: string) {
  const normalized = label.trim().toLowerCase();
  if (normalized.includes("buy") || normalized.includes("long") || normalized.includes("live")) {
    return "border-emerald-500/20 bg-emerald-500/10 text-emerald-200";
  }
  if (normalized.includes("sell") || normalized.includes("short") || normalized.includes("blocked")) {
    return "border-rose-500/20 bg-rose-500/10 text-rose-200";
  }
  if (normalized.includes("candidate") || normalized.includes("watch") || normalized.includes("collect")) {
    return "border-amber-500/20 bg-amber-500/10 text-amber-100";
  }
  return "border-cyan-500/20 bg-cyan-500/10 text-cyan-200";
}

export function markerStroke(tone: "good" | "warn" | "danger" | "neutral") {
  if (tone === "good") {
    return "#34d399";
  }
  if (tone === "warn") {
    return "#fbbf24";
  }
  if (tone === "danger") {
    return "#fb7185";
  }
  return "#22d3ee";
}
