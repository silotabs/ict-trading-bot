import { useDeferredValue, useEffect, useMemo, useRef, useState, type ChangeEvent, type ReactNode } from "react";
import {
  Activity,
  BrainCircuit,
  Clock3,
  FileSearch,
  GitBranch,
  PanelBottom,
  Radar,
  Shield,
  SlidersHorizontal,
  Diamond,
  TrainFront,
  ChartBar,
  BookOpen,
  ArrowDownToLine,
  ArrowUpToLine,
  Cable,
  ShieldPlus,
  type LucideIcon,
} from "lucide-react";
import { TerminalChart } from "../components/TerminalChart";
import {
  API_BASE_URL,
  type ConceptAcceptanceHistoryItem,
  type ConceptAcceptanceSummary,
  type ConceptRevisionCompareSummary,
  type ConceptStage7DecisionSummary,
  type ConceptStageStatusSummary,
  type Candle,
  type ConceptRevisionSummaryItem,
  type ConceptReviewSummaryItem,
  type ConceptRuntimeItem,
  type ControlItem,
  type ControlRoomTimelineItem,
  type DashboardSnapshot,
  type EventItem,
  type ExecutionActionItem,
  type ExecutionIntentItem,
  type ExecutionRiskCheckItem,
  type ExecutionStateItem,
  type IctStructurePayload,
  type OperationsComponentItem,
  type ProposalItem,
  type PublicEventStreamDetails,
  type ReadinessResponse,
  type ScanHistoryItem,
  type ShadowReviewSummary,
  type SignalTraceItem,
  type TickerPayload,
  cancelProposal,
  fetchDashboardSnapshot,
  fetchExecutionIntents,
  fetchExecutionRiskChecks,
  fetchKlines,
  fetchReadiness,
  fetchShadowReviewSummary,
  fetchSignalTraces,
  subscribeControlRoom,
  submitProposal,
  syncProposal,
  updateControlState,
  updateKillSwitch,
} from "../lib/api";

export const ACTIVE_SYNC_STATUSES = new Set([
  "planned",
  "submitted",
  "working",
  "partially_filled",
  "position_open",
  "filled",
  "unknown",
]);

export const TERMINAL_SYNC_STATUSES = new Set(["cancelled", "rejected", "failed", "closed"]);

export type StreamState = "connecting" | "live" | "delayed";
export type WorkflowStatus = "complete" | "active" | "waiting" | "blocked";
export type StructureFocus = "sweep" | "mss" | "fvg" | "displacement" | "levels";
export type WorkspaceTab = "console" | "review" | "execution" | "rules" | "desk";
export type RightRailTab = "intelligence" | "revision" | "desk";
export type EventConsoleFilter = "all" | "scan" | "proposal" | "execution" | "concept" | "control" | "ops";
export type EventConsoleSeverityFilter = "all" | "error" | "warning" | "info";
export type EventConsolePreset = "custom" | "execution_triage" | "concept_review" | "control_actions";
export type EventConsoleScope = "selected" | "global";
export type ChartTimeframe = "4H" | "15m" | "5m";
export type GroupedTimelineItem = {
  representative: ControlRoomTimelineItem;
  count: number;
  members: ControlRoomTimelineItem[];
};
export type ScoredGroupedTimelineItem = GroupedTimelineItem & {
  relevanceScore: number;
  relevanceLabel: "high" | "medium" | "watch";
  relevanceReasons: string[];
  relevanceBreakdown: Array<{
    label: string;
    points: number;
  }>;
};
export type ActionState = {
  status: "idle" | "pending" | "success" | "error";
  message: string | null;
  actionKey: string | null;
};
export type WorkflowStep = {
  id: string;
  title: string;
  status: WorkflowStatus;
  detail: string;
};
export type CommandPaletteAction = {
  id: string;
  title: string;
  group: string;
  meta?: string;
  keywords: string;
  run: () => void;
};
export type SavedOperatorSceneState = {
  symbol: string;
  preset: EventConsolePreset;
  filter: EventConsoleFilter;
  severity: EventConsoleSeverityFilter;
  scope: EventConsoleScope;
  workspaceTab: WorkspaceTab;
  followFocus: boolean;
  structureFocus: StructureFocus | null;
  openReview: boolean;
  focusTop: boolean;
};
export type SavedOperatorScene = {
  id: string;
  name: string;
  savedAt: string;
  isDefault?: boolean;
  state: SavedOperatorSceneState;
};
export type OperatorScene = {
  id: string;
  title: string;
  description: string;
  meta: string;
  active: boolean;
  disabled?: boolean;
  run: () => void;
};
export type ChartMarker = {
  id: string;
  at: string;
  label: string;
  tone: "good" | "warn" | "danger" | "neutral";
  detail: string;
};
export type SessionBoardSpec = {
  id: string;
  label: string;
  timeZone: string;
  openHour: number;
  closeHour: number;
};
export type SessionBoardState = {
  id: string;
  label: string;
  timeZone: string;
  currentTime: string;
  timeLabel: string;
  windowLabel: string;
  status: "open" | "opening_soon" | "closed";
  detail: string;
  allowed: boolean;
  active: boolean;
};
export type RuntimeRevisionResult = {
  revision_id: string;
  review_id: string;
  status: string;
  summary?: string;
  skipped?: boolean;
  reason?: string;
  current_sample_started_at?: string | null;
  history_count?: number | null;
};
export type RuntimeLinkedRevision = {
  review_id: string;
  revision_id: string;
  focus?: string | null;
  mode?: string | null;
  readiness?: string | null;
};

export const SAVED_OPERATOR_SCENES_STORAGE_KEY = "trading-operator-scenes-v1";
export const CHART_TIMEFRAME_OPTIONS: Array<{ value: ChartTimeframe; label: string; limit: number }> = [
  { value: "4H", label: "4H", limit: 180 },
  { value: "15m", label: "15m", limit: 360 },
  { value: "5m", label: "5m", limit: 520 },
];
export const SESSION_BOARD_SPECS: SessionBoardSpec[] = [
  { id: "sydney", label: "Sydney", timeZone: "Australia/Sydney", openHour: 7, closeHour: 16 },
  { id: "tokyo", label: "Tokyo", timeZone: "Asia/Tokyo", openHour: 9, closeHour: 18 },
  { id: "london", label: "London", timeZone: "Europe/London", openHour: 8, closeHour: 17 },
  { id: "new_york", label: "New York", timeZone: "America/New_York", openHour: 8, closeHour: 17 },
];

export function formatTimestamp(value: string | null | undefined) {
  if (!value) {
    return "n/a";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
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
  if (deltaSeconds < 8) {
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

export function formatPrice(value: string | number | null | undefined) {
  const numeric = Number(value ?? NaN);
  if (!Number.isFinite(numeric)) {
    return "-";
  }

  return new Intl.NumberFormat(undefined, {
    minimumFractionDigits: numeric >= 1000 ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(numeric);
}

export function formatPercent(value: string | number | null | undefined) {
  const numeric = Number(value ?? NaN);
  if (!Number.isFinite(numeric)) {
    return "-";
  }

  return `${numeric >= 0 ? "+" : ""}${(numeric * 100).toFixed(2)}%`;
}

export function formatRatioPercent(value: unknown) {
  const numeric = Number(value ?? NaN);
  if (!Number.isFinite(numeric)) {
    return "-";
  }

  return `${Math.round(numeric * 100)}%`;
}

export function cleanLabel(value: string) {
  return value.split("_").join(" ");
}

export function normalizeSessionKey(value: string | null | undefined) {
  const normalized = String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "_");

  if (!normalized) {
    return "outside";
  }
  if (normalized === "newyork" || normalized === "ny") {
    return "new_york";
  }
  if (normalized === "ldn") {
    return "london";
  }
  if (normalized === "syd") {
    return "sydney";
  }
  if (normalized === "tky") {
    return "tokyo";
  }

  return normalized;
}

export function isSessionAllowedInConfig(sessionLabel: string | null | undefined, allowedSessions: string[]) {
  const normalizedTarget = normalizeSessionKey(sessionLabel);
  return allowedSessions.some((item) => normalizeSessionKey(item) === normalizedTarget);
}

export function isOutsideSessionAllowed(allowedSessions: string[]) {
  return isSessionAllowedInConfig("outside", allowedSessions);
}

export function formatSessionDisplayLabel(
  sessionLabel: string | null | undefined,
  allowedSessions: string[],
  fallback = "outside",
) {
  const normalized = normalizeSessionKey(sessionLabel ?? fallback);
  if (normalized === "outside" && isOutsideSessionAllowed(allowedSessions)) {
    return "outside allowed";
  }
  return cleanLabel(normalized || fallback);
}

export function formatSessionAwareCopy(value: string | null | undefined, outsideAllowed: boolean) {
  const text = String(value ?? "").trim();
  if (!text) {
    return "-";
  }
  if (!outsideAllowed) {
    return text;
  }

  return text
    .replace(/The market is currently outside the allowed session windows for Concept 1\./gi, "Outside session is allowed for this run.")
    .replace(/Wait for the next allowed session window so Concept 1 can be judged in its intended market conditions\./gi, "Session timing is already open for this run. Keep watching structure and confirmation instead.")
    .replace(/outside the allowed paper-trading windows/gi, "outside session, allowed for this run")
    .replace(/outside the allowed session windows/gi, "outside session, allowed for this run")
    .replace(/\bsession outside\b/gi, "session outside allowed");
}

export function formatBlockerClassLabel(value: string | null | undefined, outsideAllowed: boolean) {
  const normalized = String(value ?? "no_blocker").trim().toLowerCase();
  if (outsideAllowed && normalized === "session_window") {
    return "session override";
  }
  return cleanLabel(normalized || "no_blocker");
}

export function formatOperatorStatusLabel(value: string | null | undefined, outsideAllowed = false) {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (normalized === ["no", "paper", "trade"].join("_")) {
    return "Not executable";
  }
  switch (normalized) {
    case "verified_paper_trade":
      return "Executable";
    case "not_ready":
    case "not_aligned":
    case "no_opportunity":
      return "Not executable";
    case "session_window":
    case "outside_session":
      return outsideAllowed ? "Outside session allowed" : "Outside session";
    case "collect_more_evidence":
    case "awaiting_updates":
    case "awaiting_confirmation":
      return "Collecting evidence";
    case "healthy_primary":
      return "Primary stream healthy";
    case "degraded_fallback":
      return "Fallback carrying scans";
    case "receiving_events":
      return "Receiving candle closes";
    case "connected_no_flow":
      return "Connected, awaiting closes";
    case "execution_plan_created":
      return "Plan created";
    case "order_submission_pending":
      return "Submission pending";
    case "order_submitted":
      return "Submitted";
    case "order_acknowledged":
      return "Acknowledged";
    case "fully_filled":
      return "Filled";
    case "blocked":
      return "Risk blocked";
    case "allow":
    case "allowed":
      return "Risk allowed";
    case "":
      return "-";
    default:
      return cleanLabel(normalized);
  }
}

export function isExecutionEligibleDecision(decision: string | null | undefined) {
  return decision === "verified_paper_trade";
}

export function rawStatusTitle(label: string, value: string | number | boolean | null | undefined) {
  const rendered = value === null || value === undefined || value === "" ? "-" : String(value);
  return `${label} raw: ${rendered}`;
}

export function findPublicEventStreamComponent(
  readiness: ReadinessResponse | null | undefined,
): OperationsComponentItem | null {
  return (
    readiness?.operations.components.find(
      (item) => item.component_key === "public_market_event_path" || item.component_type === "public_market",
    ) ?? null
  );
}

export function publicEventStreamDetails(
  component: OperationsComponentItem | null | undefined,
): PublicEventStreamDetails {
  return (component?.details ?? {}) as PublicEventStreamDetails;
}

export function publicEventStreamBadgeStatus(
  value: string | null | undefined,
): "good" | "warn" | "danger" | "neutral" {
  switch (value) {
    case "healthy_primary":
    case "receiving_events":
    case "streaming":
      return "good";
    case "degraded_fallback":
    case "connected_no_flow":
    case "connected":
      return "warn";
    case "not_ready":
    case "disconnected":
    case "missing":
      return "danger";
    default:
      return "neutral";
  }
}

export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

export function asRecordList<T extends Record<string, unknown>>(value: unknown): T[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is T => Boolean(item) && typeof item === "object" && !Array.isArray(item));
}

export function revisionStatusBadgeStatus(value: string | null | undefined): "good" | "warn" | "danger" | "neutral" {
  switch (value) {
    case "improved":
      return "good";
    case "awaiting_fresh_sample":
    case "planned":
      return "warn";
    case "regressed":
      return "danger";
    case "flat":
    default:
      return "neutral";
  }
}

export function revisionCompareVerdictBadgeStatus(value: string | null | undefined): "good" | "warn" | "danger" | "neutral" {
  switch (value) {
    case "keep_current_leader":
      return "good";
    case "hold_revision_loop":
      return "warn";
    case "promote_runner_up":
      return "danger";
    default:
      return "neutral";
  }
}

export function stageGateBadgeStatus(value: string | null | undefined): "good" | "warn" | "danger" | "neutral" {
  switch (value) {
    case "ready_for_stage_6_from_daemon_state":
      return "good";
    case "stabilizing":
      return "warn";
    case "not_ready":
      return "danger";
    default:
      return "neutral";
  }
}

export function acceptanceStatusBadgeStatus(value: string | null | undefined): "good" | "warn" | "danger" | "neutral" {
  switch (value) {
    case "ready_for_stage_7_decision":
      return "good";
    case "collecting_evidence":
    case "observing_revision_outcomes":
      return "warn";
    case "blocked_by_stage_5":
      return "danger";
    default:
      return "neutral";
  }
}

export function readinessBadgeStatus(value: string | null | undefined): "good" | "warn" | "danger" | "neutral" {
  switch (value) {
    case "ready":
    case "healthy_primary":
      return "good";
    case "degraded":
    case "degraded_fallback":
      return "warn";
    case "blocked":
    case "not_ready":
      return "danger";
    default:
      return "neutral";
  }
}

export function executionIntentBadgeStatus(value: string | null | undefined): "good" | "warn" | "danger" | "neutral" {
  switch (value) {
    case "fully_filled":
    case "flattened":
    case "reconciled":
      return "good";
    case "execution_plan_created":
    case "order_submission_pending":
    case "order_submitted":
    case "order_acknowledged":
    case "partially_filled":
    case "signal_detected":
      return "warn";
    case "cancelled":
    case "rejected":
      return "danger";
    default:
      return "neutral";
  }
}

export function riskCheckBadgeStatus(value: string | null | undefined): "good" | "warn" | "danger" | "neutral" {
  switch (String(value ?? "").trim().toLowerCase()) {
    case "allow":
    case "allowed":
      return "good";
    case "watch":
      return "warn";
    case "blocked":
      return "danger";
    default:
      return "neutral";
  }
}

export function acceptanceVerdictBadgeStatus(value: string | null | undefined): "good" | "warn" | "danger" | "neutral" {
  switch (value) {
    case "ready_for_stage_7_decision":
      return "good";
    case "support_acceptance_status":
      return "warn";
    case "challenge_acceptance_status":
      return "danger";
    default:
      return "neutral";
  }
}

export function stage7StatusBadgeStatus(value: string | null | undefined): "good" | "warn" | "danger" | "neutral" {
  switch (value) {
    case "ready_for_stage_7_decision":
      return "good";
    case "blocked_by_stage_6":
      return "warn";
    default:
      return "neutral";
  }
}

export function stage7VerdictBadgeStatus(value: string | null | undefined): "good" | "warn" | "danger" | "neutral" {
  switch (value) {
    case "queue_one_variable_review":
      return "good";
    case "keep_collecting_evidence":
    case "compare_next_concept":
      return "warn";
    case "reject_current_concept":
      return "danger";
    default:
      return "neutral";
  }
}

export function stageStatusBadgeStatus(value: string | null | undefined): "good" | "warn" | "danger" | "neutral" {
  switch (value) {
    case "ready_for_stage_7_decision":
      return "good";
    case "no_qualifying_evidence_recorded":
      return "danger";
    case "active_waiting_for_evidence":
      return "warn";
    case "stage_7_active":
      return "good";
    default:
      return "neutral";
  }
}

export function formatZoneTime(value: Date, timeZone: string) {
  return new Intl.DateTimeFormat(undefined, {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(value);
}

export function formatZoneTimeLabel(value: Date, timeZone: string) {
  return new Intl.DateTimeFormat(undefined, {
    timeZone,
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(value);
}

export function getZoneClockParts(value: Date, timeZone: string) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(value);

  const hour = Number(parts.find((part) => part.type === "hour")?.value ?? "0");
  const minute = Number(parts.find((part) => part.type === "minute")?.value ?? "0");

  return {
    hour,
    minute,
    totalMinutes: hour * 60 + minute,
  };
}

export function formatMinutesWindow(totalMinutes: number) {
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours <= 0) {
    return `${minutes}m`;
  }
  return `${hours}h ${minutes}m`;
}

export function buildSessionBoardState(
  now: Date,
  spec: SessionBoardSpec,
  allowedSessions: string[],
  activeSession: string,
): SessionBoardState {
  const { totalMinutes } = getZoneClockParts(now, spec.timeZone);
  const openMinutes = spec.openHour * 60;
  const closeMinutes = spec.closeHour * 60;
  const isOpen = totalMinutes >= openMinutes && totalMinutes < closeMinutes;
  const minutesUntilOpen =
    totalMinutes < openMinutes ? openMinutes - totalMinutes : 24 * 60 - totalMinutes + openMinutes;
  const minutesUntilClose = closeMinutes - totalMinutes;
  const openingSoon = !isOpen && minutesUntilOpen <= 60;

  return {
    id: spec.id,
    label: spec.label,
    timeZone: spec.timeZone,
    currentTime: formatZoneTime(now, spec.timeZone),
    timeLabel: formatZoneTimeLabel(now, spec.timeZone),
    windowLabel: `${String(spec.openHour).padStart(2, "0")}:00 - ${String(spec.closeHour).padStart(2, "0")}:00`,
    status: isOpen ? "open" : openingSoon ? "opening_soon" : "closed",
    detail: isOpen
      ? `closes in ${formatMinutesWindow(minutesUntilClose)}`
      : openingSoon
        ? `opens in ${formatMinutesWindow(minutesUntilOpen)}`
        : `next open in ${formatMinutesWindow(minutesUntilOpen)}`,
    allowed: isSessionAllowedInConfig(spec.id, allowedSessions),
    active: normalizeSessionKey(activeSession) === spec.id,
  };
}

export function structureProgressState(value: string | boolean | null | undefined) {
  if (typeof value === "boolean") {
    return value
      ? { score: 1, tone: "good" as const, detail: "confirmed" }
      : { score: 0.16, tone: "danger" as const, detail: "missing" };
  }

  const normalized = String(value ?? "none").trim().toLowerCase();
  if (!normalized || normalized === "none" || normalized === "no_scan" || normalized === "not_aligned") {
    return { score: 0.16, tone: "danger" as const, detail: "missing" };
  }
  if (
    normalized.includes("disrespect") ||
    normalized.includes("failing") ||
    normalized.includes("invalid")
  ) {
    return { score: 0.16, tone: "danger" as const, detail: cleanLabel(normalized) };
  }
  if (
    normalized.includes("confirmed") ||
    normalized.includes("valid") ||
    normalized.includes("active") ||
    normalized.includes("bull") ||
    normalized.includes("bear") ||
    normalized.includes("detected") ||
    normalized.includes("ready") ||
    normalized.includes("respect")
  ) {
    return { score: 1, tone: "good" as const, detail: cleanLabel(normalized) };
  }
  if (
    normalized.includes("partial") ||
    normalized.includes("candidate") ||
    normalized.includes("watch") ||
    normalized.includes("collect") ||
    normalized.includes("outside")
  ) {
    return { score: 0.58, tone: "warn" as const, detail: cleanLabel(normalized) };
  }
  return { score: 0.78, tone: "neutral" as const, detail: cleanLabel(normalized) };
}

export function badgeClasses(status: "good" | "warn" | "danger" | "neutral") {
  if (status === "good") {
    return "border-emerald-500/15 bg-emerald-500/10  text-emerald-300";
  }
  if (status === "warn") {
    return "border-amber-500/15 bg-amber-500/10 text-amber-300";
  }
  if (status === "danger") {
    return "border-rose-500/15 bg-rose-500/10  text-rose-300";
  }
  return "border-cyan-500/15 bg-cyan-500/10  text-cyan-200";
}

export function timelineAccentClasses(severity: string) {
  if (severity === "error") {
    return "bg-rose-400";
  }
  if (severity === "warning") {
    return "bg-amber-300";
  }
  if (severity === "info") {
    return "bg-cyan-300";
  }
  return "bg-slate-500";
}

export function classifyTimelineItem(item: ControlRoomTimelineItem): EventConsoleFilter {
  if (item.kind === "scan_history" || item.kind === "scan" || item.source.includes("scan")) {
    return "scan";
  }
  if (item.kind === "proposal") {
    return "proposal";
  }
  if (item.kind === "execution_state" || item.kind === "execution_action") {
    return "execution";
  }
  if (item.source.includes("concept")) {
    return "concept";
  }
  if (item.source.includes("control")) {
    return "control";
  }
  return "ops";
}

export function groupTimelineItems(items: ControlRoomTimelineItem[]): GroupedTimelineItem[] {
  const grouped: GroupedTimelineItem[] = [];
  const seen = new Map<string, number>();

  for (const item of items) {
    const key = [
      item.source,
      item.kind,
      item.event_type,
      item.title,
      item.summary,
      item.symbol ?? "",
      item.proposal_id ?? "",
      item.meta ?? "",
    ].join("|");

    const existingIndex = seen.get(key);
    if (existingIndex !== undefined) {
      grouped[existingIndex] = {
        representative: grouped[existingIndex].representative,
        count: grouped[existingIndex].count + 1,
        members: [...grouped[existingIndex].members, item],
      };
      continue;
    }

    seen.set(key, grouped.length);
    grouped.push({
      representative: item,
      count: 1,
      members: [item],
    });
  }

  return grouped;
}

export function normalizeSignalText(value: string | null | undefined) {
  return (value ?? "").toLowerCase().replace(/[_\s]+/g, " ").trim();
}

export function structureFocusConfig(focus: StructureFocus | null) {
  if (focus === "sweep") {
    return {
      label: "4H Liquidity",
      aliases: [
        "liquidity",
        "liquidity event",
        "raid",
        "sweep",
        "buy side sweep",
        "sell side sweep",
        "dealing range",
        "drt",
      ],
      preferredFilters: ["scan", "concept", "ops"] as EventConsoleFilter[],
      reason: "structure focus",
    };
  }
  if (focus === "mss") {
    return {
      label: "15m MSS",
      aliases: ["mss", "market structure", "structure shift", "broken swing", "15m"],
      preferredFilters: ["scan", "concept", "ops"] as EventConsoleFilter[],
      reason: "structure focus",
    };
  }
  if (focus === "fvg") {
    return {
      label: "5m PD Array",
      aliases: ["fvg", "fair value gap", "pd array", "bisi", "sibi", "ifvg", "midpoint", "entry zone"],
      preferredFilters: ["scan", "proposal", "execution", "ops"] as EventConsoleFilter[],
      reason: "structure focus",
    };
  }
  if (focus === "displacement") {
    return {
      label: "Displacement",
      aliases: ["displacement", "impulse", "expansion"],
      preferredFilters: ["scan", "concept", "ops"] as EventConsoleFilter[],
      reason: "structure focus",
    };
  }
  if (focus === "levels") {
    return {
      label: "Execution Plan",
      aliases: ["entry", "stop", "target", "working", "submitted", "cancel", "sync", "plan", "execution"],
      preferredFilters: ["proposal", "execution", "control", "ops", "scan"] as EventConsoleFilter[],
      reason: "execution plan",
    };
  }
  return null;
}

export function shouldIgnoreShortcutTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) {
    return false;
  }

  const tagName = target.tagName.toLowerCase();
  if (target.isContentEditable || target.closest("[contenteditable='true']")) {
    return true;
  }

  return tagName === "input" || tagName === "textarea" || tagName === "select";
}

export function inferStructureFocusFromEvent(item: ControlRoomTimelineItem | null): StructureFocus | null {
  if (!item) {
    return null;
  }

  const haystack = normalizeSignalText(
    [
      item.title,
      item.summary,
      item.source,
      item.kind,
      item.meta,
      item.event_type,
      item.symbol,
      item.proposal_id,
    ]
      .filter(Boolean)
      .join(" "),
  );

  if (
    haystack.includes("fair value gap") ||
    haystack.includes("fvg") ||
    haystack.includes("pd array") ||
    haystack.includes("bisi") ||
    haystack.includes("sibi") ||
    haystack.includes("ifvg")
  ) {
    return "fvg";
  }
  if (haystack.includes("market structure") || haystack.includes("structure shift") || haystack.includes("mss")) {
    return "mss";
  }
  if (haystack.includes("displacement") || haystack.includes("impulse") || haystack.includes("expansion")) {
    return "displacement";
  }
  if (
    haystack.includes("drt") ||
    haystack.includes("dealing range") ||
    haystack.includes("liquidity event") ||
    haystack.includes("raid_bsl") ||
    haystack.includes("raid_ssl") ||
    haystack.includes("close_through") ||
    haystack.includes("liquidity sweep") ||
    haystack.includes("buy side sweep") ||
    haystack.includes("sell side sweep") ||
    haystack.includes("sweep")
  ) {
    return "sweep";
  }
  if (
    item.kind === "proposal" ||
    item.kind === "execution_state" ||
    item.kind === "execution_action" ||
    haystack.includes("entry") ||
    haystack.includes("stop") ||
    haystack.includes("target") ||
    haystack.includes("submitted") ||
    haystack.includes("working") ||
    haystack.includes("cancel")
  ) {
    return "levels";
  }

  return null;
}

export function filterStructureFocusedTimelineItems(
  items: ScoredGroupedTimelineItem[],
  focus: StructureFocus | null,
  selectedSymbol: string,
) {
  const config = structureFocusConfig(focus);
  if (!config) {
    return items;
  }

  const filtered = items.filter((item) => {
    const symbolMatch =
      item.representative.symbol === selectedSymbol ||
      item.members.some((member) => member.symbol === selectedSymbol);
    const filterMatch = config.preferredFilters.includes(classifyTimelineItem(item.representative));
    const structureBreakdownMatch = item.relevanceBreakdown.some((entry) =>
      ["Matches structure focus", "Structure workflow match", "Derived plan lifecycle"].includes(entry.label),
    );
    const haystack = normalizeSignalText(
      item.members
        .flatMap((member) => [
          member.title,
          member.summary,
          member.source,
          member.kind,
          member.meta,
          member.event_type,
          member.symbol,
          member.proposal_id,
        ])
        .filter(Boolean)
        .join(" "),
    );
    const aliasMatch = config.aliases.some((alias) => haystack.includes(alias));

    return structureBreakdownMatch || aliasMatch || (symbolMatch && filterMatch) || item.relevanceScore >= 58;
  });

  return filtered.length > 0 ? filtered : items;
}

export function scoreGroupedTimelineItems(
  items: GroupedTimelineItem[],
  context: {
    selectedSymbol: string;
    currentProposalId: string | null;
    activeExecutionProposalId: string | null;
    currentTradeState: string;
    conceptRecommendation: string;
    dominantBlocker: string;
    operatorSignal: string;
    structureFocus: StructureFocus | null;
  },
): ScoredGroupedTimelineItem[] {
  return items
    .map((group) => {
      const item = group.representative;
      const reasons: string[] = [];
      const breakdown: Array<{ label: string; points: number }> = [];
      let score = 0;
      const addScore = (points: number, label: string, reason?: string) => {
        score += points;
        breakdown.push({ label, points });
        if (reason) {
          reasons.push(reason);
        }
      };
      const haystack = normalizeSignalText(
        [
          item.title,
          item.summary,
          item.source,
          item.kind,
          item.meta,
          item.event_type,
          item.symbol,
          item.proposal_id,
        ]
          .filter(Boolean)
          .join(" "),
      );

      if (item.symbol === context.selectedSymbol) {
        addScore(40, "Selected symbol match", "selected symbol");
      }

      if (context.currentProposalId && item.proposal_id === context.currentProposalId) {
        addScore(34, "Active proposal match", "active proposal");
      }

      if (
        context.activeExecutionProposalId &&
        item.proposal_id === context.activeExecutionProposalId &&
        item.proposal_id !== context.currentProposalId
      ) {
        addScore(30, "Live execution match", "live execution");
      }

      if (item.kind === "execution_state" || item.kind === "execution_action") {
        addScore(context.currentTradeState === "flat" ? 10 : 18, "Execution lifecycle", "execution lifecycle");
      } else if (item.kind === "proposal") {
        addScore(context.currentProposalId ? 16 : 10, "Proposal desk", "proposal desk");
      } else if (item.kind === "scan_history" || item.kind === "scan") {
        addScore(context.currentTradeState === "flat" ? 14 : 8, "Scan context", "scan context");
      } else if (item.source.includes("concept")) {
        addScore(14, "Concept runtime", "concept runtime");
      }

      if (item.severity === "error") {
        addScore(14, "Error severity", "error severity");
      } else if (item.severity === "warning") {
        addScore(10, "Warning severity", "warning severity");
      } else {
        addScore(4, "Info severity");
      }

      if (group.count > 1) {
        addScore(Math.min(12, group.count * 2), "Repeated daemon signal", "repeated daemon signal");
      }

      const normalizedBlocker = normalizeSignalText(context.dominantBlocker);
      if (normalizedBlocker && normalizedBlocker !== "n/a" && haystack.includes(normalizedBlocker)) {
        addScore(20, "Matches dominant blocker", "matches blocker");
      }

      const normalizedOperatorSignal = normalizeSignalText(context.operatorSignal);
      if (normalizedOperatorSignal && normalizedOperatorSignal !== "awaiting updates" && haystack.includes(normalizedOperatorSignal)) {
        addScore(12, "Matches operator signal", "matches operator signal");
      }

      const normalizedVerdict = normalizeSignalText(context.conceptRecommendation);
      if (normalizedVerdict && haystack.includes(normalizedVerdict)) {
        addScore(10, "Matches concept verdict", "matches concept verdict");
      }

      const structureConfig = structureFocusConfig(context.structureFocus);
      if (structureConfig) {
        const structureAliasMatch = structureConfig.aliases.some((alias) => haystack.includes(alias));
        const structureFilter = classifyTimelineItem(item);
        if (structureAliasMatch) {
          addScore(24, "Matches structure focus", structureConfig.reason);
        }
        if (item.symbol === context.selectedSymbol && structureConfig.preferredFilters.includes(structureFilter)) {
          addScore(18, "Structure workflow match", structureConfig.reason);
        }
        if (
          context.structureFocus === "levels" &&
          (item.proposal_id ||
            structureFilter === "proposal" ||
            structureFilter === "execution" ||
            item.source.includes("auto_execution"))
        ) {
          addScore(16, "Derived plan lifecycle", "execution plan");
        }
      }

      const relevanceLabel: ScoredGroupedTimelineItem["relevanceLabel"] =
        score >= 60 ? "high" : score >= 35 ? "medium" : "watch";

      return {
        ...group,
        relevanceScore: score,
        relevanceLabel,
        relevanceReasons: reasons.slice(0, 3),
        relevanceBreakdown: breakdown,
      };
    })
    .sort((left, right) => {
      if (right.relevanceScore !== left.relevanceScore) {
        return right.relevanceScore - left.relevanceScore;
      }
      return new Date(right.representative.created_at).getTime() - new Date(left.representative.created_at).getTime();
    });
}

export function severityChipClasses(severity: EventConsoleSeverityFilter, active: boolean) {
  if (active) {
    if (severity === "error") {
      return "border-rose-400/30 bg-rose-500/15 text-rose-200";
    }
    if (severity === "warning") {
      return "border-amber-400/30 bg-amber-500/15 text-amber-100";
    }
    if (severity === "info") {
      return "border-cyan-400/30 bg-cyan-500/15 text-cyan-200";
    }
    return "border-emerald-400/30 bg-emerald-500/15 text-emerald-200";
  }

  return "border-slate-700 bg-[#09111a] text-slate-400 hover:border-slate-600 hover:text-slate-200";
}

export function verdictBadgeStatus(value: string | null | undefined): "good" | "warn" | "danger" | "neutral" {
  if (value === "promising" || value === "continue_testing" || value === "live") {
    return "good";
  }
  if (value === "collecting" || value === "testing" || value === "watch") {
    return "warn";
  }
  if (value === "blocked" || value === "fix_harness") {
    return "danger";
  }
  return "neutral";
}

export function streamBadgeState(streamState: StreamState): { label: string; status: "good" | "warn" | "danger" } {
  if (streamState === "live") {
    return { label: "Stream Live", status: "good" };
  }
  if (streamState === "connecting") {
    return { label: "Stream Sync", status: "warn" };
  }
  return { label: "Stream Delayed", status: "danger" };
}

export function TerminalBadge({
  label,
  status = "neutral",
  icon: Icon,
}: {
  label: string;
  status?: "good" | "warn" | "danger" | "neutral";
  icon?: LucideIcon;
}) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-1 text-[8px] font-semibold uppercase tracking-[0.16em] ${badgeClasses(status)}`}>
      {Icon ? (
        <Icon className="h-3 w-3 opacity-80" strokeWidth={2} />
      ) : (
        <span className={`inline-block h-1.5 w-1.5 rounded-full ${status === "good" ? "terminal-live-dot bg-emerald-300" : status === "warn" ? "bg-amber-300" : status === "danger" ? "bg-rose-300" : "bg-cyan-300"}`} />
      )}
      {label}
    </span>
  );
}

export function ClockTile({
  label,
  value,
  meta,
}: {
  label: string;
  value: string;
  meta: string;
}) {
  return (
    <div className="terminal-subpanel px-4 py-3">
      <p className="terminal-kicker">{label}</p>
      <p className="mt-2 font-mono text-[22px] text-slate-100">{value}</p>
      <p className="mt-2 text-[11px] uppercase tracking-[0.16em] text-slate-500">{meta}</p>
    </div>
  );
}

export function SessionWindowCard({
  session,
}: {
  session: SessionBoardState;
}) {
  const status =
    session.status === "open" ? "good" : session.status === "opening_soon" ? "warn" : "neutral";

  return (
    <div
      className={`rounded-2xl border px-4 py-4 ${
        session.active
          ? "border-cyan-400/30 bg-cyan-400/10"
          : session.allowed
            ? "border-emerald-400/15 bg-emerald-500/5"
            : "border-slate-800 bg-[#071019]"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-mono text-[13px] text-slate-100">{session.label}</p>
          <p className="mt-2 font-mono text-lg text-slate-50">{session.currentTime}</p>
          <p className="mt-1 text-[11px] uppercase tracking-[0.16em] text-slate-500">{session.timeLabel}</p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <TerminalBadge
            label={
              session.status === "open"
                ? "open"
                : session.status === "opening_soon"
                  ? "opening soon"
                  : "closed"
            }
            status={status}
          />
          {session.active ? <TerminalBadge label="active" status="good" /> : null}
          {session.allowed ? <TerminalBadge label="concept allowed" status="warn" /> : null}
        </div>
      </div>
      <div className="mt-3 border-t border-slate-800 pt-3">
        <div className="flex items-center justify-between gap-3 text-[11px]">
          <span className="text-slate-500">window</span>
          <span className="font-mono text-slate-200">{session.windowLabel}</span>
        </div>
        <div className="mt-2 flex items-center justify-between gap-3 text-[11px]">
          <span className="text-slate-500">status</span>
          <span className="font-mono text-slate-200">{session.detail}</span>
        </div>
      </div>
    </div>
  );
}

export function ActionButton({
  label,
  tone = "neutral",
  disabled = false,
  busy = false,
  onClick,
}: {
  label: string;
  tone?: "neutral" | "good" | "warn" | "danger";
  disabled?: boolean;
  busy?: boolean;
  onClick: () => void;
}) {
  const toneClasses =
    tone === "good"
      ? "border-emerald-500/25 bg-emerald-500/15 text-emerald-200 hover:border-emerald-400/40"
      : tone === "warn"
        ? "border-amber-500/25 bg-amber-500/15 text-amber-100 hover:border-amber-400/40"
        : tone === "danger"
          ? "border-rose-500/25 bg-rose-500/15 text-rose-100 hover:border-rose-400/40"
          : "border-slate-700 bg-[#09111a] text-slate-200 hover:border-slate-600";

  return (
    <button
      type="button"
      disabled={disabled || busy}
      onClick={onClick}
      className={`rounded-xl border px-3 py-2 text-left font-mono text-[10px] uppercase tracking-[0.14em] transition ${toneClasses} ${
        disabled || busy ? "cursor-not-allowed opacity-55" : ""
      }`}
    >
      {busy ? "Working..." : label}
    </button>
  );
}

export function PanelHeader({ title, meta, icon }: { title: string; meta?: string; icon?: ReactNode }) {
  return (
    <div className="mb-2.5 flex items-center justify-between gap-3">
      <h2 className="terminal-heading flex items-center gap-2">
        {icon ? (
          <span className="flex h-4 w-4 items-center justify-center text-cyan-300">{icon}</span>
        ) : (
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-cyan-300" />
        )}
        {title}
      </h2>
      {meta ? <span className="terminal-kicker text-right">{meta}</span> : null}
    </div>
  );
}

export function ProgressMeter({
  label,
  detail,
  value,
  tone = "neutral",
}: {
  label: string;
  detail: string;
  value: number;
  tone?: "neutral" | "good" | "warn" | "danger";
}) {
  const safeValue = Math.max(0, Math.min(1, value));
  const barClass =
    tone === "good"
      ? "bg-emerald-400"
      : tone === "warn"
        ? "bg-amber-300"
        : tone === "danger"
          ? "bg-rose-400"
          : "bg-cyan-300";

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[11px] uppercase tracking-[0.14em] text-slate-500">{label}</span>
        <span className="font-mono text-[11px] text-slate-300">{detail}</span>
      </div>
      <div className="h-1.5 rounded-full bg-slate-900">
        <div className={`h-1.5 rounded-full ${barClass}`} style={{ width: `${safeValue * 100}%` }} />
      </div>
    </div>
  );
}

export function FooterStripItem({
  label,
  value,
  tone = "text-slate-300",
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</span>
      <span className={`font-mono text-[12px] ${tone}`}>{value}</span>
    </div>
  );
}

export function ShortcutHint({
  keys,
  label,
  active = true,
}: {
  keys: string;
  label: string;
  active?: boolean;
}) {
  return (
    <div
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] ${
        active
          ? "border-slate-700 bg-[#09111a] text-slate-300"
          : "border-slate-800 bg-[#060c14] text-slate-600"
      }`}
    >
      <span className="rounded border border-slate-700 bg-slate-950/80 px-2 py-1 font-mono text-[10px] text-slate-100">
        {keys}
      </span>
      <span>{label}</span>
    </div>
  );
}

export function WorkspaceTabButton({
  label,
  meta,
  active,
  icon,
  onClick,
}: {
  label: string;
  meta: string;
  active: boolean;
  icon?: ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={meta}
      className={`rounded-xl border px-2.5 py-1.5 text-left transition ${
        active
          ? "border-cyan-400/20 bg-cyan-400/10"
          : "border-slate-800 bg-[#071019] hover:border-slate-700 hover:bg-[#09131d]"
      }`}
    >
      <div className="flex items-center gap-1.5">
        {icon ? <span className="text-slate-400">{icon}</span> : null}
        <p className="font-mono text-[10px] text-slate-100">{label}</p>
      </div>
    </button>
  );
}

export function OperatorSceneCard({
  scene,
}: {
  scene: OperatorScene;
}) {
  return (
    <button
      type="button"
      disabled={scene.disabled}
      onClick={scene.run}
      className={`rounded-2xl border px-4 py-4 text-left transition ${
        scene.active
          ? "border-cyan-400/35 bg-cyan-400/10"
          : scene.disabled
            ? "border-slate-800 bg-[#060c14] text-slate-600"
            : "border-slate-800 bg-[#071019] hover:border-slate-700 hover:bg-[#09131d]"
      } ${scene.disabled ? "cursor-not-allowed opacity-70" : ""}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-mono text-[13px] text-slate-100">{scene.title}</p>
            {scene.active ? (
              <span className="rounded-full border border-cyan-400/20 bg-cyan-400/10 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.16em] text-cyan-200">
                active
              </span>
            ) : null}
          </div>
          <p className="mt-2 text-[12px] text-slate-400">{scene.description}</p>
        </div>
        <span className="terminal-kicker">{scene.meta}</span>
      </div>
    </button>
  );
}

export function loadSavedOperatorScenes() {
  if (typeof window === "undefined") {
    return [] as SavedOperatorScene[];
  }

  try {
    const raw = window.localStorage.getItem(SAVED_OPERATOR_SCENES_STORAGE_KEY);
    if (!raw) {
      return [];
    }

    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }

    return normalizeSavedOperatorScenes(
      parsed.filter((item) => item && typeof item === "object" && "id" in item && "state" in item) as SavedOperatorScene[],
    );
  } catch {
    return [];
  }
}

export function normalizeSavedOperatorScenes(scenes: SavedOperatorScene[]) {
  let defaultAssigned = false;

  return scenes.slice(0, 8).map((scene) => {
    const nextDefault = Boolean(scene.isDefault) && !defaultAssigned;
    if (nextDefault) {
      defaultAssigned = true;
    }

    return {
      ...scene,
      state: {
        ...scene.state,
        workspaceTab: scene.state.workspaceTab ?? "console",
      },
      isDefault: nextDefault,
    };
  });
}

export function CommandPalette({
  open,
  query,
  onQueryChange,
  onClose,
  actions,
  selectedIndex,
  onSelectIndex,
  onRunAction,
}: {
  open: boolean;
  query: string;
  onQueryChange: (value: string) => void;
  onClose: () => void;
  actions: CommandPaletteAction[];
  selectedIndex: number;
  onSelectIndex: (index: number) => void;
  onRunAction: (action: CommandPaletteAction) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!open) {
      return undefined;
    }

    const timer = window.setTimeout(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    }, 10);

    return () => window.clearTimeout(timer);
  }, [open]);

  if (!open) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-[70] flex items-start justify-center bg-[#04070cbf] px-4 pt-20"
      role="presentation"
      onClick={onClose}
    >
      <div
        className="w-full max-w-[760px] rounded-[20px] border border-slate-800 bg-[#081018]"
        role="dialog"
        aria-modal="true"
        aria-label="Operator command palette"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="border-b border-slate-800 px-5 py-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="terminal-kicker">Operator Command Palette</p>
              <p className="mt-2 text-sm text-slate-400">
                Search actions, jump markets, focus structure, or move faster through investigation flow.
              </p>
            </div>
            <ShortcutHint keys="Esc" label="Close" />
          </div>
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="Search actions, symbols, structure focus, or investigation moves..."
            className="mt-4 w-full rounded-2xl border border-slate-700 bg-[#09111a] px-4 py-3 font-mono text-[13px] text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-cyan-400/40"
          />
        </div>

        <div className="max-h-[56vh] overflow-auto px-4 py-4">
          {actions.length > 0 ? (
            <div className="space-y-2">
              {actions.map((action, index) => (
                <button
                  key={action.id}
                  type="button"
                  onMouseEnter={() => onSelectIndex(index)}
                  onClick={() => onRunAction(action)}
                  className={`w-full rounded-2xl border px-4 py-3 text-left transition ${
                    index === selectedIndex
                      ? "border-cyan-400/30 bg-cyan-400/10"
                      : "border-slate-800 bg-[#071019] hover:border-slate-700 hover:bg-[#09131d]"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="terminal-kicker">{action.group}</span>
                        {action.meta ? (
                          <span className="text-[10px] uppercase tracking-[0.16em] text-cyan-300">{action.meta}</span>
                        ) : null}
                      </div>
                      <p className="mt-2 font-mono text-[13px] text-slate-100">{action.title}</p>
                    </div>
                    <span className="rounded-full border border-slate-700 bg-slate-950/80 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-300">
                      {index + 1}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <div className="rounded-2xl border border-slate-800 bg-[#071019] px-4 py-6 text-sm text-slate-500">
              No commands match this search yet.
            </div>
          )}
        </div>

        <div className="border-t border-slate-800 px-5 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <ShortcutHint keys="↑ / ↓" label="Move" />
            <ShortcutHint keys="Enter" label="Run" />
            <ShortcutHint keys="⌘K" label="Toggle" />
          </div>
        </div>
      </div>
    </div>
  );
}

export function AnalysisRow({ label, value, tone = "text-cyan-300" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="grid grid-cols-[108px_1fr] gap-3 border-b border-slate-800/90 py-2.5 text-sm last:border-b-0">
      <span className="terminal-kicker">{label}</span>
      <span className={`font-mono text-[10px] ${tone}`}>{value}</span>
    </div>
  );
}

export function RevisionLeaderSummary({
  compareSummary,
  activity,
  compact = false,
}: {
  compareSummary: ConceptRevisionCompareSummary | null;
  activity?: Record<string, unknown> | null;
  compact?: boolean;
}) {
  const leader = compareSummary?.best_ranked_revision ?? null;
  const fallbackRevision = compareSummary?.best_revision ?? compareSummary?.latest_revision ?? null;
  const rankedFollowers = compareSummary?.ranked_revisions.slice(1, 3) ?? [];
  const latestCompare = compareSummary?.latest_compare_artifact ?? null;
  const stabilityCycles = Number((activity ?? {}).stability_cycles ?? 0);
  const lastChangedAt =
    typeof (activity ?? {}).last_changed_at === "string" ? String((activity ?? {}).last_changed_at) : null;
  const stage5Readiness = compareSummary?.stage5_readiness ?? null;
  const focusLabel = cleanLabel(leader?.focus ?? fallbackRevision?.focus ?? "no_revision_focus");
  const statusLabel = cleanLabel(leader?.status ?? fallbackRevision?.status ?? "awaiting_review");
  const primaryReason =
    compareSummary?.leader_explanation ??
    latestCompare?.comparison_summary ??
    leader?.reasons[0] ??
    compareSummary?.takeaway ??
    "No ranked revision leader is available yet.";
  const compareAction =
    compareSummary?.compare_action ??
    latestCompare?.next_action_summary ??
    compareSummary?.next_action ??
    "Keep collecting evaluation history until a revision separates itself.";

  if (compact) {
    return (
      <div className="mt-4 terminal-subpanel p-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="terminal-kicker">Revision Leader</p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <span className="font-mono text-[13px] text-slate-100">
                {leader?.revision_id ?? fallbackRevision?.revision_id ?? "awaiting revision"}
              </span>
              {leader ? (
                <TerminalBadge label={`score ${leader.score}`} status={revisionStatusBadgeStatus(leader.status)} />
              ) : null}
              <TerminalBadge
                label={statusLabel}
                status={revisionStatusBadgeStatus(leader?.status ?? fallbackRevision?.status)}
              />
              {latestCompare?.verdict ? (
                <TerminalBadge
                  label={cleanLabel(latestCompare.verdict)}
                  status={revisionCompareVerdictBadgeStatus(latestCompare.verdict)}
                />
              ) : null}
            </div>
          </div>
          <span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
            {leader?.history_count ? `${leader.history_count} checks` : "compare ready"}
          </span>
        </div>

        <div className="mt-3 grid gap-2 text-[11px] sm:grid-cols-2">
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-500">focus</span>
            <span className="font-mono text-slate-200">{focusLabel}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-500">sample</span>
            <span className="font-mono text-slate-200">
              {compareSummary?.latest_sample_started_at
                ? formatRelativeTime(compareSummary.latest_sample_started_at)
                : "awaiting sample"}
            </span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-500">artifacts</span>
            <span className="font-mono text-slate-200">{compareSummary?.compare_artifact_count ?? 0}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-500">stability</span>
            <span className="font-mono text-slate-200">
              {stabilityCycles > 0 ? `${stabilityCycles} cycles` : "new guidance"}
            </span>
          </div>
        </div>

        <p className="mt-3 text-[12px] text-slate-300">{primaryReason}</p>
        <p className="mt-2 text-[11px] text-slate-500">{compareAction}</p>
        {stage5Readiness ? (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <TerminalBadge
              label={`stage 5 ${cleanLabel(stage5Readiness.status)}`}
              status={stageGateBadgeStatus(stage5Readiness.status)}
            />
            <TerminalBadge
              label={`gate ${stage5Readiness.score}`}
              status={stageGateBadgeStatus(stage5Readiness.status)}
            />
          </div>
        ) : null}
        {lastChangedAt || latestCompare?.review_id ? (
          <p className="mt-2 text-[10px] uppercase tracking-[0.16em] text-slate-600">
            {lastChangedAt ? `changed ${formatRelativeTime(lastChangedAt)}` : "latest compare ready"}
            {latestCompare?.review_id ? ` · ${latestCompare.review_id}` : ""}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <section className="terminal-panel p-4">
      <PanelHeader
        title="Revision Leader"
        icon={<GitBranch size={14} strokeWidth={1.8} />}
        meta={
          leader?.history_count
            ? `${leader.history_count} fresh-sample checks`
            : compareSummary?.evaluation_history_count
              ? `${compareSummary.evaluation_history_count} total checks`
              : "awaiting revision checks"
        }
      />
      <div className="terminal-subpanel p-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="terminal-kicker">Current leader</p>
            <p className="mt-2 font-mono text-[15px] text-slate-100">
              {leader?.revision_id ?? fallbackRevision?.revision_id ?? "No ranked revision yet"}
            </p>
            <p className="mt-1 text-[12px] text-slate-400">
              {compareSummary?.takeaway ?? "Revision compare summary not available yet."}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {leader ? (
              <TerminalBadge label={`score ${leader.score}`} status={revisionStatusBadgeStatus(leader.status)} />
            ) : null}
            <TerminalBadge
              label={statusLabel}
              status={revisionStatusBadgeStatus(leader?.status ?? fallbackRevision?.status)}
            />
            <TerminalBadge label={focusLabel} status="neutral" />
            {latestCompare?.verdict ? (
              <TerminalBadge
                label={cleanLabel(latestCompare.verdict)}
                status={revisionCompareVerdictBadgeStatus(latestCompare.verdict)}
              />
            ) : null}
          </div>
        </div>

        <div className="mt-3 grid gap-2 text-[11px] md:grid-cols-3">
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-500">reviews</span>
            <span className="font-mono text-slate-200">{compareSummary?.review_count ?? 0}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-500">revisions</span>
            <span className="font-mono text-slate-200">{compareSummary?.revision_count ?? 0}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-500">latest sample</span>
            <span className="font-mono text-slate-200">
              {compareSummary?.latest_sample_started_at
                ? formatTimestamp(compareSummary.latest_sample_started_at)
                : "awaiting sample"}
            </span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-500">compare artifacts</span>
            <span className="font-mono text-slate-200">{compareSummary?.compare_artifact_count ?? 0}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-500">stability</span>
            <span className="font-mono text-slate-200">
              {stabilityCycles > 0 ? `${stabilityCycles} cycles` : "new guidance"}
            </span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-500">last changed</span>
            <span className="font-mono text-slate-200">
              {lastChangedAt ? formatRelativeTime(lastChangedAt) : "-"}
            </span>
          </div>
        </div>

        <p className="mt-3 text-sm text-slate-300">{primaryReason}</p>
        <div className="mt-3 rounded-xl border border-slate-800 bg-[#09111a] px-3 py-2 text-[11px] text-slate-400">
          <span className="text-slate-500">Next action</span>
          <p className="mt-1 text-slate-300">{compareAction}</p>
        </div>
        {latestCompare ? (
          <div className="mt-3 rounded-xl border border-slate-800 bg-[#09111a] px-3 py-2 text-[11px] text-slate-400">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span className="text-slate-500">Latest compare</span>
              <span className="font-mono text-slate-300">
                {latestCompare.review_id}
                {latestCompare.created_at ? ` · ${formatRelativeTime(latestCompare.created_at)}` : ""}
              </span>
            </div>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              <div className="flex items-center justify-between gap-3">
                <span className="text-slate-500">focus</span>
                <span className="font-mono text-slate-200">
                  {cleanLabel(latestCompare.next_action_focus ?? "n/a")}
                </span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-slate-500">confidence</span>
                <span className="font-mono text-slate-200">
                  {cleanLabel(latestCompare.confidence ?? "unknown")}
                </span>
              </div>
            </div>
          </div>
        ) : null}
      </div>

      {rankedFollowers.length > 0 ? (
        <div className="mt-3 space-y-2">
          {rankedFollowers.map((item) => (
            <div key={item.revision_id} className="terminal-subpanel px-3 py-2">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-mono text-[12px] text-slate-100">
                    {item.revision_id} · {cleanLabel(item.focus ?? "no_focus")}
                  </p>
                  <p className="mt-1 text-[11px] text-slate-500">{item.reasons[0] ?? item.summary}</p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <TerminalBadge label={`score ${item.score}`} status={revisionStatusBadgeStatus(item.status)} />
                  <TerminalBadge
                    label={cleanLabel(item.status ?? "planned")}
                    status={revisionStatusBadgeStatus(item.status)}
                  />
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

export function AcceptanceStatusSummary({
  acceptanceSummary,
  acceptanceHistory = [],
  compact = false,
}: {
  acceptanceSummary: ConceptAcceptanceSummary | null;
  acceptanceHistory?: ConceptAcceptanceHistoryItem[];
  compact?: boolean;
}) {
  const gate = acceptanceSummary?.acceptance_gate ?? null;
  const latest = acceptanceSummary?.latest_acceptance_artifact ?? null;
  const evidenceProgress = acceptanceSummary?.evidence_progress ?? null;
  const statusLabel = cleanLabel(acceptanceSummary?.latest_acceptance_status ?? gate?.status ?? "awaiting_acceptance");
  const verdictLabel = latest?.verdict ? cleanLabel(latest.verdict) : null;
  const explanation =
    acceptanceSummary?.acceptance_explanation ??
    acceptanceSummary?.takeaway ??
    gate?.summary ??
    "No Stage 6 acceptance guidance is saved yet.";
  const action = acceptanceSummary?.acceptance_action ?? gate?.next_action ?? "Keep collecting evidence.";
  const blocker = cleanLabel(acceptanceSummary?.primary_blocker ?? "evidence_thresholds");
  const stalledCycles = Number(acceptanceSummary?.stalled_cycles ?? 0);
  const recentHistory = acceptanceHistory.slice(0, 3);
  const progressTone =
    acceptanceSummary?.ready_for_stage_7
      ? "good"
      : stalledCycles >= 3
        ? "warn"
        : "neutral";
  const thresholdBreakdown = evidenceProgress?.thresholds?.length
    ? evidenceProgress.thresholds
        .map((item) => `${item.label.slice(0, 4)} ${item.actual}/${item.required}`)
        .join(" · ")
    : null;

  if (compact) {
    return (
      <div className="terminal-subpanel p-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="terminal-kicker">Stage 6 Acceptance</p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <TerminalBadge label={statusLabel} status={acceptanceStatusBadgeStatus(acceptanceSummary?.latest_acceptance_status ?? gate?.status)} />
              {verdictLabel ? (
                <TerminalBadge label={verdictLabel} status={acceptanceVerdictBadgeStatus(latest?.verdict)} />
              ) : null}
              <TerminalBadge
                label={acceptanceSummary?.ready_for_stage_7 ? "Stage 7 Ready" : "Stage 7 Hold"}
                status={acceptanceSummary?.ready_for_stage_7 ? "good" : "warn"}
              />
            </div>
          </div>
          <span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
            {acceptanceSummary?.acceptance_artifact_count ? `${acceptanceSummary.acceptance_artifact_count} reviews` : "awaiting review"}
          </span>
        </div>

        <div className="mt-3 grid gap-2 text-[11px] sm:grid-cols-2">
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-500">blocker</span>
            <span className="font-mono text-amber-200">{blocker}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-500">stability</span>
            <span className="font-mono text-slate-200">
              {acceptanceSummary?.stability_cycles ? `${acceptanceSummary.stability_cycles} cycles` : "new guidance"}
            </span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-500">progress</span>
            <span className="font-mono text-slate-200">
              {evidenceProgress ? `${evidenceProgress.thresholds_met_count}/${evidenceProgress.thresholds_total_count}` : "n/a"}
            </span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-500">stall</span>
            <span className="font-mono text-slate-200">
              {stalledCycles > 0 ? `${stalledCycles} cycles` : "moving"}
            </span>
          </div>
        </div>

        {evidenceProgress ? (
          <div className="mt-3">
            <ProgressMeter
              label="threshold progress"
              detail={`${evidenceProgress.thresholds_met_count}/${evidenceProgress.thresholds_total_count}`}
              value={evidenceProgress.threshold_progress_ratio}
              tone={progressTone}
            />
            {thresholdBreakdown ? (
              <p className="mt-2 text-[10px] uppercase tracking-[0.14em] text-slate-600">{thresholdBreakdown}</p>
            ) : null}
          </div>
        ) : null}

        <p className="mt-3 text-[12px] text-slate-300">{explanation}</p>
        <p className="mt-2 text-[11px] text-slate-500">{action}</p>
        {acceptanceSummary?.last_changed_at || latest?.review_id ? (
          <p className="mt-2 text-[10px] uppercase tracking-[0.16em] text-slate-600">
            {acceptanceSummary?.last_changed_at ? `changed ${formatRelativeTime(acceptanceSummary.last_changed_at)}` : "latest acceptance ready"}
            {latest?.review_id ? ` · ${latest.review_id}` : ""}
            {acceptanceSummary?.last_progress_at ? ` · progress ${formatRelativeTime(acceptanceSummary.last_progress_at)}` : ""}
          </p>
        ) : null}
        {recentHistory.length > 0 ? (
          <div className="mt-3 space-y-2 border-t border-slate-800 pt-3">
            {recentHistory.map((item) => (
              <div key={item.entry_key} className="flex items-center justify-between gap-3 text-[10px] uppercase tracking-[0.14em] text-slate-500">
                <span className="truncate">{item.progress_summary ?? cleanLabel(item.latest_acceptance_status ?? "acceptance")}</span>
                <span className="font-mono text-slate-300">{formatRelativeTime(item.last_seen_at)}</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="mt-4 rounded-2xl border border-emerald-500/15 bg-emerald-500/5 px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="terminal-kicker">Stage 6 Acceptance</p>
          <p className="mt-2 text-sm text-slate-200">{explanation}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <TerminalBadge label={statusLabel} status={acceptanceStatusBadgeStatus(acceptanceSummary?.latest_acceptance_status ?? gate?.status)} />
          {verdictLabel ? (
            <TerminalBadge label={verdictLabel} status={acceptanceVerdictBadgeStatus(latest?.verdict)} />
          ) : null}
          <TerminalBadge
            label={acceptanceSummary?.ready_for_stage_7 ? "Stage 7 Ready" : "Stage 7 Hold"}
            status={acceptanceSummary?.ready_for_stage_7 ? "good" : "warn"}
          />
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-4 text-[11px] uppercase tracking-[0.14em] text-slate-500">
        <span>blocker {blocker}</span>
        <span>artifacts {acceptanceSummary?.acceptance_artifact_count ?? 0}</span>
        {acceptanceSummary?.stability_cycles ? <span>stable {acceptanceSummary.stability_cycles} cycles</span> : null}
        {evidenceProgress ? <span>progress {evidenceProgress.thresholds_met_count}/{evidenceProgress.thresholds_total_count}</span> : null}
        {stalledCycles > 0 ? <span>stalled {stalledCycles} cycles</span> : null}
        {latest?.created_at ? <span>review {formatRelativeTime(latest.created_at)}</span> : null}
        {acceptanceSummary?.last_progress_at ? <span>progress {formatRelativeTime(acceptanceSummary.last_progress_at)}</span> : null}
      </div>

      <p className="mt-3 text-sm text-slate-400">{action}</p>

      {evidenceProgress ? (
        <div className="mt-3 rounded-2xl border border-slate-800 bg-[#071019] px-4 py-3">
          <ProgressMeter
            label="threshold progress"
            detail={`${evidenceProgress.thresholds_met_count}/${evidenceProgress.thresholds_total_count}`}
            value={evidenceProgress.threshold_progress_ratio}
            tone={progressTone}
          />
          <div className="mt-3 flex flex-wrap items-center gap-4 text-[11px] uppercase tracking-[0.14em] text-slate-500">
            {thresholdBreakdown ? <span>{thresholdBreakdown}</span> : null}
            <span>candidate {formatPercent(evidenceProgress.candidate_ratio)}</span>
            {evidenceProgress.next_needed_label ? <span>next {cleanLabel(evidenceProgress.next_needed_label)}</span> : null}
          </div>
        </div>
      ) : null}

      {recentHistory.length > 0 ? (
        <div className="mt-3 space-y-2">
          <p className="terminal-kicker">Recent Milestones</p>
          {recentHistory.map((item) => (
            <div key={item.entry_key} className="terminal-subpanel px-3 py-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <p className="font-mono text-[12px] text-slate-100">
                    {item.progress_summary ?? cleanLabel(item.latest_acceptance_status ?? "acceptance")}
                  </p>
                  <p className="mt-1 text-[11px] text-slate-500">
                    {item.next_needed_label ? `next ${cleanLabel(item.next_needed_label)}` : cleanLabel(item.primary_blocker ?? "evidence_thresholds")}
                    {item.stalled_cycles > 0 ? ` · stalled ${item.stalled_cycles}` : ""}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <TerminalBadge label={`${item.thresholds_met_count}/${item.thresholds_total_count}`} status={item.ready_for_stage_7 ? "good" : "neutral"} />
                  <TerminalBadge label={cleanLabel(item.progress_direction ?? "flat")} status={item.progress_direction === "forward" ? "good" : item.progress_direction === "backward" ? "danger" : "warn"} />
                </div>
              </div>
              <p className="mt-2 text-[10px] uppercase tracking-[0.14em] text-slate-600">
                seen {item.cycles_seen} cycles · {formatRelativeTime(item.last_seen_at)}
              </p>
            </div>
          ))}
        </div>
      ) : null}

      {gate?.blockers?.length ? (
        <div className="mt-3 space-y-1 text-[11px] text-slate-500">
          {gate.blockers.slice(0, 3).map((item) => (
            <p key={item}>- {item}</p>
          ))}
        </div>
      ) : gate?.caveat ? (
        <p className="mt-3 text-[11px] text-slate-500">{gate.caveat}</p>
      ) : null}
    </div>
  );
}

export function Stage7DecisionSummary({
  stage7Summary,
  compact = false,
}: {
  stage7Summary: ConceptStage7DecisionSummary | null;
  compact?: boolean;
}) {
  const gate = stage7Summary?.stage7_gate ?? null;
  const latest = stage7Summary?.latest_stage7_artifact ?? null;
  const statusLabel = cleanLabel(gate?.status ?? latest?.stage7_readiness ?? "awaiting_stage7");
  const verdictLabel = latest?.verdict ? cleanLabel(latest.verdict) : null;
  const explanation =
    latest?.primary_reason ??
    stage7Summary?.decision_takeaway ??
    gate?.summary ??
    "No Stage 7 decision memo is saved yet.";
  const action =
    latest?.next_action_summary ??
    stage7Summary?.decision_action ??
    gate?.next_action ??
    "Keep Stage 7 blocked until Stage 6 proves out.";
  const pathLabel = cleanLabel(gate?.suggested_path ?? latest?.next_action_type ?? "hold");
  const reasonLabel = cleanLabel(latest?.next_action_focus ?? gate?.primary_reason ?? "evidence_thresholds");

  if (compact) {
    return (
      <div className="terminal-subpanel p-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="terminal-kicker">Stage 7 Memo</p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <TerminalBadge label={statusLabel} status={stage7StatusBadgeStatus(gate?.status ?? latest?.stage7_readiness)} />
              {verdictLabel ? (
                <TerminalBadge label={verdictLabel} status={stage7VerdictBadgeStatus(latest?.verdict)} />
              ) : null}
              <TerminalBadge
                label={gate?.ready_for_stage_7 ? "Decision Ready" : "Stage 6 Hold"}
                status={gate?.ready_for_stage_7 ? "good" : "warn"}
              />
            </div>
          </div>
          <span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
            {stage7Summary?.decision_artifact_count ? `${stage7Summary.decision_artifact_count} memos` : "awaiting memo"}
          </span>
        </div>

        <div className="mt-3 grid gap-2 text-[11px] sm:grid-cols-2">
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-500">path</span>
            <span className="font-mono text-slate-200">{pathLabel}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-500">reason</span>
            <span className="font-mono text-amber-200">{reasonLabel}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-500">stability</span>
            <span className="font-mono text-slate-200">
              {stage7Summary?.stability_cycles ? `${stage7Summary.stability_cycles} cycles` : "new guidance"}
            </span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-500">latest</span>
            <span className="font-mono text-slate-200">
              {latest?.created_at ? formatRelativeTime(latest.created_at) : "awaiting memo"}
            </span>
          </div>
        </div>

        <p className="mt-3 text-[12px] text-slate-300">{explanation}</p>
        <p className="mt-2 text-[11px] text-slate-500">{action}</p>
        {stage7Summary?.last_changed_at || latest?.review_id ? (
          <p className="mt-2 text-[10px] uppercase tracking-[0.16em] text-slate-600">
            {stage7Summary?.last_changed_at ? `changed ${formatRelativeTime(stage7Summary.last_changed_at)}` : "latest memo ready"}
            {latest?.review_id ? ` · ${latest.review_id}` : ""}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div className="mt-4 rounded-2xl border border-amber-500/15 bg-amber-500/5 px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="terminal-kicker">Stage 7 Memo</p>
          <p className="mt-2 text-sm text-slate-200">{explanation}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <TerminalBadge label={statusLabel} status={stage7StatusBadgeStatus(gate?.status ?? latest?.stage7_readiness)} />
          {verdictLabel ? (
            <TerminalBadge label={verdictLabel} status={stage7VerdictBadgeStatus(latest?.verdict)} />
          ) : null}
          <TerminalBadge
            label={gate?.ready_for_stage_7 ? "Decision Ready" : "Stage 6 Hold"}
            status={gate?.ready_for_stage_7 ? "good" : "warn"}
          />
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-4 text-[11px] uppercase tracking-[0.14em] text-slate-500">
        <span>path {pathLabel}</span>
        <span>reason {reasonLabel}</span>
        <span>memos {stage7Summary?.decision_artifact_count ?? 0}</span>
        {stage7Summary?.stability_cycles ? <span>stable {stage7Summary.stability_cycles} cycles</span> : null}
        {latest?.created_at ? <span>memo {formatRelativeTime(latest.created_at)}</span> : null}
      </div>

      <p className="mt-3 text-sm text-slate-400">{action}</p>

      {gate?.blockers?.length ? (
        <div className="mt-3 space-y-1 text-[11px] text-slate-500">
          {gate.blockers.slice(0, 3).map((item) => (
            <p key={item}>- {item}</p>
          ))}
        </div>
      ) : gate?.caveat ? (
        <p className="mt-3 text-[11px] text-slate-500">{gate.caveat}</p>
      ) : null}
    </div>
  );
}

export function StageStatusSummary({
  stageStatus,
  compact = false,
}: {
  stageStatus: ConceptStageStatusSummary | null;
  compact?: boolean;
}) {
  const currentStage = stageStatus?.current_stage ?? null;
  const nextStage = stageStatus?.next_stage ?? null;
  const statusLabel = cleanLabel(stageStatus?.status ?? "unknown");
  const summary = stageStatus?.summary ?? "Stage status is not available yet.";
  const focusLabel = cleanLabel(stageStatus?.current_focus ?? "collect_more_evidence");
  const diagnostics = stageStatus?.diagnostics ?? null;
  const operationalSignal = cleanLabel(diagnostics?.operational_signal ?? stageStatus?.current_focus ?? "unknown");
  const bottleneckLabel =
    diagnostics?.operational_signal === "no_qualifying_evidence_recorded"
      ? "No Evidence"
      : stageStatus?.evidence_is_primary_constraint
        ? "Evidence Bottleneck"
        : "Infra / Gate Bottleneck";
  const bottleneckStatus =
    diagnostics?.operational_signal === "no_qualifying_evidence_recorded"
      ? "danger"
      : stageStatus?.evidence_is_primary_constraint
        ? "warn"
        : "neutral";
  const counts = diagnostics?.evidence_counts ?? null;

  if (compact) {
    return (
      <div className="terminal-subpanel p-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="terminal-kicker">Stage Status</p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <TerminalBadge
                label={currentStage ? `Stage ${currentStage.number}` : "Stage ?"}
                status={stageStatus?.ready_for_next_stage ? "good" : "neutral"}
              />
              <TerminalBadge label={statusLabel} status={stageStatusBadgeStatus(stageStatus?.status)} />
              <TerminalBadge label={bottleneckLabel} status={bottleneckStatus} />
            </div>
          </div>
          <span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
            {nextStage ? `next stage ${nextStage.number}` : "final stage"}
          </span>
        </div>

        <div className="mt-3 grid gap-2 text-[11px] sm:grid-cols-2">
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-500">focus</span>
            <span className="font-mono text-slate-200">{operationalSignal}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-500">leader</span>
            <span className="font-mono text-slate-200">
              {stageStatus?.metrics.leader_revision_id ?? "none"}{stageStatus?.metrics.leader_status ? ` · ${cleanLabel(stageStatus.metrics.leader_status)}` : ""}
            </span>
          </div>
        </div>

        <p className="mt-3 text-[12px] text-slate-300">{summary}</p>
        {counts ? (
          <p className="mt-2 text-[11px] text-slate-500">
            scans {counts.recent_scans} / proposals {counts.recent_proposals} / actions {counts.recent_actions} / execution {counts.recent_execution_state}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div className="mt-4 rounded-2xl border border-slate-700 bg-[#071019] px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="terminal-kicker">Canonical Stage</p>
          <p className="mt-2 text-sm text-slate-200">
            {currentStage ? `Stage ${currentStage.number}: ${currentStage.label}` : "Stage status unavailable"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <TerminalBadge
            label={currentStage ? `Stage ${currentStage.number}` : "Stage ?"}
            status={stageStatus?.ready_for_next_stage ? "good" : "neutral"}
          />
          <TerminalBadge label={statusLabel} status={stageStatusBadgeStatus(stageStatus?.status)} />
          <TerminalBadge label={bottleneckLabel} status={bottleneckStatus} />
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-4 text-[11px] uppercase tracking-[0.14em] text-slate-500">
        <span>focus {focusLabel}</span>
        <span>signal {operationalSignal}</span>
        {nextStage ? <span>next {nextStage.number} {cleanLabel(nextStage.label)}</span> : null}
        <span>acceptance {stageStatus?.metrics.acceptance_artifact_count ?? 0}</span>
        <span>stage7 {stageStatus?.metrics.decision_artifact_count ?? 0}</span>
      </div>

      <p className="mt-3 text-sm text-slate-400">{summary}</p>
      {diagnostics?.explanation ? (
        <p className="mt-2 text-[12px] text-slate-500">{diagnostics.explanation}</p>
      ) : null}
      {counts ? (
        <div className="mt-3 grid gap-2 text-[11px] text-slate-500 sm:grid-cols-4">
          <DetailRow label="scans" value={String(counts.recent_scans)} />
          <DetailRow label="proposals" value={String(counts.recent_proposals)} />
          <DetailRow label="actions" value={String(counts.recent_actions)} />
          <DetailRow label="execution" value={String(counts.recent_execution_state)} />
        </div>
      ) : null}

      {stageStatus?.blockers?.length ? (
        <div className="mt-3 space-y-1 text-[11px] text-slate-500">
          {stageStatus.blockers.slice(0, 3).map((item) => (
            <p key={item}>- {item}</p>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function RuleStack({ items }: { items: string[] }) {
  return (
    <div className="space-y-3">
      {items.map((item) => (
        <div key={item} className="grid grid-cols-[1fr_auto] items-center gap-3">
          <div>
            <div className="mb-1 flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-emerald-400" />
              <p className="font-mono text-[13px] text-slate-200">{cleanLabel(item)}</p>
            </div>
            <div className="h-1.5 rounded-full bg-slate-800">
              <div className="h-1.5 rounded-full bg-gradient-to-r from-cyan-400 via-emerald-400 to-cyan-300" style={{ width: "100%" }} />
            </div>
          </div>
          <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-emerald-300">active</span>
        </div>
      ))}
    </div>
  );
}

export function RevisionLoopPanel({
  compareSummary,
  acceptanceSummary,
  acceptanceHistory,
  stage7Summary,
  stageStatus,
  activity,
  results,
  linkedRevisions,
  recentLinkEvents,
  reviews,
  revisions,
  outsideSessionAllowed,
}: {
  compareSummary: ConceptRevisionCompareSummary | null;
  acceptanceSummary: ConceptAcceptanceSummary | null;
  acceptanceHistory: ConceptAcceptanceHistoryItem[];
  stage7Summary: ConceptStage7DecisionSummary | null;
  stageStatus: ConceptStageStatusSummary | null;
  activity: Record<string, unknown>;
  results: RuntimeRevisionResult[];
  linkedRevisions: RuntimeLinkedRevision[];
  recentLinkEvents: EventItem[];
  reviews: ConceptReviewSummaryItem[];
  revisions: ConceptRevisionSummaryItem[];
  outsideSessionAllowed: boolean;
}) {
  const linkedCount = Number(activity.linked_revision_count ?? revisions.length ?? 0);
  const evaluatedCount = Number(activity.evaluated_revision_count ?? 0);
  const autoLinkedCount = Number(activity.auto_linked_count ?? 0);
  const lastSampleStartedAt =
    typeof activity.last_sample_started_at === "string" ? activity.last_sample_started_at : null;
  const stabilityCycles = Number(activity.stability_cycles ?? 0);
  const lastChangedAt =
    typeof activity.last_changed_at === "string" ? String(activity.last_changed_at) : null;
  const compareAction =
    typeof activity.compare_action === "string" && activity.compare_action
      ? activity.compare_action
      : compareSummary?.compare_action ?? compareSummary?.next_action ?? "";
  const leaderExplanation =
    typeof activity.leader_explanation === "string" && activity.leader_explanation
      ? activity.leader_explanation
      : compareSummary?.leader_explanation ?? compareSummary?.takeaway ?? "";
  const statusCounts = asRecord(activity.status_counts);

  const latestResult = results[0] ?? null;
  const latestRevision = revisions[0] ?? null;
  const latestReview = reviews[0] ?? null;
  const latestCompare = compareSummary?.latest_compare_artifact ?? null;
  const stage5Readiness = compareSummary?.stage5_readiness ?? null;

  return (
    <section className="terminal-subpanel p-4">
      <PanelHeader title="Revision Loop" icon={<GitBranch size={14} strokeWidth={1.8} />} meta={linkedCount > 0 ? `${linkedCount} linked` : "awaiting linked reviews"} />
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-2xl border border-slate-800 bg-[#071019] px-4 py-3">
          <p className="terminal-kicker">linked</p>
          <p className="mt-2 font-display text-[28px] leading-none text-slate-50">{linkedCount}</p>
          <p className="mt-2 text-[11px] uppercase tracking-[0.16em] text-slate-500">
            {autoLinkedCount > 0 ? `${autoLinkedCount} auto-linked` : "manual and auto-linked"}
          </p>
        </div>
        <div className="rounded-2xl border border-slate-800 bg-[#071019] px-4 py-3">
          <p className="terminal-kicker">evaluated</p>
          <p className="mt-2 font-display text-[28px] leading-none text-slate-50">{evaluatedCount}</p>
          <p className="mt-2 text-[11px] uppercase tracking-[0.16em] text-slate-500">
            {lastSampleStartedAt ? `sample ${formatTimestamp(lastSampleStartedAt)}` : "waiting for sample"}
          </p>
        </div>
        <div className="rounded-2xl border border-slate-800 bg-[#071019] px-4 py-3">
          <p className="terminal-kicker">latest state</p>
          <div className="mt-2 flex items-center gap-2">
            <TerminalBadge
              label={cleanLabel(latestResult?.status ?? latestRevision?.status ?? "planned")}
              status={revisionStatusBadgeStatus(latestResult?.status ?? latestRevision?.status)}
            />
          </div>
          <p className="mt-2 text-[11px] uppercase tracking-[0.16em] text-slate-500">
            {Object.entries(statusCounts)
              .map(([key, value]) => `${cleanLabel(key)} ${value}`)
              .join(" · ") || "no history yet"}
          </p>
        </div>
      </div>

      <StageStatusSummary stageStatus={stageStatus} />
      <AcceptanceStatusSummary acceptanceSummary={acceptanceSummary} acceptanceHistory={acceptanceHistory} />
      <Stage7DecisionSummary stage7Summary={stage7Summary} />

      {compareSummary ? (
        <div className="mt-4 rounded-2xl border border-cyan-500/20 bg-cyan-500/6 px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="terminal-kicker">daemon comparison takeaway</p>
              <p className="mt-2 text-sm text-slate-200">{leaderExplanation}</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {compareSummary.best_ranked_revision ? (
                <TerminalBadge
                  label={`${compareSummary.best_ranked_revision.revision_id} ${cleanLabel(compareSummary.best_ranked_revision.status ?? "planned")}`}
                  status={revisionStatusBadgeStatus(compareSummary.best_ranked_revision.status)}
                />
              ) : null}
              {latestCompare?.verdict ? (
                <TerminalBadge
                  label={cleanLabel(latestCompare.verdict)}
                  status={revisionCompareVerdictBadgeStatus(latestCompare.verdict)}
                />
              ) : null}
            </div>
          </div>
          <div className="mt-3 space-y-2">
            <p className="text-sm text-slate-400">{compareAction}</p>
            <div className="flex flex-wrap items-center gap-4 text-[11px] uppercase tracking-[0.14em] text-slate-500">
              <span>history {compareSummary.evaluation_history_count}</span>
              <span>artifacts {compareSummary.compare_artifact_count}</span>
              {stabilityCycles > 0 ? <span>stable {stabilityCycles} cycles</span> : null}
              {compareSummary.latest_sample_started_at ? (
                <span>sample {formatTimestamp(compareSummary.latest_sample_started_at)}</span>
              ) : null}
              {lastChangedAt ? <span>changed {formatRelativeTime(lastChangedAt)}</span> : null}
            </div>
          </div>

          {latestCompare ? (
            <div className="mt-4 grid gap-2 text-[11px] md:grid-cols-2">
              <div className="flex items-center justify-between gap-3 rounded-xl border border-slate-800/90 bg-[#08121b] px-3 py-2.5">
                <span className="text-slate-500">latest compare</span>
                <span className="font-mono text-slate-200">
                  {latestCompare.review_id}
                  {latestCompare.created_at ? ` · ${formatRelativeTime(latestCompare.created_at)}` : ""}
                </span>
              </div>
              <div className="flex items-center justify-between gap-3 rounded-xl border border-slate-800/90 bg-[#08121b] px-3 py-2.5">
                <span className="text-slate-500">focus</span>
                <span className="font-mono text-slate-200">
                  {cleanLabel(latestCompare.next_action_focus ?? "n/a")}
                </span>
              </div>
            </div>
          ) : null}

          {stage5Readiness ? (
            <div className="mt-4 rounded-2xl border border-slate-800/90 bg-[#08121b] px-4 py-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="terminal-kicker">Stage 5 Gate</p>
                  <p className="mt-2 text-sm text-slate-200">{stage5Readiness.summary}</p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <TerminalBadge
                    label={cleanLabel(stage5Readiness.status)}
                    status={stageGateBadgeStatus(stage5Readiness.status)}
                  />
                  <TerminalBadge
                    label={`score ${stage5Readiness.score}`}
                    status={stageGateBadgeStatus(stage5Readiness.status)}
                  />
                </div>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-4 text-[11px] uppercase tracking-[0.14em] text-slate-500">
                <span>{stage5Readiness.ready_for_stage_6_from_daemon_state ? "daemon ready for stage 6" : "stage 5 still active"}</span>
                <span>blockers {stage5Readiness.blockers.length}</span>
                {stage5Readiness.metrics.stability_cycles > 0 ? (
                  <span>stable {stage5Readiness.metrics.stability_cycles} cycles</span>
                ) : null}
              </div>
              {stage5Readiness.blockers.length > 0 ? (
                <div className="mt-3 space-y-1 text-[11px] text-slate-500">
                  {stage5Readiness.blockers.slice(0, 3).map((item) => (
                    <p key={item}>- {item}</p>
                  ))}
                </div>
              ) : (
                <p className="mt-3 text-[11px] text-slate-500">{stage5Readiness.caveat}</p>
              )}
            </div>
          ) : null}

          {compareSummary.ranked_revisions.length > 0 ? (
            <div className="mt-4 grid gap-2 md:grid-cols-2">
              {compareSummary.ranked_revisions.slice(0, 2).map((item) => (
                <div key={item.revision_id} className="rounded-xl border border-slate-800/90 bg-[#08121b] px-3 py-2.5">
                  <div className="flex items-center justify-between gap-3">
                    <p className="font-mono text-[12px] text-slate-100">
                      {item.revision_id} · {cleanLabel(item.focus ?? "concept observation")}
                    </p>
                    <span className="font-mono text-[11px] text-cyan-200">score {item.score}</span>
                  </div>
                  <p className="mt-2 text-sm text-slate-400">{formatSessionAwareCopy(item.summary, outsideSessionAllowed)}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <TerminalBadge label={cleanLabel(item.status ?? "planned")} status={revisionStatusBadgeStatus(item.status)} />
                    {item.history_count > 0 ? (
                      <span className="terminal-kicker">history {item.history_count}</span>
                    ) : null}
                  </div>
                  {item.reasons.length > 0 ? (
                    <p className="mt-2 text-[11px] text-slate-500">{item.reasons.join(" ")}</p>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="mt-4 grid gap-3 xl:grid-cols-[1.1fr_0.9fr]">
        <div className="space-y-3">
          <div className="rounded-2xl border border-slate-800 bg-[#071019] px-4 py-3">
            <p className="terminal-kicker">Recent live checks</p>
            <div className="mt-3 space-y-2">
              {results.length > 0 ? (
                results.slice(0, 3).map((item) => (
                  <div key={`${item.revision_id}-${item.review_id}`} className="rounded-xl border border-slate-800/90 bg-[#08121b] px-3 py-2.5">
                    <div className="flex items-center justify-between gap-3">
                      <p className="font-mono text-[12px] text-slate-100">
                        {item.revision_id} / {item.review_id}
                      </p>
                      <TerminalBadge label={cleanLabel(item.status)} status={revisionStatusBadgeStatus(item.status)} />
                    </div>
                    <p className="mt-2 text-sm text-slate-400">{formatSessionAwareCopy(item.summary || cleanLabel(item.reason ?? "waiting for evaluation"), outsideSessionAllowed)}</p>
                    <p className="mt-2 text-[11px] uppercase tracking-[0.14em] text-slate-500">
                      {item.current_sample_started_at ? `sample ${formatTimestamp(item.current_sample_started_at)}` : "no sample anchor"}
                      {item.history_count ? ` · history ${item.history_count}` : ""}
                      {item.skipped ? " · skipped" : ""}
                    </p>
                  </div>
                ))
              ) : (
                <p className="text-sm text-slate-500">No linked revision checks recorded yet.</p>
              )}
            </div>
          </div>

          {linkedRevisions.length > 0 || recentLinkEvents.length > 0 ? (
            <div className="rounded-2xl border border-slate-800 bg-[#071019] px-4 py-3">
              <p className="terminal-kicker">Latest auto-link</p>
              <div className="mt-3 space-y-2">
                {linkedRevisions.length > 0
                  ? linkedRevisions.slice(0, 2).map((item) => (
                      <div key={`${item.revision_id}-${item.review_id}`} className="flex items-center justify-between gap-3 border-b border-slate-800/90 pb-2 last:border-b-0 last:pb-0">
                        <div>
                          <p className="font-mono text-[12px] text-slate-100">
                            {item.revision_id} from {item.review_id}
                          </p>
                          <p className="mt-1 text-[11px] uppercase tracking-[0.14em] text-slate-500">
                            {cleanLabel(item.focus ?? "concept observation")} · {cleanLabel(item.mode ?? "observe")} · {cleanLabel(item.readiness ?? "now")}
                          </p>
                        </div>
                        <TerminalBadge label="linked" status="good" />
                      </div>
                    ))
                  : recentLinkEvents.slice(0, 2).map((item) => (
                      <div key={item.event_id} className="flex items-center justify-between gap-3 border-b border-slate-800/90 pb-2 last:border-b-0 last:pb-0">
                        <div>
                          <p className="font-mono text-[12px] text-slate-100">{formatSessionAwareCopy(item.summary, outsideSessionAllowed)}</p>
                          <p className="mt-1 text-[11px] uppercase tracking-[0.14em] text-slate-500">
                            {formatTimestamp(item.created_at)}
                          </p>
                        </div>
                        <TerminalBadge label="linked" status="good" />
                      </div>
                    ))}
              </div>
            </div>
          ) : null}
        </div>

        <div className="space-y-3">
          <div className="rounded-2xl border border-slate-800 bg-[#071019] px-4 py-3">
            <p className="terminal-kicker">Saved reviews</p>
            <div className="mt-3 space-y-2">
              {reviews.length > 0 ? (
                reviews.slice(0, 3).map((item) => (
                  <div key={item.review_id} className="border-b border-slate-800/90 pb-2 last:border-b-0 last:pb-0">
                    <div className="flex items-center justify-between gap-3">
                      <p className="font-mono text-[12px] text-slate-100">{item.review_id}</p>
                      <span className="terminal-kicker">{formatTimestamp(item.created_at)}</span>
                    </div>
                    <p className="mt-1 text-sm text-slate-400">{formatSessionAwareCopy(item.summary, outsideSessionAllowed)}</p>
                  </div>
                ))
              ) : (
                <p className="text-sm text-slate-500">No saved structured reviews yet.</p>
              )}
            </div>
          </div>

          <div className="rounded-2xl border border-slate-800 bg-[#071019] px-4 py-3">
            <p className="terminal-kicker">Saved revisions</p>
            <div className="mt-3 space-y-2">
              {revisions.length > 0 ? (
                revisions.slice(0, 3).map((item) => (
                  <div key={item.revision_id} className="border-b border-slate-800/90 pb-2 last:border-b-0 last:pb-0">
                    <div className="flex items-center justify-between gap-3">
                      <p className="font-mono text-[12px] text-slate-100">{item.revision_id}</p>
                      <TerminalBadge label={cleanLabel(item.status ?? "planned")} status={revisionStatusBadgeStatus(item.status)} />
                    </div>
                    <p className="mt-1 text-[11px] uppercase tracking-[0.14em] text-slate-500">
                      {cleanLabel(item.focus ?? "concept observation")} · {formatTimestamp(item.created_at)}
                    </p>
                    <p className="mt-1 text-sm text-slate-400">{formatSessionAwareCopy(item.summary, outsideSessionAllowed)}</p>
                  </div>
                ))
              ) : (
                <p className="text-sm text-slate-500">No saved revisions yet.</p>
              )}
            </div>
          </div>

          {latestReview ? (
            <p className="text-[11px] text-slate-500">
              Latest review author: <span className="font-mono text-slate-300">{latestReview.author ?? latestReview.source}</span>
            </p>
          ) : null}
        </div>
      </div>
    </section>
  );
}

export function getControlRecord(snapshot: DashboardSnapshot | null, controlKey: string): ControlItem {
  const normalized = controlKey.trim().toLowerCase();
  const existing = snapshot?.controls.find((item) => item.control_key === normalized);
  if (existing) {
    return existing;
  }

  if (normalized === "global") {
    return {
      control_key: "global",
      paused: Boolean(snapshot?.health.global_control_paused),
      reason: snapshot?.health.global_control_reason ?? null,
      updated_at: null,
      effective: {
        paused: Boolean(snapshot?.health.global_control_paused),
        reason: snapshot?.health.global_control_reason ?? null,
      },
    };
  }

  return {
    control_key: normalized,
    paused: false,
    reason: null,
    updated_at: null,
    effective: {
      paused: false,
      reason: null,
    },
  };
}

export function upsertControlRecord(snapshot: DashboardSnapshot | null, record: ControlItem): DashboardSnapshot | null {
  if (!snapshot) {
    return snapshot;
  }

  const controls = [...snapshot.controls];
  const index = controls.findIndex((item) => item.control_key === record.control_key);
  if (index >= 0) {
    controls[index] = record;
  } else {
    controls.push(record);
  }

  const nextSnapshot: DashboardSnapshot = {
    ...snapshot,
    controls,
  };

  if (record.control_key === "global") {
    nextSnapshot.health = {
      ...snapshot.health,
      global_control_paused: record.effective?.paused ?? record.paused,
      global_control_reason: record.effective?.reason ?? record.reason,
    };
  }

  return nextSnapshot;
}

export function isControlItem(value: unknown): value is ControlItem {
  return Boolean(
    value &&
      typeof value === "object" &&
      "control_key" in value &&
      "paused" in value &&
      "updated_at" in value,
  );
}

export function ScanFeed({
  items,
  emptyLabel,
  allowedSessions,
}: {
  items: ScanHistoryItem[];
  emptyLabel: string;
  allowedSessions: string[];
}) {
  if (items.length === 0) {
    return <p className="text-sm text-slate-500">{emptyLabel}</p>;
  }

  return (
    <div className="max-h-[360px] space-y-3 overflow-auto pr-1">
      {items.map((item) => (
        <div key={item.scan_id} className="terminal-subpanel px-4 py-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <span
                  className={`inline-block h-2 w-2 rounded-full ${
                    isExecutionEligibleDecision(item.decision) ? "bg-cyan-300" : "bg-slate-600"
                  }`}
                />
                <p className="font-mono text-[13px] text-slate-100">{item.instrument} {item.decision}</p>
              </div>
              <p className="mt-2 text-[11px] text-slate-500">
                session {formatSessionDisplayLabel(item.session || "-", allowedSessions, "-")} · direction {item.direction || "not aligned"}
              </p>
            </div>
            <span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{formatTimestamp(item.created_at)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

export function TimelineFeed({
  items,
  selectedEventId,
  onSelectEvent,
  onOpenReview,
  expandedGroupId,
  onToggleGroup,
  outsideSessionAllowed,
}: {
  items: ScoredGroupedTimelineItem[];
  selectedEventId: string | null;
  onSelectEvent: (eventId: string | null) => void;
  onOpenReview: () => void;
  expandedGroupId: string | null;
  onToggleGroup: (groupId: string | null) => void;
  outsideSessionAllowed: boolean;
}) {
  if (items.length === 0) {
    return <p className="text-sm text-slate-500">No recent daemon events yet.</p>;
  }

  return (
    <div className="max-h-[360px] space-y-3 overflow-auto pr-1">
      {items.map(({ representative: item, count, members, relevanceScore, relevanceLabel, relevanceReasons, relevanceBreakdown }) => (
        <div
          key={item.id}
          className={`terminal-subpanel px-4 py-3 transition ${selectedEventId === item.id ? "border-cyan-400/30 bg-cyan-400/5" : ""}`}
        >
          <button type="button" onClick={() => onSelectEvent(selectedEventId === item.id ? null : item.id)} className="w-full text-left">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`inline-block h-2 w-2 rounded-full ${timelineAccentClasses(item.severity)}`} />
                  <span className="terminal-kicker text-[9px]">{cleanLabel(item.source)}</span>
                  <span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{cleanLabel(item.kind)}</span>
                  {item.symbol ? <span className="text-[10px] uppercase tracking-[0.16em] text-cyan-400">{item.symbol}</span> : null}
                  {item.meta ? <span className="text-[10px] uppercase tracking-[0.16em] text-slate-600">{cleanLabel(item.meta)}</span> : null}
                  {count > 1 ? (
                    <span className="rounded-full border border-amber-400/20 bg-amber-500/15 px-2 py-0.5 text-[9px] uppercase tracking-[0.16em] text-amber-100">
                      x{count}
                    </span>
                  ) : null}
                  <span
                    className={`rounded-full border px-2 py-0.5 text-[9px] uppercase tracking-[0.16em] ${
                      relevanceLabel === "high"
                        ? "border-emerald-400/20 bg-emerald-500/15 text-emerald-200"
                        : relevanceLabel === "medium"
                          ? "border-cyan-400/20 bg-cyan-500/15 text-cyan-200"
                          : "border-slate-700 bg-slate-900/70 text-slate-300"
                    }`}
                  >
                    {relevanceLabel} {relevanceScore}
                  </span>
                </div>
                <p className="mt-2 font-mono text-[13px] text-slate-100">{item.title}</p>
                <p className="mt-2 text-[11px] text-slate-500">{formatSessionAwareCopy(item.summary, outsideSessionAllowed)}</p>
                {relevanceReasons.length > 0 ? (
                  <p className="mt-2 text-[11px] text-cyan-200/80">Why this matters: {relevanceReasons.join(" · ")}</p>
                ) : null}
                {count > 1 ? (
                  <p className="mt-2 text-[11px] text-amber-100/80">Collapsed {count} repeated daemon events into this row.</p>
                ) : null}
              </div>
              <span className="shrink-0 text-[10px] uppercase tracking-[0.16em] text-slate-500">{formatRelativeTime(item.created_at)}</span>
            </div>
          </button>
          {selectedEventId === item.id ? (
            <div className="mt-3 rounded-xl border border-slate-800 bg-[#050d15] px-3 py-3">
              <div className="grid gap-2 text-[11px] md:grid-cols-2">
                <div>
                  <p className="terminal-kicker">Event Type</p>
                  <p className="mt-1 font-mono text-slate-200">{cleanLabel(item.event_type)}</p>
                </div>
                <div>
                  <p className="terminal-kicker">Severity</p>
                  <p className="mt-1 font-mono text-slate-200">{item.severity}</p>
                </div>
                <div>
                  <p className="terminal-kicker">Symbol</p>
                  <p className="mt-1 font-mono text-slate-200">{item.symbol ?? "-"}</p>
                </div>
                <div>
                  <p className="terminal-kicker">Proposal</p>
                  <p className="mt-1 font-mono text-slate-200">{item.proposal_id ?? "-"}</p>
                </div>
                <div>
                  <p className="terminal-kicker">Relevance</p>
                  <p className="mt-1 font-mono text-slate-200">{relevanceLabel} · {relevanceScore}</p>
                </div>
                <div>
                  <p className="terminal-kicker">Why</p>
                  <p className="mt-1 font-mono text-slate-200">{relevanceReasons.join(" · ") || "-"}</p>
                </div>
              </div>
              {relevanceBreakdown.length > 0 ? (
                <div className="mt-3 rounded-xl border border-slate-800 bg-[#071019] px-3 py-3">
                  <p className="terminal-kicker">Score Breakdown</p>
                  <div className="mt-2 space-y-2">
                    {relevanceBreakdown.map((entry) => (
                      <div key={`${item.id}-${entry.label}`} className="flex items-center justify-between gap-3 text-[11px]">
                        <span className="text-slate-400">{entry.label}</span>
                        <span className="font-mono text-cyan-200">+{entry.points}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={onOpenReview}
                  className="rounded-full border border-cyan-400/30 bg-cyan-400/10 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-200 transition hover:border-cyan-300/40"
                >
                  Open Review Deck
                </button>
                {count > 1 ? (
                  <button
                    type="button"
                    onClick={() => onToggleGroup(expandedGroupId === item.id ? null : item.id)}
                    className="rounded-full border border-amber-400/20 bg-amber-500/15 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-100 transition hover:border-amber-300/30"
                  >
                    {expandedGroupId === item.id ? "Hide Cluster" : `Expand Cluster (${count})`}
                  </button>
                ) : null}
                <span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">marker focus {item.id}</span>
              </div>
              {count > 1 && expandedGroupId === item.id ? (
                <div className="mt-3 space-y-2">
                  {members.map((member) => (
                    <div key={`cluster-${member.id}`} className="rounded-xl border border-slate-800 bg-[#071019] px-3 py-2">
                      <div className="flex items-center justify-between gap-3">
                        <p className="font-mono text-[12px] text-slate-100">{member.title}</p>
                        <span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
                          {formatTimestamp(member.created_at)}
                        </span>
                      </div>
                      <p className="mt-1 text-[11px] text-slate-500">{member.summary}</p>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

export function EventConsole({
  items,
  activeFilter,
  onFilterChange,
  activePreset,
  onPresetChange,
  severityFilter,
  onSeverityFilterChange,
  scope,
  onScopeChange,
  followFocusedEvent,
  onToggleFollow,
  relevanceContext,
  structureFocus,
  onClearStructureFocus,
  selectedEventId,
  onSelectEvent,
  onOpenReview,
  outsideSessionAllowed,
}: {
  items: ControlRoomTimelineItem[];
  activeFilter: EventConsoleFilter;
  onFilterChange: (filter: EventConsoleFilter) => void;
  activePreset: EventConsolePreset;
  onPresetChange: (preset: EventConsolePreset) => void;
  severityFilter: EventConsoleSeverityFilter;
  onSeverityFilterChange: (severity: EventConsoleSeverityFilter) => void;
  scope: EventConsoleScope;
  onScopeChange: (scope: EventConsoleScope) => void;
  followFocusedEvent: boolean;
  onToggleFollow: (value: boolean) => void;
  relevanceContext: {
    selectedSymbol: string;
    currentProposalId: string | null;
    activeExecutionProposalId: string | null;
    currentTradeState: string;
    conceptRecommendation: string;
    dominantBlocker: string;
    operatorSignal: string;
    structureFocus: StructureFocus | null;
  };
  structureFocus: StructureFocus | null;
  onClearStructureFocus: () => void;
  selectedEventId: string | null;
  onSelectEvent: (eventId: string | null) => void;
  onOpenReview: () => void;
  outsideSessionAllowed: boolean;
}) {
  const filters: EventConsoleFilter[] = ["all", "scan", "proposal", "execution", "concept", "control", "ops"];
  const severityFilters: EventConsoleSeverityFilter[] = ["all", "error", "warning", "info"];
  const [searchQuery, setSearchQuery] = useState("");
  const [expandedGroupId, setExpandedGroupId] = useState<string | null>(null);
  const deferredSearchQuery = useDeferredValue(searchQuery);
  const presets: Array<{ id: EventConsolePreset; label: string; apply: () => void }> = [
    {
      id: "execution_triage",
      label: "Execution Triage",
      apply: () => {
        onPresetChange("execution_triage");
        onFilterChange("execution");
        onSeverityFilterChange("all");
        setSearchQuery("");
      },
    },
    {
      id: "concept_review",
      label: "Concept Review",
      apply: () => {
        onPresetChange("concept_review");
        onFilterChange("concept");
        onSeverityFilterChange("warning");
        setSearchQuery("");
      },
    },
    {
      id: "control_actions",
      label: "Control Actions",
      apply: () => {
        onPresetChange("control_actions");
        onFilterChange("control");
        onSeverityFilterChange("all");
        setSearchQuery("");
      },
    },
  ];
  const counts = filters.reduce<Record<EventConsoleFilter, number>>(
    (accumulator, filter) => {
      accumulator[filter] =
        filter === "all" ? items.length : items.filter((item) => classifyTimelineItem(item) === filter).length;
      return accumulator;
    },
    {
      all: 0,
      scan: 0,
      proposal: 0,
      execution: 0,
      concept: 0,
      control: 0,
      ops: 0,
    },
  );
  const severityCounts = severityFilters.reduce<Record<EventConsoleSeverityFilter, number>>(
    (accumulator, severity) => {
      accumulator[severity] =
        severity === "all" ? items.length : items.filter((item) => item.severity === severity).length;
      return accumulator;
    },
    {
      all: 0,
      error: 0,
      warning: 0,
      info: 0,
    },
  );

  const filteredItems = items.filter((item) => {
    if (activeFilter !== "all" && classifyTimelineItem(item) !== activeFilter) {
      return false;
    }

    if (severityFilter !== "all" && item.severity !== severityFilter) {
      return false;
    }

    const normalizedQuery = deferredSearchQuery.trim().toLowerCase();
    if (!normalizedQuery) {
      return true;
    }

    const haystack = [item.title, item.summary, item.source, item.kind, item.meta, item.event_type, item.symbol, item.proposal_id]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();

    return haystack.includes(normalizedQuery);
  });
  const scoredItems = useMemo(
    () => scoreGroupedTimelineItems(groupTimelineItems(filteredItems), relevanceContext),
    [filteredItems, relevanceContext],
  );
  const groupedItems = useMemo(
    () => filterStructureFocusedTimelineItems(scoredItems, structureFocus, relevanceContext.selectedSymbol),
    [relevanceContext.selectedSymbol, scoredItems, structureFocus],
  );
  const structureLens = structureFocusConfig(structureFocus);
  const topRankedEvent = groupedItems[0] ?? null;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {(["selected", "global"] as EventConsoleScope[]).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => onScopeChange(value)}
              className={`rounded-full border px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] transition ${
                scope === value
                  ? "border-cyan-400/30 bg-cyan-400/10 text-cyan-200"
                  : "border-slate-700 bg-[#09111a] text-slate-400 hover:border-slate-600 hover:text-slate-200"
              }`}
            >
              {value === "selected" ? "Selected Market" : "Global Stream"}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => onToggleFollow(!followFocusedEvent)}
          className={`rounded-full border px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] transition ${
            followFocusedEvent
              ? "border-emerald-400/30 bg-emerald-500/15 text-emerald-200"
              : "border-slate-700 bg-[#09111a] text-slate-400 hover:border-slate-600 hover:text-slate-200"
          }`}
        >
          {followFocusedEvent ? "Follow Focus On" : "Follow Focus Off"}
        </button>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        {filters.map((filter) => {
          const active = activeFilter === filter;
          return (
            <button
              key={filter}
              type="button"
              onClick={() => {
                onPresetChange("custom");
                onFilterChange(filter);
              }}
              className={`rounded-full border px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] transition ${
                active
                  ? "border-cyan-400/30 bg-cyan-400/10 text-cyan-200"
                  : "border-slate-700 bg-[#09111a] text-slate-400 hover:border-slate-600 hover:text-slate-200"
              }`}
            >
              {cleanLabel(filter)} {counts[filter]}
            </button>
          );
        })}
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        {presets.map((preset) => (
          <button
            key={preset.id}
            type="button"
            onClick={preset.apply}
            className={`rounded-full border px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] transition ${
              activePreset === preset.id
                ? "border-emerald-400/30 bg-emerald-500/15 text-emerald-200"
                : "border-slate-700 bg-[#09111a] text-slate-400 hover:border-slate-600 hover:text-slate-200"
            }`}
          >
            {preset.label}
          </button>
        ))}
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        {severityFilters.map((severity) => (
            <button
              key={severity}
              type="button"
              onClick={() => {
                onPresetChange("custom");
                onSeverityFilterChange(severity);
              }}
            className={`rounded-full border px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] transition ${severityChipClasses(
              severity,
              severityFilter === severity,
            )}`}
          >
            {cleanLabel(severity)} {severityCounts[severity]}
          </button>
        ))}
      </div>

      <div className="mb-3">
        <input
          value={searchQuery}
          onChange={(event) => {
            onPresetChange("custom");
            setSearchQuery(event.target.value);
          }}
          placeholder="Search event title, summary, source, symbol, proposal..."
          className="w-full rounded-2xl border border-slate-700 bg-[#09111a] px-4 py-3 font-mono text-[12px] text-slate-200 outline-none transition placeholder:text-slate-500 focus:border-cyan-400/40"
        />
      </div>

      {structureLens ? (
        <div className="mb-3 terminal-subpanel p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="terminal-kicker">Structure Lens Active</p>
              <p className="mt-2 font-mono text-[13px] text-cyan-200">{structureLens.label}</p>
              <p className="mt-2 text-[12px] text-slate-400">
                The daemon console is prioritizing events most correlated to the selected ICT structure.
              </p>
            </div>
            <button
              type="button"
              onClick={onClearStructureFocus}
              className="rounded-full border border-slate-700 bg-[#09111a] px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-300 transition hover:border-slate-600 hover:text-slate-100"
            >
              Clear Lens
            </button>
          </div>
        </div>
      ) : null}

      <div className="mb-3 flex items-center justify-between gap-3 text-[10px] uppercase tracking-[0.16em] text-slate-500">
        <span>
          Live daemon console · ranked by relevance{structureLens ? ` · ${structureLens.label}` : ""}
        </span>
        <span>
          {groupedItems.length} grouped rows · {filteredItems.length} raw events
          {filteredItems.length > groupedItems.length
            ? ` · ${Math.round((1 - groupedItems.length / filteredItems.length) * 100)}% noise reduced`
            : ""}
        </span>
      </div>

      {topRankedEvent ? (
        <div className="mb-3 terminal-subpanel p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="terminal-kicker">Top Ranked Event</p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <span className={`inline-block h-2 w-2 rounded-full ${timelineAccentClasses(topRankedEvent.representative.severity)}`} />
                <span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
                  {cleanLabel(topRankedEvent.representative.source)}
                </span>
                {topRankedEvent.representative.symbol ? (
                  <span className="text-[10px] uppercase tracking-[0.16em] text-cyan-400">
                    {topRankedEvent.representative.symbol}
                  </span>
                ) : null}
                {topRankedEvent.count > 1 ? (
                  <span className="rounded-full border border-amber-400/20 bg-amber-500/15 px-2 py-0.5 text-[9px] uppercase tracking-[0.16em] text-amber-100">
                    x{topRankedEvent.count}
                  </span>
                ) : null}
              </div>
              <p className="mt-3 font-mono text-[14px] text-slate-100">{topRankedEvent.representative.title}</p>
              <p className="mt-2 max-w-3xl text-[12px] text-slate-400">{topRankedEvent.representative.summary}</p>
            </div>
            <span
              className={`rounded-full border px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] ${
                topRankedEvent.relevanceLabel === "high"
                  ? "border-emerald-400/20 bg-emerald-500/15 text-emerald-200"
                  : topRankedEvent.relevanceLabel === "medium"
                    ? "border-cyan-400/20 bg-cyan-500/15 text-cyan-200"
                    : "border-slate-700 bg-slate-900/70 text-slate-300"
              }`}
            >
              {topRankedEvent.relevanceLabel} {topRankedEvent.relevanceScore}
            </span>
          </div>

          {topRankedEvent.relevanceReasons.length > 0 ? (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {topRankedEvent.relevanceReasons.map((reason) => (
                <span
                  key={`${topRankedEvent.representative.id}-${reason}`}
                  className="rounded-full border border-cyan-400/15 bg-cyan-500/15 px-3 py-1 text-[10px] uppercase tracking-[0.14em] text-cyan-100"
                >
                  {reason}
                </span>
              ))}
            </div>
          ) : null}

          {topRankedEvent.relevanceBreakdown.length > 0 ? (
            <div className="mt-3 grid gap-2 md:grid-cols-3">
              {topRankedEvent.relevanceBreakdown.slice(0, 3).map((entry) => (
                <div key={`${topRankedEvent.representative.id}-${entry.label}`} className="rounded-xl border border-slate-800 bg-[#071019] px-3 py-3">
                  <p className="terminal-kicker">Score Driver</p>
                  <p className="mt-2 text-[12px] text-slate-300">{entry.label}</p>
                  <p className="mt-2 font-mono text-[13px] text-cyan-200">+{entry.points}</p>
                </div>
              ))}
            </div>
          ) : null}

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => {
                onSelectEvent(topRankedEvent.representative.id);
                setExpandedGroupId(topRankedEvent.count > 1 ? topRankedEvent.representative.id : null);
              }}
              className="rounded-full border border-cyan-400/30 bg-cyan-400/10 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-200 transition hover:border-cyan-300/40"
            >
              {selectedEventId === topRankedEvent.representative.id ? "Focused" : "Focus Top Event"}
            </button>
            <button
              type="button"
              onClick={onOpenReview}
              className="rounded-full border border-slate-700 bg-[#09111a] px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-300 transition hover:border-slate-600 hover:text-slate-100"
            >
              Open Review Deck
            </button>
            <span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
              {formatRelativeTime(topRankedEvent.representative.created_at)}
            </span>
          </div>
        </div>
      ) : null}

      <TimelineFeed
        items={groupedItems.slice(0, 14)}
        selectedEventId={selectedEventId}
        onSelectEvent={onSelectEvent}
        onOpenReview={onOpenReview}
        expandedGroupId={expandedGroupId}
        onToggleGroup={setExpandedGroupId}
        outsideSessionAllowed={outsideSessionAllowed}
      />
    </div>
  );
}

export function ExecutionTable({ items }: { items: ExecutionStateItem[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-slate-500">No execution evidence rows yet.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-left text-sm text-slate-300">
        <thead className="text-[10px] uppercase tracking-[0.18em] text-slate-500">
          <tr>
            <th className="pb-3 pr-4">Pair</th>
            <th className="pb-3 pr-4">Sync</th>
            <th className="pb-3 pr-4">Order</th>
            <th className="pb-3 pr-4">Pos</th>
            <th className="pb-3">Updated</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.proposal_id} className="border-t border-slate-800/90">
              <td className="py-3 pr-4 font-mono text-slate-100">{item.symbol}</td>
              <td className="py-3 pr-4">{item.sync_status}</td>
              <td className="py-3 pr-4">{item.order_status ?? "-"}</td>
              <td className="py-3 pr-4">{item.position_size ?? "-"}</td>
              <td className="py-3">{formatTimestamp(item.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function FocusedInspectionRail({
  event,
  proposal,
  execution,
  action,
  auditTrail,
  symbolAuditTrail,
  conceptRecommendation,
  operatorSignal,
  dominantBlocker,
  actionState,
  canSubmit,
  canSync,
  canCancel,
  onSubmit,
  onSync,
  onCancel,
  onOpenReview,
  onFocusEvent,
  onClear,
  outsideSessionAllowed,
}: {
  event: ControlRoomTimelineItem | null;
  proposal: ProposalItem | null;
  execution: ExecutionStateItem | null;
  action: ExecutionActionItem | null;
  auditTrail: ControlRoomTimelineItem[];
  symbolAuditTrail: ControlRoomTimelineItem[];
  conceptRecommendation: string;
  operatorSignal: string;
  dominantBlocker: string;
  actionState: ActionState;
  canSubmit: boolean;
  canSync: boolean;
  canCancel: boolean;
  onSubmit: () => void;
  onSync: () => void;
  onCancel: () => void;
  onOpenReview: () => void;
  onFocusEvent: (eventId: string) => void;
  onClear: () => void;
  outsideSessionAllowed: boolean;
}) {
  if (!event) {
    return (
      <div className="terminal-panel p-4">
        <PanelHeader title="Inspection Rail" meta="awaiting focus" icon={<TrainFront size={14} strokeWidth={1.8} />} />
        <p className="text-sm text-slate-500">
          Select an event in the daemon console to inspect its related proposal, execution, and concept context here.
        </p>
      </div>
    );
  }

  const groupedAuditTrail = groupTimelineItems(auditTrail).slice(0, 4);
  const groupedSymbolAuditTrail = groupTimelineItems(symbolAuditTrail).slice(0, 6);

  return (
    <div className="terminal-panel p-4">
      <PanelHeader title="Inspection Rail" meta={cleanLabel(event.kind)} />
      <div className="space-y-3">
        <div className="terminal-subpanel p-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="font-mono text-[13px] text-slate-100">{event.title}</p>
              <p className="mt-2 text-[12px] text-slate-400">{formatSessionAwareCopy(event.summary, outsideSessionAllowed)}</p>
            </div>
            <span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{formatRelativeTime(event.created_at)}</span>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <TerminalBadge label={cleanLabel(event.severity)} status={event.severity === "error" ? "danger" : event.severity === "warning" ? "warn" : "good"} />
            <TerminalBadge label={event.symbol ?? "no symbol"} status="neutral" />
            {event.proposal_id ? <TerminalBadge label={event.proposal_id} status="neutral" /> : null}
          </div>
        </div>

        <div className="terminal-subpanel p-3">
          <p className="terminal-kicker">Proposal Link</p>
          <p className="mt-2 font-mono text-[13px] text-slate-100">{proposal ? `${proposal.proposal_id} · ${proposal.status}` : "No linked proposal"}</p>
          <p className="mt-2 text-[12px] text-slate-500">
            {proposal ? `${proposal.side} ${proposal.symbol} · qty ${proposal.qty} · venue ${proposal.venue}` : "This event is not tied to an active proposal row."}
          </p>
        </div>

        <div className="terminal-subpanel p-3">
          <p className="terminal-kicker">Execution Link</p>
          <p className="mt-2 font-mono text-[13px] text-slate-100">{execution ? `${execution.sync_status} · ${execution.order_status ?? "no order status"}` : "No linked execution row"}</p>
          <p className="mt-2 text-[12px] text-slate-500">
            {execution
              ? `${execution.symbol} · pos ${execution.position_size ?? "-"} · updated ${formatRelativeTime(execution.updated_at)}`
              : "No exchange lifecycle row is currently attached to this focused event."}
          </p>
        </div>

        <div className="terminal-subpanel p-3">
          <p className="terminal-kicker">Action Link</p>
          <p className="mt-2 font-mono text-[13px] text-slate-100">{action ? `${action.action_type} · ${action.status}` : "No linked execution action"}</p>
          <p className="mt-2 text-[12px] text-slate-500">
            {action
              ? `${action.venue} · ${action.order_id ?? action.order_link_id ?? "no order ref"}`
              : "No recent execution action row matches this focused event."}
          </p>
        </div>

        <div className="terminal-subpanel p-3">
          <p className="terminal-kicker">Concept Context</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <TerminalBadge label={cleanLabel(conceptRecommendation)} status={verdictBadgeStatus(conceptRecommendation)} />
            <TerminalBadge label={cleanLabel(operatorSignal)} status="good" />
          </div>
          <p className="mt-2 text-[12px] text-slate-500">Dominant blocker: {cleanLabel(dominantBlocker)}</p>
        </div>

        <div className="terminal-subpanel p-3">
          <p className="terminal-kicker">Audit Trail</p>
          {groupedAuditTrail.length > 0 ? (
            <div className="mt-2 space-y-2">
              {groupedAuditTrail.map(({ representative: item, count }) => (
                <div key={`audit-${item.id}`} className="rounded-xl border border-slate-800 bg-[#050d15] px-3 py-2">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-mono text-[12px] text-slate-100">{item.title}</p>
                      <p className="mt-1 text-[11px] text-slate-500">{formatSessionAwareCopy(item.summary, outsideSessionAllowed)}</p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      {count > 1 ? (
                        <span className="rounded-full border border-amber-400/20 bg-amber-500/15 px-2 py-0.5 text-[9px] uppercase tracking-[0.16em] text-amber-100">
                          x{count}
                        </span>
                      ) : null}
                      <span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{formatRelativeTime(item.created_at)}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-2 text-[12px] text-slate-500">No adjacent audit trail exists yet for this focused event.</p>
          )}
        </div>

        <div className="terminal-subpanel p-3">
          <p className="terminal-kicker">Per-Symbol Audit</p>
          {groupedSymbolAuditTrail.length > 0 ? (
            <div className="mt-2 space-y-2">
              {groupedSymbolAuditTrail.map(({ representative: item, count }) => (
                <div key={`symbol-audit-${item.id}`} className="rounded-xl border border-slate-800 bg-[#050d15] px-3 py-2">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-mono text-[12px] text-slate-100">{item.title}</p>
                      <p className="mt-1 text-[11px] text-slate-500">{formatSessionAwareCopy(item.summary, outsideSessionAllowed)}</p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      {count > 1 ? (
                        <span className="rounded-full border border-amber-400/20 bg-amber-500/15 px-2 py-0.5 text-[9px] uppercase tracking-[0.16em] text-amber-100">
                          x{count}
                        </span>
                      ) : null}
                      <span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{formatRelativeTime(item.created_at)}</span>
                    </div>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() => onFocusEvent(item.id)}
                      className="rounded-full border border-cyan-400/30 bg-cyan-400/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-200 transition hover:border-cyan-300/40"
                    >
                      Focus Event
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-2 text-[12px] text-slate-500">No symbol-specific audit history is available yet.</p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <ActionButton
            label="Submit Focused"
            tone="good"
            disabled={!canSubmit}
            busy={actionState.status === "pending" && actionState.actionKey === "submit-proposal"}
            onClick={onSubmit}
          />
          <ActionButton
            label="Sync Focused"
            tone="neutral"
            disabled={!canSync}
            busy={actionState.status === "pending" && actionState.actionKey === "sync-proposal"}
            onClick={onSync}
          />
          <ActionButton
            label="Cancel Focused"
            tone="danger"
            disabled={!canCancel}
            busy={actionState.status === "pending" && actionState.actionKey === "cancel-proposal"}
            onClick={onCancel}
          />
          <button
            type="button"
            onClick={onOpenReview}
            className="rounded-full border border-cyan-400/30 bg-cyan-400/10 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-200 transition hover:border-cyan-300/40"
          >
            Open Review Deck
          </button>
          <button
            type="button"
            onClick={onClear}
            className="rounded-full border border-slate-700 bg-[#09111a] px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-300 transition hover:border-slate-600"
          >
            Clear Focus
          </button>
        </div>
      </div>
    </div>
  );
}

export function workflowStatusClasses(status: WorkflowStatus) {
  if (status === "complete") {
    return {
      dot: "bg-emerald-300",
      text: "text-emerald-200",
      pill: "bg-emerald-500/15 text-emerald-200 border-emerald-500/20",
    };
  }
  if (status === "active") {
    return {
      dot: "bg-cyan-300",
      text: "text-cyan-200",
      pill: "bg-cyan-500/15 text-cyan-200 border-cyan-500/20",
    };
  }
  if (status === "blocked") {
    return {
      dot: "bg-rose-300",
      text: "text-rose-200",
      pill: "bg-rose-500/15 text-rose-200 border-rose-500/20",
    };
  }
  return {
    dot: "bg-amber-300",
    text: "text-amber-100",
    pill: "bg-amber-500/15 text-amber-100 border-amber-500/20",
  };
}

export function WorkflowRunbook({
  steps,
  nextAction,
}: {
  steps: WorkflowStep[];
  nextAction: string;
}) {
  return (
    <div>
      <div className="space-y-3">
        {steps.map((step, index) => {
          const classes = workflowStatusClasses(step.status);
          return (
            <div key={step.id} className="terminal-subpanel px-4 py-3">
              <div className="flex items-start gap-3">
                <div className="flex flex-col items-center">
                  <span className={`mt-1 inline-block h-2.5 w-2.5 rounded-full ${classes.dot}`} />
                  {index < steps.length - 1 ? <span className="mt-2 h-10 w-px bg-slate-800" /> : null}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-3">
                    <p className={`font-mono text-[13px] ${classes.text}`}>{step.title}</p>
                    <span className={`rounded-full border px-2.5 py-1 text-[10px] uppercase tracking-[0.16em] ${classes.pill}`}>
                      {step.status}
                    </span>
                  </div>
                  <p className="mt-2 text-[12px] text-slate-400">{step.detail}</p>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-3 terminal-subpanel p-3">
        <p className="terminal-kicker">Next Operator Move</p>
        <p className="mt-2 text-sm text-slate-300">{nextAction}</p>
      </div>
    </div>
  );
}

export function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[120px_1fr] gap-3 border-b border-slate-800/80 py-2 last:border-b-0">
      <span className="terminal-kicker">{label}</span>
      <span className="font-mono text-[12px] text-slate-200">{value}</span>
    </div>
  );
}

export function RuntimeSurfaceCard({
  title,
  meta,
  children,
}: {
  title: string;
  meta?: string;
  children: ReactNode;
}) {
  return (
    <div className="terminal-subpanel p-3">
      <div className="mb-2 flex items-center justify-between gap-3">
        <p className="terminal-kicker">{title}</p>
        {meta ? <span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{meta}</span> : null}
      </div>
      {children}
    </div>
  );
}

export function markerToneClasses(tone: ChartMarker["tone"]) {
  if (tone === "good") {
    return "border-emerald-500/20 bg-emerald-500/15 text-emerald-200";
  }
  if (tone === "warn") {
    return "border-amber-500/20 bg-amber-500/15 text-amber-100";
  }
  if (tone === "danger") {
    return "border-rose-500/20 bg-rose-500/15 text-rose-200";
  }
  return "border-cyan-500/20 bg-cyan-500/15 text-cyan-200";
}

export function ReviewDrawer({
  open,
  onClose,
  symbol,
  structure,
  focusedStructure,
  structureFocusSource,
  focusedStructureEventTitle,
  onFocusStructure,
  latestScan,
  conceptRuntime,
  compareSummary,
  stage7Summary,
  stageStatus,
  conceptEvents,
  executionActions,
  timeline,
  allowedSessions,
  outsideSessionAllowed,
}: {
  open: boolean;
  onClose: () => void;
  symbol: string;
  structure: IctStructurePayload | null;
  focusedStructure: StructureFocus | null;
  structureFocusSource: "lens" | "event" | "none";
  focusedStructureEventTitle: string | null;
  onFocusStructure: (focus: StructureFocus) => void;
  latestScan: ScanHistoryItem | null;
  conceptRuntime: ConceptRuntimeItem | null;
  compareSummary: ConceptRevisionCompareSummary | null;
  stage7Summary: ConceptStage7DecisionSummary | null;
  stageStatus: ConceptStageStatusSummary | null;
  conceptEvents: EventItem[];
  executionActions: ExecutionActionItem[];
  timeline: ControlRoomTimelineItem[];
  allowedSessions: string[];
  outsideSessionAllowed: boolean;
}) {
  useEffect(() => {
    if (!open) {
      return undefined;
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, open]);

  if (!open) {
    return null;
  }

  const availableStructureFocuses = [
    {
      id: "sweep" as const,
      label: "4H Liquidity",
      enabled: Boolean(
        structure &&
          (structure.liquidity_event.state !== "none" || structure.drt.state === "ready" || structure.sweep.state !== "none"),
      ),
    },
    { id: "mss" as const, label: "15m MSS", enabled: Boolean(structure && structure.mss.state !== "none") },
    {
      id: "fvg" as const,
      label: "5m PD Array",
      enabled: Boolean(structure && (structure.pd_array.name || structure.fvg.state !== "none")),
    },
    {
      id: "displacement" as const,
      label: "Displacement",
      enabled: Boolean(structure && structure.displacement.state !== "none"),
    },
    { id: "levels" as const, label: "Execution Plan", enabled: Boolean(structure && structure.levels.ok) },
  ];
  const activeStructureFocus =
    (focusedStructure && availableStructureFocuses.find((item) => item.id === focusedStructure && item.enabled)?.id) ??
    availableStructureFocuses.find((item) => item.enabled)?.id ??
    null;

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-[#04070cbf]"
      role="presentation"
      onClick={onClose}
    >
      <div
        className="flex h-full w-full max-w-[520px] flex-col border-l border-slate-800 bg-[#081018]"
        role="dialog"
        aria-modal="true"
        aria-label={`${symbol} review deck`}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-4">
          <div>
            <p className="terminal-kicker">Review Deck</p>
            <h3 className="mt-1 font-display text-2xl text-slate-100">{symbol}</h3>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <TerminalBadge
                label={String(readConceptField(conceptRuntime, "recommendation") ?? "awaiting runtime")}
                status={verdictBadgeStatus(String(readConceptField(conceptRuntime, "recommendation") ?? ""))}
              />
              <TerminalBadge
                label={String(readConceptField(conceptRuntime, "operator_signal") ?? "no operator signal")}
                status={verdictBadgeStatus(String(readConceptField(conceptRuntime, "overall") ?? ""))}
              />
              <TerminalBadge
                label={`candidate ${formatRatioPercent(readConceptField(conceptRuntime, "candidate_ratio"))}`}
                status="neutral"
              />
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-slate-700 bg-[#09111a] px-3 py-2 font-mono text-[11px] uppercase tracking-[0.16em] text-slate-300 transition hover:border-slate-600"
          >
            Close
          </button>
        </div>

        <div className="flex-1 space-y-4 overflow-auto px-5 py-4">
          <section className="terminal-panel p-4">
            <PanelHeader
              title="ICT Structure Review"
              icon={<Radar size={14} strokeWidth={1.8} />}
              meta={structure?.updated_at ? formatRelativeTime(structure.updated_at) : "awaiting structure"}
            />
            {structure ? (
              <div>
                {structureFocusSource !== "none" ? (
                  <div className="mb-3 terminal-subpanel p-3 text-sm text-slate-400">
                    {structureFocusSource === "lens"
                      ? "Following the active ICT structure lens from the chart."
                      : `Following the focused event: ${focusedStructureEventTitle ?? "linked event"}.`}
                  </div>
                ) : null}
                <div className="flex flex-wrap items-center gap-2">
                  {availableStructureFocuses.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      disabled={!item.enabled}
                      onClick={() => item.enabled && onFocusStructure(item.id)}
                      className={`rounded-full border px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] transition ${
                        activeStructureFocus === item.id
                          ? "border-cyan-400/30 bg-cyan-400/10 text-cyan-200"
                          : item.enabled
                            ? "border-slate-700 bg-[#09111a] text-slate-400 hover:border-slate-600 hover:text-slate-200"
                            : "border-slate-800 bg-[#071019] text-slate-600"
                      }`}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>

                <div className="mt-3">
                  {activeStructureFocus === "sweep" ? (
                    <div>
                      <DetailRow label="drt" value={structure.drt.state || "-"} />
                      <DetailRow label="location" value={structure.drt.location || structure.bias.location || "-"} />
                      <DetailRow label="objective" value={cleanLabel(structure.drt.open_objective || structure.liquidity_draw || "unclear")} />
                      <DetailRow label="event" value={cleanLabel(structure.liquidity_event.state || structure.sweep.state || "-")} />
                      <DetailRow label="level" value={formatPrice(structure.liquidity_event.level ?? structure.sweep.level)} />
                      <DetailRow label="narrative" value={cleanLabel(structure.liquidity_event.narrative_hint || structure.narrative.state || "-")} />
                      <DetailRow label="defended" value={cleanLabel(structure.liquidity_event.defended_side || "-")} />
                      <DetailRow label="timestamp" value={structure.liquidity_event.at || structure.sweep.at || "-"} />
                    </div>
                  ) : null}

                  {activeStructureFocus === "mss" ? (
                    <div>
                      <DetailRow label="state" value={structure.mss.state || "-"} />
                      <DetailRow label="timeframe" value="15m" />
                      <DetailRow label="level" value={formatPrice(structure.mss.level)} />
                      <DetailRow label="broken swing" value={structure.mss.broken_swing_at || structure.mss.at || "-"} />
                      <DetailRow label="tolerance" value={formatPrice(structure.mss.tolerance)} />
                      <DetailRow label="micro break" value={structure.mss.micro_break ? "yes" : "no"} />
                    </div>
                  ) : null}

                  {activeStructureFocus === "fvg" ? (
                    <div>
                      <DetailRow label="array" value={structure.pd_array.name || cleanLabel(structure.fvg.state || "-")} />
                      <DetailRow label="respect" value={cleanLabel(structure.pd_array.respect_state || structure.narrative.array_support || "-")} />
                      <DetailRow label="location" value={cleanLabel(structure.pd_array.location || "-")} />
                      <DetailRow label="relation" value={cleanLabel(structure.pd_array.range_relation || "-")} />
                      <DetailRow label="lower" value={formatPrice(structure.fvg.lower)} />
                      <DetailRow label="upper" value={formatPrice(structure.fvg.upper)} />
                      <DetailRow label="midpoint" value={formatPrice(structure.fvg.midpoint)} />
                      <DetailRow label="ifvg" value={structure.pd_array.ifvg_candidate ? "candidate" : "no"} />
                      <DetailRow label="timestamp" value={structure.fvg.at || "-"} />
                    </div>
                  ) : null}

                  {activeStructureFocus === "displacement" ? (
                    <div>
                      <DetailRow label="state" value={structure.displacement.state || "-"} />
                      <DetailRow label="mode" value={structure.displacement.mode || "-"} />
                      <DetailRow label="range x" value={formatPrice(structure.displacement.range_multiple)} />
                      <DetailRow label="body x" value={formatPrice(structure.displacement.body_multiple)} />
                      <DetailRow label="timestamp" value={structure.displacement.at || "-"} />
                    </div>
                  ) : null}

                  {activeStructureFocus === "levels" ? (
                    <div>
                      <DetailRow label="entry" value={formatPrice(structure.levels.entry_price)} />
                      <DetailRow label="stop" value={formatPrice(structure.levels.stop_loss)} />
                      <DetailRow label="target" value={formatPrice(structure.levels.take_profit)} />
                      <DetailRow label="rr" value={formatPrice(structure.levels.rr_multiple)} />
                      <DetailRow label="target src" value={structure.levels.target_source || "-"} />
                    </div>
                  ) : null}
                </div>

                <div className="mt-3 terminal-subpanel p-3 text-sm text-slate-400">
                  {activeStructureFocus === "sweep"
                    ? structure.liquidity_event.reason ||
                      "This is the 4H dealing-range and liquidity event read. Bias and narrative should come from where liquidity was raided and how price responded inside the range."
                    : activeStructureFocus === "mss"
                      ? "This is the 15m structural confirmation. It should express the 4H liquidity narrative before we accept any 5m execution detail."
                      : activeStructureFocus === "fvg"
                        ? "This is the active 5m execution array. Location inside the dealing range and respect versus disrespect matter more than the label alone."
                        : activeStructureFocus === "displacement"
                          ? "This is the 5m impulse leg that should form off the 15m MSS. If the displacement is weak, the execution layer should stay invalid."
                          : activeStructureFocus === "levels"
                            ? structure.levels.error || "These are the current derived execution levels from the structure stack."
                            : "No active ICT structure is available for this symbol yet."}
                </div>
              </div>
            ) : (
              <p className="text-sm text-slate-500">No compact ICT structure payload is available for this market yet.</p>
            )}
          </section>

          <section className="terminal-panel p-4">
            <PanelHeader title="Latest Scan Truth" icon={<FileSearch size={14} strokeWidth={1.8} />} meta={latestScan ? formatTimestamp(latestScan.created_at) : "no scan"} />
            {latestScan ? (
              <div>
                <DetailRow label="decision" value={latestScan.decision || "-"} />
                <DetailRow label="session" value={formatSessionDisplayLabel(latestScan.session || "-", allowedSessions, "-")} />
                <DetailRow label="direction" value={latestScan.direction || "not aligned"} />
                <DetailRow label="candidate" value={latestScan.candidate_logged ? "logged" : "not logged"} />
                <DetailRow label="duplicate" value={latestScan.duplicate_candidate ? "yes" : "no"} />
                <DetailRow label="signature" value={latestScan.scan_signature || "-"} />
              </div>
            ) : (
              <p className="text-sm text-slate-500">No recent scan truth is available for this market yet.</p>
            )}
          </section>

          <section className="terminal-panel p-4">
            <PanelHeader title="Concept Blockers" icon={<BrainCircuit size={14} strokeWidth={1.8} />} meta={conceptRuntime ? formatRelativeTime(conceptRuntime.updated_at) : "awaiting runtime"} />
            <div>
              <DetailRow label="overall" value={String(readConceptField(conceptRuntime, "overall") ?? "-")} />
              <DetailRow label="verdict" value={String(readConceptField(conceptRuntime, "recommendation") ?? "-")} />
              <DetailRow label="operator" value={String(readConceptField(conceptRuntime, "operator_signal") ?? "-")} />
              <DetailRow label="candidate %" value={formatRatioPercent(readConceptField(conceptRuntime, "candidate_ratio"))} />
              <DetailRow label="dominant" value={String(readConceptField(conceptRuntime, "dominant_blocker") ?? "-")} />
            </div>
            <div className="mt-3 terminal-subpanel p-3 text-sm text-slate-400">
              {String(
                readConceptField(conceptRuntime, "operator_summary") ??
                  "Concept lab has not published a current operator summary yet.",
              )}
            </div>
              <div className="mt-3 space-y-2">
                {conceptEvents.slice(0, 4).map((event) => (
                  <div key={event.event_id} className="terminal-subpanel px-3 py-2">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="font-mono text-[12px] text-slate-100">{formatSessionAwareCopy(event.summary, outsideSessionAllowed)}</p>
                        <p className="mt-1 text-[10px] uppercase tracking-[0.16em] text-slate-500">
                          {cleanLabel(event.event_type)}
                        </p>
                      </div>
                      <span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{formatRelativeTime(event.created_at)}</span>
                    </div>
                  </div>
                ))}
            </div>
          </section>

          <RevisionLeaderSummary compareSummary={compareSummary} />
          <StageStatusSummary stageStatus={stageStatus} />
          <Stage7DecisionSummary stage7Summary={stage7Summary} />

          <section className="terminal-panel p-4">
            <PanelHeader title="Exchange Action History" icon={<Activity size={14} strokeWidth={1.8} />} meta={`${executionActions.length} rows`} />
            {executionActions.length > 0 ? (
              <div className="space-y-2">
                {executionActions.map((item) => (
                  <div key={item.action_id} className="terminal-subpanel px-3 py-2">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <span className={`inline-flex rounded-full border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] ${markerToneClasses(item.status === "action_applied" ? "good" : item.status === "action_failed" ? "danger" : "warn")}`}>
                            {item.action_type}
                          </span>
                          <span className="font-mono text-[12px] text-slate-100">{item.status}</span>
                        </div>
                        <p className="mt-1 text-[11px] text-slate-500">
                          {item.proposal_id} · {item.venue}
                        </p>
                        {item.order_id || item.order_link_id ? (
                          <p className="mt-1 text-[11px] text-slate-600">
                            {item.order_id ? `order ${item.order_id}` : item.order_link_id}
                          </p>
                        ) : null}
                      </div>
                      <span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{formatTimestamp(item.created_at)}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-slate-500">No exchange action history exists for this market in the current sample.</p>
            )}
          </section>

          <section className="terminal-panel p-4">
            <PanelHeader title="Lifecycle Markers" icon={<Radar size={14} strokeWidth={1.8} />} meta={`${timeline.length} tape rows`} />
            {timeline.length > 0 ? (
              <div className="space-y-2">
                {timeline.slice(0, 8).map((item) => (
                  <div key={item.id} className="terminal-subpanel px-3 py-2">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="font-mono text-[12px] text-slate-100">{item.title}</p>
                        <p className="mt-1 text-[11px] text-slate-500">{formatSessionAwareCopy(item.summary, outsideSessionAllowed)}</p>
                      </div>
                      <span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{formatRelativeTime(item.created_at)}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-slate-500">No recent lifecycle tape is available for this market.</p>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

export function deriveConceptPosture(scans: ScanHistoryItem[], proposals: ProposalItem[], executionState: ExecutionStateItem[]) {
  const candidateCount = scans.filter((item) => isExecutionEligibleDecision(item.decision)).length;
  if (candidateCount > 0) {
    return { label: "arming", status: "good" as const, note: `${candidateCount} candidate scans in window` };
  }
  if (proposals.length > 0 || executionState.length > 0) {
    return { label: "observing", status: "warn" as const, note: "Evidence exists, current sample still dry" };
  }
  return { label: "collecting", status: "neutral" as const, note: "Waiting for executable alignment" };
}

export function readConceptField(runtime: ConceptRuntimeItem | null, field: string) {
  if (!runtime) {
    return null;
  }

  const summaryValue = runtime.last_summary[field];
  if (summaryValue !== undefined && summaryValue !== null && summaryValue !== "") {
    return summaryValue;
  }

  const stateValue = runtime.state[field];
  if (stateValue !== undefined && stateValue !== null && stateValue !== "") {
    return stateValue;
  }

  return null;
}

export function deriveWorkflow(
  args: {
    stackHealth: string;
    sessionValid: boolean;
    sessionLabel: string;
    allowedSessions: string[];
    conceptRecommendation: string;
    latestScan: ScanHistoryItem | null;
    currentProposal: ProposalItem | null;
    activeExecution: ExecutionStateItem | null;
    lastExecution: ExecutionStateItem | null;
    globalPaused: boolean;
  },
) {
  const steps: WorkflowStep[] = [];

  if (args.globalPaused) {
    steps.push({
      id: "harness",
      title: "Harness Control",
      status: "blocked",
      detail: "Global kill switch is engaged. Release it before trusting the live flow.",
    });
  } else if (args.stackHealth === "error") {
    steps.push({
      id: "harness",
      title: "Harness Control",
      status: "blocked",
      detail: "One or more stack components are unhealthy. Stabilize the daemon before acting.",
    });
  } else if (args.stackHealth === "warning") {
    steps.push({
      id: "harness",
      title: "Harness Control",
      status: "active",
      detail: "The stack is in watch mode. Data is usable, but treat actions cautiously.",
    });
  } else {
    steps.push({
      id: "harness",
      title: "Harness Control",
      status: "complete",
      detail: "The live daemon stack is healthy and publishing current state.",
    });
  }

  steps.push(
    args.sessionValid
      ? {
          id: "session",
          title: "Session Gate",
          status: "complete",
          detail:
            normalizeSessionKey(args.sessionLabel) === "outside" && isOutsideSessionAllowed(args.allowedSessions)
              ? "Outside session is allowed for this run."
              : `The market is inside the ${formatSessionDisplayLabel(args.sessionLabel, args.allowedSessions)} session window.`,
        }
      : {
          id: "session",
          title: "Session Gate",
          status: "waiting",
          detail: "The market is currently outside the allowed session windows for Concept 1.",
        },
  );

  if (isExecutionEligibleDecision(args.latestScan?.decision)) {
    steps.push({
      id: "concept",
      title: "Concept Alignment",
      status: "active",
      detail: "The latest scan found an executable concept candidate for this market.",
    });
  } else if (args.conceptRecommendation === "fix_harness") {
    steps.push({
      id: "concept",
      title: "Concept Alignment",
      status: "blocked",
      detail: "The concept lab is blocked by harness trust issues and should not be judged yet.",
    });
  } else {
    steps.push({
      id: "concept",
      title: "Concept Alignment",
      status: "waiting",
      detail: "The current sample is not meeting executable Concept 1 alignment yet.",
    });
  }

  if (args.currentProposal?.status === "ready_for_submission") {
    steps.push({
      id: "proposal",
      title: "Proposal Desk",
      status: "active",
      detail: `${args.currentProposal.proposal_id} is ready for submission review.`,
    });
  } else if (args.currentProposal?.status === "submitted_testnet") {
    steps.push({
      id: "proposal",
      title: "Proposal Desk",
      status: "complete",
      detail: `${args.currentProposal.proposal_id} has already been submitted to the exchange.`,
    });
  } else {
    steps.push({
      id: "proposal",
      title: "Proposal Desk",
      status: "waiting",
      detail: "No active proposal is waiting on the desk right now.",
    });
  }

  if (args.activeExecution) {
    steps.push({
      id: "execution",
      title: "Execution Lifecycle",
      status: "active",
      detail: `${args.activeExecution.symbol} is ${cleanLabel(args.activeExecution.sync_status)} on the exchange.`,
    });
  } else if (args.lastExecution) {
    steps.push({
      id: "execution",
      title: "Execution Lifecycle",
      status: "complete",
      detail: `Latest execution lifecycle ended as ${cleanLabel(args.lastExecution.sync_status)}.`,
    });
  } else {
    steps.push({
      id: "execution",
      title: "Execution Lifecycle",
      status: "waiting",
      detail: "No live working order or open position exists yet for this symbol.",
    });
  }

  let nextAction = "Keep the daemon running and continue observing the current sample.";
  const firstBlocked = steps.find((step) => step.status === "blocked");
  const firstActive = steps.find((step) => step.status === "active");
  const firstWaiting = steps.find((step) => step.status === "waiting");

  if (firstBlocked?.id === "harness") {
    nextAction = "Clear the harness issue first. Release paused controls or recover unhealthy daemons before acting.";
  } else if (firstWaiting?.id === "session") {
    nextAction = "Wait for the next allowed session window so Concept 1 can be judged in its intended market conditions.";
  } else if (firstActive?.id === "proposal") {
    nextAction = "Review the ready proposal and submit it from the operator desk when you want to test the live path.";
  } else if (firstActive?.id === "execution") {
    nextAction = "Monitor the live execution state and use sync/cancel controls as the exchange state changes.";
  } else if (firstWaiting?.id === "concept") {
    nextAction = "Let the daemon keep sampling until the market meets the executable house rules again.";
  } else if (firstWaiting?.id === "proposal") {
    nextAction = "Stay in observation mode. The concept is not generating a current operator-ready proposal yet.";
  }

  return { steps, nextAction };
}

export function deriveChartMarkers(timeline: ControlRoomTimelineItem[]): ChartMarker[] {
  const markers: ChartMarker[] = [];

  for (const item of timeline) {
    if (item.kind === "execution_action") {
      const normalized = cleanLabel(item.event_type).toUpperCase();
      markers.push({
        id: item.id,
        at: item.created_at,
        label: normalized.includes("CANCEL") ? "CANCEL" : normalized,
        tone: item.severity === "warning" ? "danger" : "warn",
        detail: item.summary,
      });
      continue;
    }

    if (item.kind === "execution_state") {
      const status = item.event_type.toLowerCase();
      let label = status.toUpperCase();
      let tone: ChartMarker["tone"] = "neutral";

      if (status === "submitted" || status === "working") {
        label = "WORKING";
        tone = "warn";
      } else if (status === "filled" || status === "position_open" || status === "partially_filled") {
        label = "FILL";
        tone = "good";
      } else if (status === "cancelled" || status === "rejected" || status === "failed") {
        label = status.toUpperCase();
        tone = "danger";
      }

      markers.push({
        id: item.id,
        at: item.created_at,
        label,
        tone,
        detail: item.summary,
      });
      continue;
    }

    if (item.kind === "proposal" && item.event_type === "submitted_testnet") {
      markers.push({
        id: item.id,
        at: item.created_at,
        label: "SUBMIT",
        tone: "good",
        detail: item.summary,
      });
    }
  }

  return markers.slice(0, 8);
}
