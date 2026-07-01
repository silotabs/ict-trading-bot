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
import { TerminalChart } from "./components/TerminalChart";
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
  type ProposalItem,
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
} from "./lib/api";
import { ACTIVE_SYNC_STATUSES, TERMINAL_SYNC_STATUSES, SAVED_OPERATOR_SCENES_STORAGE_KEY, CHART_TIMEFRAME_OPTIONS, SESSION_BOARD_SPECS, formatTimestamp, formatRelativeTime, formatPrice, formatPercent, formatRatioPercent, cleanLabel, normalizeSessionKey, isSessionAllowedInConfig, isOutsideSessionAllowed, formatSessionDisplayLabel, formatSessionAwareCopy, formatBlockerClassLabel, formatOperatorStatusLabel, rawStatusTitle, findPublicEventStreamComponent, publicEventStreamDetails, publicEventStreamBadgeStatus, isExecutionEligibleDecision, asRecord, asRecordList, revisionStatusBadgeStatus, revisionCompareVerdictBadgeStatus, stageGateBadgeStatus, acceptanceStatusBadgeStatus, readinessBadgeStatus, executionIntentBadgeStatus, riskCheckBadgeStatus, acceptanceVerdictBadgeStatus, stage7StatusBadgeStatus, stage7VerdictBadgeStatus, stageStatusBadgeStatus, formatZoneTime, formatZoneTimeLabel, getZoneClockParts, formatMinutesWindow, buildSessionBoardState, structureProgressState, badgeClasses, timelineAccentClasses, classifyTimelineItem, groupTimelineItems, normalizeSignalText, structureFocusConfig, shouldIgnoreShortcutTarget, inferStructureFocusFromEvent, filterStructureFocusedTimelineItems, scoreGroupedTimelineItems, severityChipClasses, verdictBadgeStatus, streamBadgeState, TerminalBadge, ClockTile, SessionWindowCard, ActionButton, PanelHeader, ProgressMeter, FooterStripItem, ShortcutHint, WorkspaceTabButton, OperatorSceneCard, loadSavedOperatorScenes, normalizeSavedOperatorScenes, CommandPalette, AnalysisRow, RevisionLeaderSummary, AcceptanceStatusSummary, Stage7DecisionSummary, StageStatusSummary, RuleStack, RevisionLoopPanel, getControlRecord, upsertControlRecord, isControlItem, ScanFeed, TimelineFeed, EventConsole, ExecutionTable, FocusedInspectionRail, workflowStatusClasses, WorkflowRunbook, DetailRow, RuntimeSurfaceCard, markerToneClasses, ReviewDrawer, deriveConceptPosture, readConceptField, deriveWorkflow, deriveChartMarkers } from "./dashboard/app-support";
import type { StreamState, WorkflowStatus, StructureFocus, WorkspaceTab, RightRailTab, EventConsoleFilter, EventConsoleSeverityFilter, EventConsolePreset, EventConsoleScope, ChartTimeframe, GroupedTimelineItem, ScoredGroupedTimelineItem, ActionState, WorkflowStep, CommandPaletteAction, SavedOperatorSceneState, SavedOperatorScene, OperatorScene, ChartMarker, SessionBoardSpec, SessionBoardState, RuntimeRevisionResult, RuntimeLinkedRevision } from "./dashboard/app-support";

export default function App() {
  const defaultSceneHydratedRef = useRef(false);
  const sceneImportInputRef = useRef<HTMLInputElement | null>(null);
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [clockNow, setClockNow] = useState(() => new Date());
  const [selectedSymbol, setSelectedSymbol] = useState("BTCUSDT");
  const [selectedTimeframe, setSelectedTimeframe] = useState<ChartTimeframe>("5m");
  const [candles, setCandles] = useState<Candle[]>([]);
  const [chartError, setChartError] = useState<string | null>(null);
  const [streamState, setStreamState] = useState<StreamState>("connecting");
  const [lastStreamAt, setLastStreamAt] = useState<string | null>(null);
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const [latestSignalTraces, setLatestSignalTraces] = useState<SignalTraceItem[]>([]);
  const [latestExecutionIntents, setLatestExecutionIntents] = useState<ExecutionIntentItem[]>([]);
  const [latestExecutionRiskChecks, setLatestExecutionRiskChecks] = useState<ExecutionRiskCheckItem[]>([]);
  const [shadowReviewSummary, setShadowReviewSummary] = useState<ShadowReviewSummary | null>(null);
  const [reviewDrawerOpen, setReviewDrawerOpen] = useState(false);
  const [eventConsoleFilter, setEventConsoleFilter] = useState<EventConsoleFilter>("all");
  const [eventConsolePreset, setEventConsolePreset] = useState<EventConsolePreset>("custom");
  const [eventConsoleSeverityFilter, setEventConsoleSeverityFilter] =
    useState<EventConsoleSeverityFilter>("all");
  const [eventConsoleScope, setEventConsoleScope] = useState<EventConsoleScope>("selected");
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>("console");
  const [rightRailTab, setRightRailTab] = useState<RightRailTab>("intelligence");
  const [workspaceDockExpanded, setWorkspaceDockExpanded] = useState(false);
  const [followFocusedEvent, setFollowFocusedEvent] = useState(true);
  const [selectedTimelineEventId, setSelectedTimelineEventId] = useState<string | null>(null);
  const [selectedStructureFocus, setSelectedStructureFocus] = useState<StructureFocus | null>(null);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [commandPaletteQuery, setCommandPaletteQuery] = useState("");
  const [commandPaletteIndex, setCommandPaletteIndex] = useState(0);
  const [savedOperatorScenes, setSavedOperatorScenes] = useState<SavedOperatorScene[]>(() => loadSavedOperatorScenes());
  const [actionState, setActionState] = useState<ActionState>({
    status: "idle",
    message: null,
    actionKey: null,
  });

  const refreshSnapshot = async (signal?: AbortSignal, apply = true) => {
    const nextSnapshot = await fetchDashboardSnapshot(signal);
    if (apply) {
      setSnapshot(nextSnapshot);
      setLastStreamAt(nextSnapshot.built_at);
      setError(null);
      setLoading(false);
    }
    return nextSnapshot;
  };

  const runAction = async (
    actionKey: string,
    successMessage: string,
    runner: () => Promise<ControlItem | Record<string, unknown>>,
  ) => {
    setActionState({
      status: "pending",
      message: null,
      actionKey,
    });

    try {
      const result = await runner();
      if (isControlItem(result)) {
        setSnapshot((current) => upsertControlRecord(current, result));
      }
      await refreshSnapshot();
      setActionState({
        status: "success",
        message: successMessage,
        actionKey,
      });
    } catch (actionError) {
      setActionState({
        status: "error",
        message: actionError instanceof Error ? actionError.message : "Action failed",
        actionKey,
      });
    }
  };

  useEffect(() => {
    let active = true;

    const load = async () => {
      const controller = new AbortController();
      try {
        const nextSnapshot = await refreshSnapshot(controller.signal, false);
        if (!active) {
          return;
        }
        setSnapshot(nextSnapshot);
        setLastStreamAt(nextSnapshot.built_at);
        setError(null);
        setLoading(false);
      } catch (loadError) {
        if (!active) {
          return;
        }
        setError(loadError instanceof Error ? loadError.message : "Failed to load dashboard");
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    };

    void load();
    const interval = window.setInterval(() => {
      void load();
    }, 60000);

    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    const unsubscribe = subscribeControlRoom({
      onOpen: () => {
        setStreamState("live");
      },
      onSnapshot: (nextSnapshot) => {
        setSnapshot(nextSnapshot);
        setLastStreamAt(nextSnapshot.built_at);
        setError(null);
        setLoading(false);
        setStreamState("live");
      },
      onError: () => {
        setStreamState((current) => (current === "live" ? "delayed" : "connecting"));
      },
    });

    return () => {
      unsubscribe();
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    window.localStorage.setItem(
      SAVED_OPERATOR_SCENES_STORAGE_KEY,
      JSON.stringify(normalizeSavedOperatorScenes(savedOperatorScenes)),
    );
  }, [savedOperatorScenes]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      if (!lastStreamAt) {
        return;
      }

      const ageMs = Date.now() - new Date(lastStreamAt).getTime();
      if (ageMs > 18000) {
        setStreamState("delayed");
      }
    }, 4000);

    return () => {
      window.clearInterval(interval);
    };
  }, [lastStreamAt]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      setClockNow(new Date());
    }, 1000);

    return () => {
      window.clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    let mounted = true;
    const controller = new AbortController();
    const chartTimeframe =
      CHART_TIMEFRAME_OPTIONS.find((option) => option.value === selectedTimeframe) ?? CHART_TIMEFRAME_OPTIONS[2];

    const loadChart = async () => {
      try {
        const payload = await fetchKlines(selectedSymbol, {
          interval: chartTimeframe.value,
          limit: chartTimeframe.limit,
          signal: controller.signal,
        });
        if (!mounted) {
          return;
        }
        setCandles(payload.candles);
        setChartError(null);
      } catch (loadError) {
        if (!mounted) {
          return;
        }
        setChartError(loadError instanceof Error ? loadError.message : "Failed to load chart");
      }
    };

    void loadChart();
    const interval = window.setInterval(() => {
      void loadChart();
    }, 25000);

    return () => {
      mounted = false;
      controller.abort();
      window.clearInterval(interval);
    };
  }, [selectedSymbol, selectedTimeframe]);

  useEffect(() => {
    let mounted = true;
    const controller = new AbortController();

    const loadOperatorSurfaces = async () => {
      try {
        const [nextReadiness, tracesResponse, intentsResponse, riskChecksResponse, nextShadowSummary] =
          await Promise.all([
            fetchReadiness(controller.signal),
            fetchSignalTraces({ signal: controller.signal, symbol: selectedSymbol, limit: 4 }),
            fetchExecutionIntents({ signal: controller.signal, symbol: selectedSymbol, limit: 4 }),
            fetchExecutionRiskChecks({ signal: controller.signal, symbol: selectedSymbol, limit: 4 }),
            fetchShadowReviewSummary({ signal: controller.signal, limit: 20, cluster_limit: 3 }),
          ]);

        if (!mounted) {
          return;
        }

        setReadiness(nextReadiness);
        setLatestSignalTraces(tracesResponse.items);
        setLatestExecutionIntents(intentsResponse.items);
        setLatestExecutionRiskChecks(riskChecksResponse.items);
        setShadowReviewSummary(nextShadowSummary);
      } catch {
        if (!mounted) {
          return;
        }
      }
    };

    void loadOperatorSurfaces();
    const interval = window.setInterval(() => {
      void loadOperatorSurfaces();
    }, 45000);

    return () => {
      mounted = false;
      controller.abort();
      window.clearInterval(interval);
    };
  }, [selectedSymbol]);

  const scans = snapshot?.scans ?? [];
  const proposals = snapshot?.proposals ?? [];
  const executionState = snapshot?.executionState ?? [];
  const executionActions = snapshot?.executionActions ?? [];
  const timeline = snapshot?.timeline ?? [];
  const tickers = snapshot?.tickers ?? [];
  const tickerErrors = snapshot?.ticker_errors ?? [];
  const ictStructures = snapshot?.ictStructures ?? {};
  const rules = snapshot?.rules;
  const operations = snapshot?.operations;
  const conceptRuntime = snapshot?.conceptRuntime ?? null;
  const conceptEvents = snapshot?.conceptEvents ?? [];
  const conceptReviews = snapshot?.conceptReviews ?? [];
  const conceptRevisions = snapshot?.conceptRevisions ?? [];
  const conceptRevisionCompare = snapshot?.conceptRevisionCompare ?? null;
  const conceptAcceptance = snapshot?.conceptAcceptance ?? null;
  const conceptAcceptanceHistory = snapshot?.conceptAcceptanceHistory ?? [];
  const conceptStage7Decision = snapshot?.conceptStage7Decision ?? null;
  const conceptStageStatus = snapshot?.conceptStageStatus ?? null;
  const conceptRuntimeState = conceptRuntime?.state ?? {};
  const conceptRuntimeSummary = conceptRuntime?.last_summary ?? {};
  const revisionActivity = asRecord(
    conceptRuntimeState.revision_activity ?? conceptRuntimeSummary.revision_activity,
  );
  const lastRevisionResults = asRecordList<RuntimeRevisionResult>(conceptRuntimeState.last_revision_results);
  const lastLinkedRevisions = asRecordList<RuntimeLinkedRevision>(conceptRuntimeState.last_linked_revisions);
  const recentRevisionLinkEvents = conceptEvents.filter((item) => item.event_type === "revision_linked");

  const selectedScans = scans.filter((item) => item.instrument === selectedSymbol);
  const latestScan = selectedScans[0] ?? null;
  const invalidatedProposalIds = new Set(
    executionState.filter((item) => TERMINAL_SYNC_STATUSES.has(item.sync_status)).map((item) => item.proposal_id),
  );
  const activeExecution =
    executionState.find((item) => item.symbol === selectedSymbol && ACTIVE_SYNC_STATUSES.has(item.sync_status)) ?? null;
  const lastExecution = executionState.find((item) => item.symbol === selectedSymbol) ?? null;
  const activeProposal =
    proposals.find(
      (item) =>
        item.symbol === selectedSymbol &&
        !invalidatedProposalIds.has(item.proposal_id) &&
        (item.status === "ready_for_submission" || item.status === "submitted_testnet"),
    ) ?? null;
  const currentProposal =
    (activeExecution
      ? proposals.find((item) => item.proposal_id === activeExecution.proposal_id) ?? activeProposal
      : activeProposal) ?? null;

  const tickersBySymbol = useMemo(
    () => Object.fromEntries(tickers.map((item) => [item.instrument, item])),
    [tickers],
  ) as Record<string, TickerPayload | undefined>;

  const selectedTicker = tickersBySymbol[selectedSymbol] ?? tickers[0] ?? null;
  const selectedIctStructure = ictStructures[selectedSymbol] ?? null;
  const localTimeZone = useMemo(
    () => Intl.DateTimeFormat().resolvedOptions().timeZone || "Local",
    [],
  );
  const tradingClocks = useMemo(
    () => [
      {
        id: "local",
        label: "Local Time",
        value: formatZoneTime(clockNow, localTimeZone),
        meta: localTimeZone,
      },
      {
        id: "london",
        label: "London",
        value: formatZoneTime(clockNow, "Europe/London"),
        meta: "Europe/London",
      },
      {
        id: "new-york",
        label: "New York",
        value: formatZoneTime(clockNow, "America/New_York"),
        meta: "America/New_York",
      },
    ],
    [clockNow, localTimeZone],
  );
  const sessionBoard = useMemo(
    () =>
      SESSION_BOARD_SPECS.map((spec) =>
        buildSessionBoardState(
          clockNow,
          spec,
          rules?.allowed_sessions ?? [],
          snapshot?.session_context.active_session ?? "outside",
        ),
      ),
    [clockNow, rules?.allowed_sessions, snapshot?.session_context.active_session],
  );
  const rightRailTabs: Array<{ id: RightRailTab; label: string; meta: string; icon: ReactNode }> = [
    { id: "intelligence", label: "Intel", meta: "concept state and blockers", icon: <BrainCircuit size={12} strokeWidth={1.8} /> },
    { id: "revision", label: "Revision", meta: "ranked revision loop", icon: <GitBranch size={12} strokeWidth={1.8} /> },
    { id: "desk", label: "Desk", meta: "posture and controls", icon: <SlidersHorizontal size={12} strokeWidth={1.8} /> },
  ];
  const keyboardStructureShortcuts = useMemo(
    () => [
      {
        key: "1",
        focus: "sweep" as const,
        label: "4H Liq",
        enabled: Boolean(
          selectedIctStructure &&
            (selectedIctStructure.liquidity_event.state !== "none" || selectedIctStructure.drt.state === "ready"),
        ),
      },
      {
        key: "2",
        focus: "mss" as const,
        label: "15m MSS",
        enabled: Boolean(selectedIctStructure && selectedIctStructure.mss.state !== "none"),
      },
      {
        key: "3",
        focus: "fvg" as const,
        label: "PD Array",
        enabled: Boolean(
          selectedIctStructure &&
            (Boolean(selectedIctStructure.pd_array.name) || selectedIctStructure.fvg.state !== "none"),
        ),
      },
      {
        key: "4",
        focus: "displacement" as const,
        label: "Displacement",
        enabled: Boolean(selectedIctStructure && selectedIctStructure.displacement.state !== "none"),
      },
      {
        key: "5",
        focus: "levels" as const,
        label: "Plan",
        enabled: Boolean(selectedIctStructure && selectedIctStructure.levels.ok),
      },
    ],
    [selectedIctStructure],
  );
  const openExecutionRows = executionState.filter((item) => Number(item.position_size ?? "0") > 0);
  const conceptPosture = deriveConceptPosture(scans, proposals, executionState);
  const stackHealth = operations?.overall.health ?? "unknown";
  const streamBadge = streamBadgeState(streamState);
  const allowedSessions = rules?.allowed_sessions ?? [];
  const outsideSessionAllowed = isOutsideSessionAllowed(allowedSessions);
  const activeSessionLabel = formatSessionDisplayLabel(snapshot?.session_context.active_session, allowedSessions);
  const latestVisibleSessionLabel = formatSessionDisplayLabel(
    latestScan?.session || snapshot?.session_context.active_session || "unknown",
    allowedSessions,
    "unknown",
  );
  const conceptOverall = String(readConceptField(conceptRuntime, "overall") ?? conceptPosture.label);
  const conceptRecommendation = String(readConceptField(conceptRuntime, "recommendation") ?? "continue_concept_testing");
  const operatorSignal = String(readConceptField(conceptRuntime, "operator_signal") ?? "awaiting_updates");
  const operatorSummary = String(
    readConceptField(conceptRuntime, "operator_summary") ?? "Concept lab is waiting for the next fresh daemon cycle.",
  );
  const dominantBlocker = String(readConceptField(conceptRuntime, "dominant_blocker") ?? "n/a");
  const candidateRatio = formatRatioPercent(readConceptField(conceptRuntime, "candidate_ratio"));
  const selected24hPercent = Number(selectedTicker?.ticker.price24hPcnt ?? NaN);
  const selected24hPositive = Number.isFinite(selected24hPercent) && selected24hPercent >= 0;
  const globalControl = getControlRecord(snapshot, "global");
  const orderSubmissionControl = getControlRecord(snapshot, "order_submission");
  const autoExecutionControl = getControlRecord(snapshot, "auto_execution");
  const tradeManagementControl = getControlRecord(snapshot, "trade_management");
  const latestShadowBlockerCluster = shadowReviewSummary?.blocker_clusters[0] ?? null;
  const readinessOverallHealth =
    readiness?.operations.overall.health ?? operations?.overall.health ?? "unknown";
  const readinessStatus = readiness?.status ?? (readinessOverallHealth === "healthy" ? "healthy_primary" : "not_ready");
  const publicEventStreamComponent = findPublicEventStreamComponent(readiness);
  const publicEventStream = publicEventStreamDetails(publicEventStreamComponent);
  const publicEventStreamStatus = publicEventStreamComponent?.status ?? "missing";
  const publicEventStreamSummary =
    publicEventStreamComponent?.summary ?? "public candle-close event path has not reported yet";
  const publicEventStreamConnection = publicEventStream.connection_status ?? "unknown";
  const publicEventStreamPathState = publicEventStream.event_path_state ?? publicEventStreamStatus;
  const publicEventStreamFallbackActive = Boolean(publicEventStream.fallback_active);
  const operatorStackHealth =
    readinessStatus === "healthy_primary"
      ? "healthy"
      : readinessStatus === "degraded_fallback"
        ? "warning"
        : readinessStatus === "not_ready"
          ? "error"
          : stackHealth;
  const topReadinessBlocker = readiness?.blockers[0] ?? null;
  const latestScanIsExecutionEligible = isExecutionEligibleDecision(latestScan?.decision);
  const sessionBadgeLabel =
    snapshot?.session_context.session_valid
      ? normalizeSessionKey(snapshot?.session_context.active_session) === "outside" && outsideSessionAllowed
        ? "Outside OK"
        : "Session OK"
      : "Session Watch";

  const currentSignal = currentProposal
    ? currentProposal.side.toUpperCase()
    : latestScanIsExecutionEligible
      ? "CANDIDATE"
      : "NO TRADE";

  const currentSignalTone =
    currentSignal === "BUY" || currentSignal === "LONG"
      ? "text-emerald-300"
      : currentSignal === "SELL" || currentSignal === "SHORT"
        ? "text-rose-300"
        : currentSignal === "CANDIDATE"
          ? "text-cyan-300"
          : "text-amber-300";

  const currentTradeState = activeExecution
    ? activeExecution.sync_status
    : latestScanIsExecutionEligible
      ? "candidate"
      : "flat";
  const conceptLabMeters = useMemo(() => {
    const drtState = structureProgressState(selectedIctStructure?.drt.state ?? null);
    const biasState = structureProgressState(selectedIctStructure?.bias.state ?? null);
    const liquidityEventState = structureProgressState(
      selectedIctStructure?.liquidity_event.state ?? selectedIctStructure?.sweep.state ?? null,
    );
    const narrativeState = structureProgressState(selectedIctStructure?.narrative.state ?? null);
    const mssState = structureProgressState(selectedIctStructure?.mss.state ?? null);
    const displacementState = structureProgressState(selectedIctStructure?.displacement.state ?? null);
    const arrayState = structureProgressState(
      selectedIctStructure?.pd_array.respect_state ?? selectedIctStructure?.fvg.state ?? null,
    );
    const alignmentState =
      latestScanIsExecutionEligible
        ? { score: 1, tone: "good" as const, detail: "executable" }
        : selectedIctStructure?.levels.ok
          ? { score: 0.72, tone: "neutral" as const, detail: "plan ready" }
          : structureProgressState(latestScan?.direction ?? "not_aligned");

    return [
      { label: "4H DRT", ...drtState },
      { label: `${rules?.timeframes.bias ?? "4H"} Bias`, ...biasState },
      { label: "4H Liquidity", ...liquidityEventState },
      { label: "Narrative", ...narrativeState },
      { label: "15m MSS", ...mssState },
      { label: "5m Displacement", ...displacementState },
      { label: "5m PD Array", ...arrayState },
      { label: "Alignment", ...alignmentState },
    ];
  }, [latestScan?.direction, latestScanIsExecutionEligible, rules?.timeframes.bias, selectedIctStructure]);
  const eventRelevanceContext = useMemo(
    () => ({
      selectedSymbol,
      currentProposalId: currentProposal?.proposal_id ?? null,
      activeExecutionProposalId: activeExecution?.proposal_id ?? null,
      currentTradeState,
      conceptRecommendation,
      dominantBlocker,
      operatorSignal,
      structureFocus: selectedStructureFocus,
    }),
    [
      activeExecution?.proposal_id,
      conceptRecommendation,
      currentProposal?.proposal_id,
      currentTradeState,
      dominantBlocker,
      operatorSignal,
      selectedStructureFocus,
      selectedSymbol,
    ],
  );
  const selectedTimeline = timeline.filter((item) => !item.symbol || item.symbol === selectedSymbol);
  const consoleTimeline = eventConsoleScope === "global" ? timeline : selectedTimeline;
  const selectedTimelineEvent = timeline.find((item) => item.id === selectedTimelineEventId) ?? null;
  const selectedEventStructureFocus = inferStructureFocusFromEvent(selectedTimelineEvent);
  const effectiveStructureFocus = selectedStructureFocus ?? selectedEventStructureFocus;
  const structureFocusSource: "lens" | "event" | "none" = selectedStructureFocus
    ? "lens"
    : selectedEventStructureFocus
      ? "event"
      : "none";
  const selectedExecutionActions = executionActions.filter((item) => !item.symbol || item.symbol === selectedSymbol);
  const inspectionProposal =
    (selectedTimelineEvent?.proposal_id
      ? proposals.find((item) => item.proposal_id === selectedTimelineEvent.proposal_id) ?? null
      : null) ??
    (selectedTimelineEvent?.symbol ? proposals.find((item) => item.symbol === selectedTimelineEvent.symbol) ?? null : null);
  const inspectionExecution =
    (selectedTimelineEvent?.proposal_id
      ? executionState.find((item) => item.proposal_id === selectedTimelineEvent.proposal_id) ?? null
      : null) ??
    (selectedTimelineEvent?.symbol ? executionState.find((item) => item.symbol === selectedTimelineEvent.symbol) ?? null : null);
  const inspectionAction =
    (selectedTimelineEvent?.proposal_id
      ? executionActions.find((item) => item.proposal_id === selectedTimelineEvent.proposal_id) ?? null
      : null) ??
    (selectedTimelineEvent?.symbol ? executionActions.find((item) => item.symbol === selectedTimelineEvent.symbol) ?? null : null);
  const inspectionAuditTrail = selectedTimelineEvent
    ? timeline
        .filter(
          (item) =>
            item.id !== selectedTimelineEvent.id &&
            ((selectedTimelineEvent.proposal_id && item.proposal_id === selectedTimelineEvent.proposal_id) ||
              (selectedTimelineEvent.symbol && item.symbol === selectedTimelineEvent.symbol)),
        )
        .slice(0, 5)
    : [];
  const inspectionSymbolAuditTrail = selectedTimelineEvent?.symbol
    ? timeline
        .filter((item) => item.id !== selectedTimelineEvent.id && item.symbol === selectedTimelineEvent.symbol)
        .slice(0, 6)
    : [];
  const chartMarkers = deriveChartMarkers(selectedTimeline);
  const workflow = deriveWorkflow({
    stackHealth: operatorStackHealth,
    sessionValid: Boolean(snapshot?.session_context.session_valid),
    sessionLabel: snapshot?.session_context.active_session ?? "outside",
    allowedSessions,
    conceptRecommendation,
    latestScan,
    currentProposal,
    activeExecution,
    lastExecution,
    globalPaused: Boolean(globalControl.effective?.paused),
  });

  const showSubmitAction = currentProposal?.status === "ready_for_submission";
  const showSyncAction =
    Boolean(currentProposal) &&
    (currentProposal?.status === "submitted_testnet" || Boolean(activeExecution));
  const showCancelAction = Boolean(activeExecution) || currentProposal?.status === "submitted_testnet";
  const inspectionCanSubmit = inspectionProposal?.status === "ready_for_submission";
  const inspectionCanSync =
    Boolean(inspectionProposal) &&
    (inspectionProposal?.status === "submitted_testnet" || Boolean(inspectionExecution));
  const inspectionCanCancel = Boolean(inspectionExecution) || inspectionProposal?.status === "submitted_testnet";
  const investigationModeActive = Boolean(selectedTimelineEvent);
  const focusedProposal = inspectionProposal ?? currentProposal;
  const focusedExecution = inspectionExecution ?? activeExecution ?? lastExecution;
  const focusedSignal = inspectionProposal?.side?.toUpperCase() ?? currentSignal;
  const focusedSignalTone =
    focusedSignal === "BUY" || focusedSignal === "LONG"
      ? "text-emerald-300"
      : focusedSignal === "SELL" || focusedSignal === "SHORT"
        ? "text-rose-300"
        : focusedSignal === "CANDIDATE"
          ? "text-cyan-300"
          : "text-amber-300";
  const focusedEntry =
    focusedProposal?.price ??
    (effectiveStructureFocus === "levels" && selectedIctStructure?.levels.ok
      ? selectedIctStructure.levels.entry_price
      : null);
  const focusedStop =
    focusedProposal?.stop_loss ??
    (effectiveStructureFocus === "levels" && selectedIctStructure?.levels.ok
      ? selectedIctStructure.levels.stop_loss
      : null);
  const focusedTarget =
    focusedProposal?.take_profit ??
    (effectiveStructureFocus === "levels" && selectedIctStructure?.levels.ok
      ? selectedIctStructure.levels.take_profit
      : null);
  const focusedVenue =
    focusedProposal?.venue ?? inspectionAction?.venue ?? snapshot?.health.bybit_env ?? "-";
  const focusedState =
    focusedExecution?.sync_status ??
    focusedExecution?.order_status ??
    focusedProposal?.status ??
    (selectedTimelineEvent ? cleanLabel(selectedTimelineEvent.event_type) : "flat");
  const effectiveStructureLabel = effectiveStructureFocus ? cleanLabel(effectiveStructureFocus) : null;
  const defaultStructureSceneFocus =
    selectedStructureFocus ?? keyboardStructureShortcuts.find((item) => item.enabled)?.focus ?? null;
  const investigationSourceLabel = investigationModeActive
    ? `${cleanLabel(selectedTimelineEvent?.source ?? "event")} / ${cleanLabel(selectedTimelineEvent?.kind ?? "event")}`
    : "desk watch";
  const investigationSummary = investigationModeActive
    ? selectedTimelineEvent?.title ?? "Focused investigation"
    : "Monitoring live daemon flow";
  const investigationStatusLabel = investigationModeActive ? "investigating" : "monitoring";
  const shortcutEventItems = useMemo(() => {
    const filteredTimeline =
      eventConsoleFilter === "all"
        ? consoleTimeline
        : consoleTimeline.filter((item) => classifyTimelineItem(item) === eventConsoleFilter);
    const scoredTimeline = scoreGroupedTimelineItems(groupTimelineItems(filteredTimeline), eventRelevanceContext);
    return filterStructureFocusedTimelineItems(scoredTimeline, selectedStructureFocus, selectedSymbol).slice(0, 14);
  }, [
    consoleTimeline,
    eventConsoleFilter,
    eventRelevanceContext,
    selectedStructureFocus,
    selectedSymbol,
  ]);

  useEffect(() => {
    if (selectedTimelineEventId && !timeline.some((item) => item.id === selectedTimelineEventId)) {
      setSelectedTimelineEventId(null);
    }
  }, [timeline, selectedTimelineEventId]);

  useEffect(() => {
    setSelectedStructureFocus(null);
  }, [selectedSymbol]);

  useEffect(() => {
    if (!followFocusedEvent) {
      return;
    }
    if (selectedTimelineEvent?.symbol && selectedTimelineEvent.symbol !== selectedSymbol) {
      setSelectedSymbol(selectedTimelineEvent.symbol);
    }
  }, [followFocusedEvent, selectedSymbol, selectedTimelineEvent]);

  const toggleControl = async (controlKey: string, paused: boolean, reason: string, successMessage: string) => {
    await runAction(controlKey, successMessage, () => updateControlState(controlKey, paused, reason));
  };

  const toggleGlobalKillSwitch = async (paused: boolean) => {
    const confirmed = window.confirm(
      paused
        ? "Engage the global kill switch and pause the stack from the dashboard?"
        : "Release the global kill switch and allow the stack to resume?",
    );
    if (!confirmed) {
      return;
    }

    await runAction(
      "global",
      paused ? "Global kill switch engaged." : "Global kill switch released.",
      () =>
        updateKillSwitch(
          paused,
          paused ? "engaged from trading web dashboard" : "released from trading web dashboard",
        ),
    );
  };

  const submitProposalFromContext = async (proposal: ProposalItem | null) => {
    if (!proposal) {
      return;
    }
    const confirmed = window.confirm(`Submit ${proposal.proposal_id} to the demo exchange from the dashboard?`);
    if (!confirmed) {
      return;
    }

    await runAction("submit-proposal", `Submitted ${proposal.proposal_id} to the exchange.`, () =>
      submitProposal(proposal.proposal_id),
    );
  };

  const syncProposalFromContext = async (proposal: ProposalItem | null) => {
    if (!proposal) {
      return;
    }

    await runAction("sync-proposal", `Synced execution state for ${proposal.proposal_id}.`, () =>
      syncProposal(proposal.proposal_id),
    );
  };

  const cancelProposalFromContext = async (proposal: ProposalItem | null) => {
    if (!proposal) {
      return;
    }
    const confirmed = window.confirm(`Cancel ${proposal.proposal_id} from the dashboard?`);
    if (!confirmed) {
      return;
    }

    await runAction("cancel-proposal", `Cancel request sent for ${proposal.proposal_id}.`, () =>
      cancelProposal(proposal.proposal_id),
    );
  };

  const handleSubmitProposal = async () => {
    await submitProposalFromContext(currentProposal);
  };

  const handleSyncProposal = async () => {
    await syncProposalFromContext(currentProposal);
  };

  const handleCancelProposal = async () => {
    await cancelProposalFromContext(currentProposal);
  };

  const handleFocusStructure = (focus: StructureFocus) => {
    const scored = scoreGroupedTimelineItems(groupTimelineItems(consoleTimeline), {
      ...eventRelevanceContext,
      structureFocus: focus,
    });
    const topEventId =
      filterStructureFocusedTimelineItems(scored, focus, selectedSymbol)[0]?.representative.id ?? null;
    setSelectedStructureFocus(focus);
    if (topEventId) {
      setSelectedTimelineEventId(topEventId);
    }
    setReviewDrawerOpen(true);
  };

  const clearStructureFocus = () => {
    setSelectedStructureFocus(null);
  };

  const clearInvestigation = () => {
    setSelectedTimelineEventId(null);
    setSelectedStructureFocus(null);
  };

  const applyEventConsolePreset = (preset: EventConsolePreset) => {
    setEventConsolePreset(preset);
    if (preset === "execution_triage") {
      setEventConsoleFilter("execution");
      setEventConsoleSeverityFilter("all");
      return;
    }
    if (preset === "concept_review") {
      setEventConsoleFilter("concept");
      setEventConsoleSeverityFilter("warning");
      return;
    }
    if (preset === "control_actions") {
      setEventConsoleFilter("control");
      setEventConsoleSeverityFilter("all");
      return;
    }
  };

  const cycleFocusedEvent = (direction: 1 | -1) => {
    if (shortcutEventItems.length === 0) {
      return;
    }

    const eventIds = shortcutEventItems.map((item) => item.representative.id);
    const currentIndex = eventIds.findIndex((id) => id === selectedTimelineEventId);
    const nextIndex =
      currentIndex < 0
        ? direction === 1
          ? 0
          : eventIds.length - 1
        : (currentIndex + direction + eventIds.length) % eventIds.length;

    setSelectedTimelineEventId(eventIds[nextIndex] ?? null);
  };

  const focusTopRankedEvent = () => {
    const topEventId = shortcutEventItems[0]?.representative.id ?? null;
    if (!topEventId) {
      return;
    }
    setSelectedTimelineEventId(topEventId);
  };

  const resolveRankedEventId = ({
    filter,
    severity,
    scope,
    symbol,
    structureFocus,
  }: {
    filter: EventConsoleFilter;
    severity: EventConsoleSeverityFilter;
    scope: EventConsoleScope;
    symbol: string;
    structureFocus: StructureFocus | null;
  }) => {
    const scopedTimeline =
      scope === "global" ? timeline : timeline.filter((item) => !item.symbol || item.symbol === symbol);
    const filteredTimeline = scopedTimeline.filter((item) => {
      if (filter !== "all" && classifyTimelineItem(item) !== filter) {
        return false;
      }
      if (severity !== "all" && item.severity !== severity) {
        return false;
      }
      return true;
    });

    const scoredTimeline = scoreGroupedTimelineItems(groupTimelineItems(filteredTimeline), {
      ...eventRelevanceContext,
      selectedSymbol: symbol,
      structureFocus,
    });

    return filterStructureFocusedTimelineItems(scoredTimeline, structureFocus, symbol)[0]?.representative.id ?? null;
  };

  const launchOperatorFlow = ({
    symbol = selectedSymbol,
    preset = "custom" as EventConsolePreset,
    filter = eventConsoleFilter,
    severity = eventConsoleSeverityFilter,
    scope = eventConsoleScope,
    workspaceTab: nextWorkspaceTab = workspaceTab,
    followFocus = followFocusedEvent,
    structureFocus = selectedStructureFocus,
    openReview = false,
    focusTop = false,
  }: {
    symbol?: string;
    preset?: EventConsolePreset;
    filter?: EventConsoleFilter;
    severity?: EventConsoleSeverityFilter;
    scope?: EventConsoleScope;
    workspaceTab?: WorkspaceTab;
    followFocus?: boolean;
    structureFocus?: StructureFocus | null;
    openReview?: boolean;
    focusTop?: boolean;
  }) => {
    setSelectedSymbol(symbol);
    setEventConsoleScope(scope);
    setWorkspaceTab(nextWorkspaceTab);
    setFollowFocusedEvent(followFocus);
    if (preset === "custom") {
      setEventConsolePreset("custom");
      setEventConsoleFilter(filter);
      setEventConsoleSeverityFilter(severity);
    } else {
      applyEventConsolePreset(preset);
    }
    setSelectedStructureFocus(structureFocus);

    if (focusTop) {
      const nextEventId = resolveRankedEventId({
        filter: preset === "custom" ? filter : preset === "concept_review" ? "concept" : preset === "control_actions" ? "control" : "execution",
        severity: preset === "custom" ? severity : preset === "concept_review" ? "warning" : "all",
        scope,
        symbol,
        structureFocus,
      });
      setSelectedTimelineEventId(nextEventId);
    }

    if (openReview) {
      setReviewDrawerOpen(true);
    }
  };

  const snapshotCurrentScene = (): SavedOperatorSceneState => ({
    symbol: selectedSymbol,
    preset: eventConsolePreset,
    filter: eventConsoleFilter,
    severity: eventConsoleSeverityFilter,
    scope: eventConsoleScope,
    workspaceTab,
    followFocus: followFocusedEvent,
    structureFocus: selectedStructureFocus,
    openReview: reviewDrawerOpen,
    focusTop: investigationModeActive || Boolean(selectedStructureFocus),
  });

  const restoreSavedScene = (scene: SavedOperatorScene) => {
    launchOperatorFlow({
      symbol: scene.state.symbol,
      preset: scene.state.preset,
      filter: scene.state.filter,
      severity: scene.state.severity,
      scope: scene.state.scope,
      workspaceTab: scene.state.workspaceTab,
      followFocus: scene.state.followFocus,
      structureFocus: scene.state.structureFocus,
      openReview: scene.state.openReview,
      focusTop: scene.state.focusTop,
    });
  };

  useEffect(() => {
    if (defaultSceneHydratedRef.current) {
      return;
    }

    defaultSceneHydratedRef.current = true;
    const defaultScene = savedOperatorScenes.find((scene) => scene.isDefault);
    if (defaultScene) {
      restoreSavedScene(defaultScene);
    }
  }, [restoreSavedScene, savedOperatorScenes]);

  const saveCurrentScene = () => {
    const defaultName =
      eventConsolePreset !== "custom"
        ? `${cleanLabel(eventConsolePreset)} ${selectedSymbol}`
        : effectiveStructureLabel
          ? `${effectiveStructureLabel} ${selectedSymbol}`
          : `${selectedSymbol} desk scene`;
    const name = window.prompt("Name this operator scene", defaultName)?.trim();
    if (!name) {
      return;
    }

    const scene: SavedOperatorScene = {
      id: `scene-${Date.now()}`,
      name,
      savedAt: new Date().toISOString(),
      isDefault: false,
      state: snapshotCurrentScene(),
    };

    setSavedOperatorScenes((current) => normalizeSavedOperatorScenes([scene, ...current]));
  };

  const deleteSavedScene = (sceneId: string) => {
    setSavedOperatorScenes((current) => normalizeSavedOperatorScenes(current.filter((scene) => scene.id !== sceneId)));
  };

  const renameSavedScene = (sceneId: string) => {
    const currentScene = savedOperatorScenes.find((scene) => scene.id === sceneId);
    if (!currentScene) {
      return;
    }

    const nextName = window.prompt("Rename saved operator scene", currentScene.name)?.trim();
    if (!nextName) {
      return;
    }

    setSavedOperatorScenes((current) =>
      normalizeSavedOperatorScenes(current.map((scene) => (scene.id === sceneId ? { ...scene, name: nextName } : scene))),
    );
  };

  const toggleDefaultSavedScene = (sceneId: string) => {
    setSavedOperatorScenes((current) =>
      normalizeSavedOperatorScenes(current.map((scene) =>
        scene.id === sceneId
          ? { ...scene, isDefault: !scene.isDefault }
          : { ...scene, isDefault: false },
      )),
    );
  };

  const exportSavedScenes = () => {
    if (savedOperatorScenes.length === 0) {
      setActionState({
        status: "error",
        message: "No saved scenes are available to export yet.",
        actionKey: "scene-export",
      });
      return;
    }

    const payload = {
      version: 1,
      exported_at: new Date().toISOString(),
      scenes: normalizeSavedOperatorScenes(savedOperatorScenes),
    };

    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `trading-operator-scenes-${new Date().toISOString().slice(0, 10)}.json`;
    anchor.click();
    window.URL.revokeObjectURL(url);

    setActionState({
      status: "success",
      message: `Exported ${savedOperatorScenes.length} saved scene${savedOperatorScenes.length === 1 ? "" : "s"} to a local scene pack.`,
      actionKey: "scene-export",
    });
  };

  const importSavedScenes = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }

    try {
      const rawText = await file.text();
      const parsed = JSON.parse(rawText) as { scenes?: SavedOperatorScene[] };
      const importedScenes = normalizeSavedOperatorScenes(Array.isArray(parsed.scenes) ? parsed.scenes : []);

      if (importedScenes.length === 0) {
        setActionState({
          status: "error",
          message: "The imported file did not contain any valid saved operator scenes.",
          actionKey: "scene-import",
        });
        return;
      }

      const replaceExisting =
        savedOperatorScenes.length > 0
          ? window.confirm("Replace the current saved scenes with this imported scene pack? Choose Cancel to merge instead.")
          : true;

      setSavedOperatorScenes((current) =>
        normalizeSavedOperatorScenes(
          replaceExisting
            ? importedScenes.map((scene, index) => ({
                ...scene,
                id: `scene-import-${Date.now()}-${index}`,
              }))
            : [
                ...importedScenes.map((scene, index) => ({
                  ...scene,
                  id: `scene-import-${Date.now()}-${index}`,
                })),
                ...current,
              ],
        ),
      );
      setActionState({
        status: "success",
        message: `Imported ${importedScenes.length} saved scene${importedScenes.length === 1 ? "" : "s"} from the scene pack.`,
        actionKey: "scene-import",
      });
    } catch {
      setActionState({
        status: "error",
        message: "The selected scene pack could not be parsed.",
        actionKey: "scene-import",
      });
    }
  };

  const commandPaletteActions = useMemo<CommandPaletteAction[]>(() => {
    const actions: CommandPaletteAction[] = [
      {
        id: "open-review",
        title: "Open Review Deck",
        group: "Navigation",
        meta: selectedSymbol,
        keywords: "review drawer inspect symbol",
        run: () => setReviewDrawerOpen(true),
      },
      {
        id: "export-scenes",
        title: "Export Saved Scene Pack",
        group: "Saved Scene",
        meta: `${savedOperatorScenes.length} saved`,
        keywords: "export saved scenes scene pack backup download",
        run: exportSavedScenes,
      },
      {
        id: "import-scenes",
        title: "Import Scene Pack",
        group: "Saved Scene",
        meta: "local file",
        keywords: "import saved scenes scene pack upload restore",
        run: () => sceneImportInputRef.current?.click(),
      },
      {
        id: "workflow-execution-triage",
        title: "Launch Execution Triage",
        group: "Operator Flow",
        meta: selectedSymbol,
        keywords: "workflow execution triage order sync cancel working fill lifecycle",
        run: () =>
          launchOperatorFlow({
            preset: "execution_triage",
            scope: "global",
            workspaceTab: "execution",
            followFocus: false,
            structureFocus:
              keyboardStructureShortcuts.find((item) => item.focus === "levels" && item.enabled)?.focus ?? null,
            openReview: true,
            focusTop: true,
          }),
      },
      {
        id: "workflow-concept-review",
        title: "Launch Concept Review",
        group: "Operator Flow",
        meta: selectedSymbol,
        keywords: "workflow concept review blocker operator signal recommendation daemon concept",
        run: () =>
          launchOperatorFlow({
            preset: "concept_review",
            scope: "selected",
            workspaceTab: "rules",
            followFocus: true,
            structureFocus: null,
            openReview: true,
            focusTop: true,
          }),
      },
      {
        id: "workflow-focused-investigation",
        title: "Launch Focused Investigation",
        group: "Operator Flow",
        meta: selectedTimelineEvent?.symbol ?? selectedSymbol,
        keywords: "workflow focused investigation top event inspect chart review deck",
        run: () =>
          launchOperatorFlow({
            preset: "custom",
            filter: eventConsoleFilter,
            severity: eventConsoleSeverityFilter,
            scope: eventConsoleScope,
            workspaceTab: "review",
            followFocus: true,
            structureFocus: selectedStructureFocus,
            openReview: true,
            focusTop: !selectedTimelineEventId,
          }),
      },
      {
        id: "focus-top-event",
        title: "Focus Top Ranked Event",
        group: "Investigation",
        meta: shortcutEventItems[0]?.representative.symbol ?? selectedSymbol,
        keywords: "focus top ranked daemon event investigation console",
        run: focusTopRankedEvent,
      },
      {
        id: "clear-investigation",
        title: "Clear Investigation and Structure Lens",
        group: "Investigation",
        meta: investigationModeActive ? investigationStatusLabel : "desk mode",
        keywords: "clear focus lens investigation escape reset",
        run: clearInvestigation,
      },
      {
        id: "toggle-scope",
        title: eventConsoleScope === "global" ? "Switch to Selected Market Stream" : "Switch to Global Stream",
        group: "Console",
        meta: eventConsoleScope,
        keywords: "console scope global selected stream",
        run: () => setEventConsoleScope(eventConsoleScope === "global" ? "selected" : "global"),
      },
      {
        id: "toggle-follow",
        title: followFocusedEvent ? "Turn Follow Focus Off" : "Turn Follow Focus On",
        group: "Console",
        meta: followFocusedEvent ? "tracking symbol" : "manual symbol",
        keywords: "follow focus symbol sync console",
        run: () => setFollowFocusedEvent((current) => !current),
      },
      {
        id: "cycle-event-next",
        title: "Cycle to Next Ranked Event",
        group: "Investigation",
        meta: "J",
        keywords: "next event ranked forward",
        run: () => cycleFocusedEvent(1),
      },
      {
        id: "cycle-event-prev",
        title: "Cycle to Previous Ranked Event",
        group: "Investigation",
        meta: "K",
        keywords: "previous event ranked backward",
        run: () => cycleFocusedEvent(-1),
      },
    ];

    for (const symbol of rules?.allowed_instruments ?? ["BTCUSDT", "ETHUSDT"]) {
      actions.push({
        id: `symbol-${symbol}`,
        title: `Jump to ${symbol}`,
        group: "Markets",
        meta: selectedSymbol === symbol ? "active" : "market",
        keywords: `market symbol ${symbol.toLowerCase()}`,
        run: () => setSelectedSymbol(symbol),
      });
    }

    for (const symbol of rules?.allowed_instruments ?? ["BTCUSDT", "ETHUSDT"]) {
      for (const focus of ["sweep", "mss", "fvg", "displacement", "levels"] as StructureFocus[]) {
        const label = cleanLabel(focus);
        actions.push({
          id: `market-structure-${symbol}-${focus}`,
          title: `Jump to ${symbol} and Focus ${label}`,
          group: "Operator Flow",
          meta: symbol,
          keywords: `market symbol ${symbol.toLowerCase()} focus ${focus} ${label.toLowerCase()} chart review`,
          run: () =>
            launchOperatorFlow({
              symbol,
              preset: "custom",
              filter: eventConsoleFilter,
              severity: eventConsoleSeverityFilter,
              scope: "selected",
              workspaceTab: "review",
              followFocus: false,
              structureFocus: focus,
              openReview: true,
              focusTop: true,
            }),
        });
      }
    }

    for (const structureShortcut of keyboardStructureShortcuts) {
      if (!structureShortcut.enabled) {
        continue;
      }
      actions.push({
        id: `structure-${structureShortcut.focus}`,
        title: `Focus ${structureShortcut.label}`,
        group: "ICT Structure",
        meta: selectedSymbol,
        keywords: `structure ${structureShortcut.focus} ${structureShortcut.label.toLowerCase()} lens chart`,
        run: () => handleFocusStructure(structureShortcut.focus),
      });
    }

    for (const scene of savedOperatorScenes) {
      actions.push({
        id: `saved-scene-${scene.id}`,
        title: `Restore ${scene.name}${scene.isDefault ? " (Default)" : ""}`,
        group: "Saved Scene",
        meta: scene.isDefault ? "default" : formatTimestamp(scene.savedAt),
        keywords: `saved scene restore ${scene.name.toLowerCase()} ${scene.state.symbol.toLowerCase()} ${scene.isDefault ? "default startup pinned" : ""}`,
        run: () => restoreSavedScene(scene),
      });
    }

    return actions;
  }, [
    cycleFocusedEvent,
    eventConsoleFilter,
    eventConsoleScope,
    eventConsoleSeverityFilter,
    exportSavedScenes,
    followFocusedEvent,
    handleFocusStructure,
    keyboardStructureShortcuts,
    launchOperatorFlow,
    investigationModeActive,
    investigationStatusLabel,
    restoreSavedScene,
    rules?.allowed_instruments,
    savedOperatorScenes,
    sceneImportInputRef,
    selectedSymbol,
    selectedStructureFocus,
    selectedTimelineEvent?.symbol,
    selectedTimelineEventId,
    shortcutEventItems,
  ]);

  const operatorScenes = useMemo<OperatorScene[]>(
    () => [
      {
        id: "desk-watch",
        title: "Desk Watch",
        description: "Return the desk to the baseline monitoring posture for the selected market.",
        meta: selectedSymbol,
        active:
          !investigationModeActive &&
          eventConsolePreset === "custom" &&
          eventConsoleScope === "selected" &&
          !selectedStructureFocus,
        run: () => {
          clearInvestigation();
          setEventConsolePreset("custom");
          setEventConsoleFilter("all");
          setEventConsoleSeverityFilter("all");
          setEventConsoleScope("selected");
          setWorkspaceTab("console");
          setFollowFocusedEvent(true);
          setReviewDrawerOpen(false);
        },
      },
      {
        id: "concept-review",
        title: "Concept Review",
        description: "Bias the desk toward blocker, verdict, and operator-signal investigation.",
        meta: selectedSymbol,
        active: eventConsolePreset === "concept_review",
        run: () =>
          launchOperatorFlow({
            preset: "concept_review",
            scope: "selected",
            workspaceTab: "rules",
            followFocus: true,
            structureFocus: null,
            openReview: true,
            focusTop: true,
          }),
      },
      {
        id: "execution-triage",
        title: "Execution Triage",
        description: "Switch into execution-heavy flow with plan lifecycle context and working-order focus.",
        meta: "global",
        active: eventConsolePreset === "execution_triage",
        run: () =>
          launchOperatorFlow({
            preset: "execution_triage",
            scope: "global",
            workspaceTab: "execution",
            followFocus: false,
            structureFocus:
              keyboardStructureShortcuts.find((item) => item.focus === "levels" && item.enabled)?.focus ?? null,
            openReview: true,
            focusTop: true,
          }),
      },
      {
        id: "focused-investigation",
        title: "Focused Investigation",
        description: "Drive the desk from the current event context and keep the chart, rail, and review aligned.",
        meta: selectedTimelineEvent?.symbol ?? selectedSymbol,
        active: investigationModeActive,
        run: () =>
          launchOperatorFlow({
            preset: "custom",
            filter: eventConsoleFilter,
            severity: eventConsoleSeverityFilter,
            scope: eventConsoleScope,
            workspaceTab: "review",
            followFocus: true,
            structureFocus: selectedStructureFocus,
            openReview: true,
            focusTop: !selectedTimelineEventId,
          }),
      },
      {
        id: "structure-review",
        title: "Structure Review",
        description: "Open the deck around the strongest current ICT structure and correlate the console to it.",
        meta: defaultStructureSceneFocus ? cleanLabel(defaultStructureSceneFocus) : "awaiting structure",
        active: Boolean(selectedStructureFocus),
        disabled: !defaultStructureSceneFocus,
        run: () => {
          if (!defaultStructureSceneFocus) {
            return;
          }
          launchOperatorFlow({
            symbol: selectedSymbol,
            preset: "custom",
            filter: eventConsoleFilter,
            severity: eventConsoleSeverityFilter,
            scope: "selected",
            workspaceTab: "review",
            followFocus: false,
            structureFocus: defaultStructureSceneFocus,
            openReview: true,
            focusTop: true,
          });
        },
      },
    ],
    [
      clearInvestigation,
      defaultStructureSceneFocus,
      eventConsoleFilter,
      eventConsolePreset,
      eventConsoleScope,
      eventConsoleSeverityFilter,
      investigationModeActive,
      keyboardStructureShortcuts,
      launchOperatorFlow,
      selectedStructureFocus,
      selectedSymbol,
      selectedTimelineEvent?.symbol,
      selectedTimelineEventId,
    ],
  );
  const currentSceneSnapshot = snapshotCurrentScene();
  const savedOperatorSceneCards = useMemo<OperatorScene[]>(
    () =>
      savedOperatorScenes.map((scene) => ({
        id: scene.id,
        title: scene.name,
        description:
          scene.state.preset !== "custom"
            ? `Saved ${cleanLabel(scene.state.preset)} scene with ${scene.state.scope} console posture.`
            : `Saved ${scene.state.symbol} scene with ${scene.state.structureFocus ? `${cleanLabel(scene.state.structureFocus)} focus` : "manual desk posture"}.`,
        meta: formatTimestamp(scene.savedAt),
        active: JSON.stringify(scene.state) === JSON.stringify(currentSceneSnapshot),
        run: () => restoreSavedScene(scene),
      })),
    [currentSceneSnapshot, restoreSavedScene, savedOperatorScenes],
  );
  const workspaceTabs: Array<{ id: WorkspaceTab; label: string; meta: string; icon: ReactNode }> = [
    { id: "console", label: "Console", meta: "live daemon flow", icon: <Activity size={12} strokeWidth={1.8} /> },
    { id: "review", label: "Review", meta: "scan and investigation", icon: <FileSearch size={12} strokeWidth={1.8} /> },
    { id: "execution", label: "Execution", meta: "orders and runbook", icon: <SlidersHorizontal size={12} strokeWidth={1.8} /> },
    { id: "rules", label: "Rules", meta: "concept and checklist", icon: <Shield size={12} strokeWidth={1.8} /> },
    { id: "desk", label: "Desk", meta: "sessions, scenes, shortcuts", icon: <PanelBottom size={12} strokeWidth={1.8} /> },
  ];

  const filteredCommandPaletteActions = useMemo(() => {
    const normalizedQuery = commandPaletteQuery.trim().toLowerCase();
    if (!normalizedQuery) {
      return commandPaletteActions;
    }

    return commandPaletteActions.filter((action) =>
      [action.title, action.group, action.meta, action.keywords]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(normalizedQuery),
    );
  }, [commandPaletteActions, commandPaletteQuery]);

  useEffect(() => {
    setCommandPaletteIndex(0);
  }, [commandPaletteOpen, commandPaletteQuery]);

  const runCommandPaletteAction = (action: CommandPaletteAction | null) => {
    if (!action) {
      return;
    }

    action.run();
    setCommandPaletteOpen(false);
    setCommandPaletteQuery("");
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase();

      if ((event.metaKey || event.ctrlKey) && key === "k") {
        event.preventDefault();
        setCommandPaletteOpen((current) => {
          const next = !current;
          if (!next) {
            setCommandPaletteQuery("");
          }
          return next;
        });
        return;
      }

      if (commandPaletteOpen) {
        if (key === "escape") {
          event.preventDefault();
          setCommandPaletteOpen(false);
          setCommandPaletteQuery("");
          return;
        }

        if (key === "arrowdown") {
          event.preventDefault();
          setCommandPaletteIndex((current) =>
            filteredCommandPaletteActions.length > 0 ? (current + 1) % filteredCommandPaletteActions.length : 0,
          );
          return;
        }

        if (key === "arrowup") {
          event.preventDefault();
          setCommandPaletteIndex((current) =>
            filteredCommandPaletteActions.length > 0
              ? (current - 1 + filteredCommandPaletteActions.length) % filteredCommandPaletteActions.length
              : 0,
          );
          return;
        }

        if (key === "enter") {
          event.preventDefault();
          runCommandPaletteAction(filteredCommandPaletteActions[commandPaletteIndex] ?? null);
        }
        return;
      }

      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }

      if (shouldIgnoreShortcutTarget(event.target)) {
        return;
      }

      if (key === "escape") {
        if (reviewDrawerOpen) {
          event.preventDefault();
          setReviewDrawerOpen(false);
          return;
        }

        if (investigationModeActive || selectedStructureFocus) {
          event.preventDefault();
          clearInvestigation();
        }
        return;
      }

      if (key === "r") {
        event.preventDefault();
        setReviewDrawerOpen(true);
        return;
      }

      if (key === "j") {
        event.preventDefault();
        cycleFocusedEvent(1);
        return;
      }

      if (key === "k") {
        event.preventDefault();
        cycleFocusedEvent(-1);
        return;
      }

      const structureShortcut = keyboardStructureShortcuts.find((item) => item.key === key && item.enabled);
      if (structureShortcut) {
        event.preventDefault();
        handleFocusStructure(structureShortcut.focus);
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    cycleFocusedEvent,
    commandPaletteIndex,
    commandPaletteOpen,
    filteredCommandPaletteActions,
    handleFocusStructure,
    investigationModeActive,
    keyboardStructureShortcuts,
    reviewDrawerOpen,
    selectedStructureFocus,
  ]);

  const latestRiskCheck = latestExecutionRiskChecks[0] ?? null;
  const latestIntent = latestExecutionIntents[0] ?? null;
  const latestTrace = latestSignalTraces[0] ?? null;
  const latestTraceExecutable = Boolean(latestTrace?.execution_eligible);
  const actionabilityLabel =
    currentProposal?.status === "ready_for_submission"
      ? "Plan ready"
      : activeExecution
        ? "Managing order"
        : latestTraceExecutable || latestScanIsExecutionEligible
          ? "Ready for review"
          : formatOperatorStatusLabel(operatorSignal, outsideSessionAllowed);
  const actionabilityTone =
    currentProposal?.status === "ready_for_submission" || latestTraceExecutable || latestScanIsExecutionEligible
      ? "text-emerald-200"
      : activeExecution
        ? "text-cyan-200"
        : "text-amber-100";
  const actionabilityDetail =
    currentProposal?.status === "ready_for_submission"
      ? `${currentProposal.proposal_id} is waiting for manual submission.`
      : activeExecution
        ? `${activeExecution.symbol} is ${formatOperatorStatusLabel(activeExecution.sync_status)}.`
        : formatSessionAwareCopy(operatorSummary, outsideSessionAllowed);
  const riskPostureLabel = globalControl.effective?.paused
    ? "Emergency stop engaged"
    : latestRiskCheck
      ? formatOperatorStatusLabel(latestRiskCheck.state)
      : "Controls clear";
  const riskPostureTone = globalControl.effective?.paused
    ? "text-rose-200"
    : latestRiskCheck?.state === "blocked"
      ? "text-rose-200"
      : latestRiskCheck?.state === "allow" || latestRiskCheck?.state === "allowed"
        ? "text-emerald-200"
        : "text-emerald-200";
  const riskPostureDetail = globalControl.effective?.paused
    ? "Order submission and trade management are paused globally."
    : latestRiskCheck?.primary_reason ?? "No active risk block is reported for this symbol.";
  const primaryBlockerLabel =
    topReadinessBlocker
      ? `${cleanLabel(topReadinessBlocker.component_key)} · ${formatOperatorStatusLabel(topReadinessBlocker.status)}`
      : dominantBlocker && dominantBlocker !== "n/a"
        ? formatBlockerClassLabel(dominantBlocker, outsideSessionAllowed)
        : "No primary blocker";
  const selectedShadowTraceCount = shadowReviewSummary?.by_symbol[selectedSymbol] ?? 0;
  const shadowTopState = Object.entries(shadowReviewSummary?.by_opportunity_state ?? {})[0]?.[0] ?? null;
  const shadowTopBlocker = Object.entries(shadowReviewSummary?.by_blocker_class ?? {})[0]?.[0] ?? null;
  type LifecycleRow = {
    id: string;
    stage: string;
    status: string;
    detail: string;
    updatedAt: string | null;
  };
  const recentLifecycleRows: LifecycleRow[] = [];
  if (latestTrace) {
    recentLifecycleRows.push({
      id: latestTrace.trace_id,
      stage: "Signal trace",
      status: formatOperatorStatusLabel(latestTrace.decision, outsideSessionAllowed),
      detail: `${formatOperatorStatusLabel(latestTrace.opportunity_state ?? "unknown", outsideSessionAllowed)} · ${formatBlockerClassLabel(latestTrace.blocker_class ?? "no_blocker", outsideSessionAllowed)}`,
      updatedAt: latestTrace.created_at ?? null,
    });
  }
  if (latestIntent) {
    recentLifecycleRows.push({
      id: latestIntent.intent_id,
      stage: "Execution intent",
      status: formatOperatorStatusLabel(latestIntent.state),
      detail: latestIntent.proposal_id ?? "no linked proposal",
      updatedAt: latestIntent.updated_at ?? latestIntent.created_at ?? null,
    });
  }
  if (latestRiskCheck) {
    recentLifecycleRows.push({
      id: latestRiskCheck.risk_check_id,
      stage: "Risk check",
      status: formatOperatorStatusLabel(latestRiskCheck.state),
      detail: latestRiskCheck.primary_reason ?? "no primary risk reason",
      updatedAt: latestRiskCheck.created_at ?? null,
    });
  }

  const renderWorkspaceSurface = () => {
    if (workspaceTab === "console") {
      return (
        <div className="grid min-h-[360px] gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <section className="control-room-panel flex min-h-0 flex-col p-4">
            <PanelHeader
              title="System Event Stream"
              icon={<Diamond size={14} strokeWidth={1.8} />}
              meta={`${streamState === "live" ? "streaming" : "reconnecting"} · ${eventConsoleScope === "global" ? "global" : selectedSymbol}`}
            />
            <div className="min-h-0 flex-1 overflow-auto pr-1">
              <EventConsole
                items={consoleTimeline}
                activeFilter={eventConsoleFilter}
                onFilterChange={setEventConsoleFilter}
                activePreset={eventConsolePreset}
                onPresetChange={setEventConsolePreset}
                severityFilter={eventConsoleSeverityFilter}
                onSeverityFilterChange={setEventConsoleSeverityFilter}
                scope={eventConsoleScope}
                onScopeChange={setEventConsoleScope}
                followFocusedEvent={followFocusedEvent}
                onToggleFollow={setFollowFocusedEvent}
                relevanceContext={eventRelevanceContext}
                structureFocus={selectedStructureFocus}
                onClearStructureFocus={clearStructureFocus}
                selectedEventId={selectedTimelineEventId}
                onSelectEvent={setSelectedTimelineEventId}
                onOpenReview={() => setReviewDrawerOpen(true)}
                outsideSessionAllowed={outsideSessionAllowed}
              />
            </div>
          </section>

          <FocusedInspectionRail
            event={selectedTimelineEvent}
            proposal={inspectionProposal}
            execution={inspectionExecution}
            action={inspectionAction}
            auditTrail={inspectionAuditTrail}
            symbolAuditTrail={inspectionSymbolAuditTrail}
            conceptRecommendation={conceptRecommendation}
            operatorSignal={operatorSignal}
            dominantBlocker={dominantBlocker}
            actionState={actionState}
            canSubmit={Boolean(inspectionCanSubmit)}
            canSync={Boolean(inspectionCanSync)}
            canCancel={Boolean(inspectionCanCancel)}
            onSubmit={() => void submitProposalFromContext(inspectionProposal)}
            onSync={() => void syncProposalFromContext(inspectionProposal)}
            onCancel={() => void cancelProposalFromContext(inspectionProposal)}
            onOpenReview={() => setReviewDrawerOpen(true)}
            onFocusEvent={setSelectedTimelineEventId}
            onClear={() => setSelectedTimelineEventId(null)}
            outsideSessionAllowed={outsideSessionAllowed}
          />
        </div>
      );
    }

    if (workspaceTab === "review") {
      return (
        <div className="grid min-h-[360px] gap-4 xl:grid-cols-[0.86fr_1.14fr]">
          <section className="control-room-panel min-h-0 overflow-auto p-4">
            <PanelHeader title="Signal Review" meta={selectedSymbol} icon={<Activity size={14} strokeWidth={1.8} />} />
            <ScanFeed items={selectedScans.slice(0, 10)} emptyLabel="No recent scan rows for this market." allowedSessions={allowedSessions} />
          </section>
          <FocusedInspectionRail
            event={selectedTimelineEvent}
            proposal={inspectionProposal}
            execution={inspectionExecution}
            action={inspectionAction}
            auditTrail={inspectionAuditTrail}
            symbolAuditTrail={inspectionSymbolAuditTrail}
            conceptRecommendation={conceptRecommendation}
            operatorSignal={operatorSignal}
            dominantBlocker={dominantBlocker}
            actionState={actionState}
            canSubmit={Boolean(inspectionCanSubmit)}
            canSync={Boolean(inspectionCanSync)}
            canCancel={Boolean(inspectionCanCancel)}
            onSubmit={() => void submitProposalFromContext(inspectionProposal)}
            onSync={() => void syncProposalFromContext(inspectionProposal)}
            onCancel={() => void cancelProposalFromContext(inspectionProposal)}
            onOpenReview={() => setReviewDrawerOpen(true)}
            onFocusEvent={setSelectedTimelineEventId}
            onClear={() => setSelectedTimelineEventId(null)}
            outsideSessionAllowed={outsideSessionAllowed}
          />
        </div>
      );
    }

    if (workspaceTab === "execution") {
      return (
        <div className="grid min-h-[360px] gap-4 xl:grid-cols-[0.92fr_1.08fr]">
          <section className="control-room-panel min-h-0 overflow-auto p-4">
            <PanelHeader title="Execution Lifecycle" meta={openExecutionRows.length > 0 ? "open" : "flat"} icon={<ChartBar size={14} strokeWidth={1.8} />} />
            <ExecutionTable items={openExecutionRows.length > 0 ? openExecutionRows : executionState.slice(0, 6)} />
          </section>
          <section className="control-room-panel min-h-0 overflow-auto p-4">
            <PanelHeader title="Operator Runbook" meta={selectedSymbol} icon={<BookOpen size={14} strokeWidth={1.8} />} />
            <WorkflowRunbook steps={workflow.steps} nextAction={workflow.nextAction} />
          </section>
        </div>
      );
    }

    if (workspaceTab === "rules") {
      return (
        <div className="grid min-h-[360px] gap-4 xl:grid-cols-[1.12fr_0.88fr]">
          <div className="min-h-0 space-y-4 overflow-auto pr-1">
            <section className="control-room-panel p-4">
              <PanelHeader title="Strategy Readiness" icon={<BrainCircuit size={14} strokeWidth={1.8} />} meta={conceptRuntime ? formatRelativeTime(conceptRuntime.updated_at) : "awaiting runtime"} />
              <AnalysisRow label="overall" value={formatOperatorStatusLabel(conceptOverall, outsideSessionAllowed)} tone="text-slate-100" />
              <AnalysisRow label="verdict" value={formatOperatorStatusLabel(conceptRecommendation, outsideSessionAllowed)} tone="text-cyan-300" />
              <AnalysisRow label="signal" value={formatOperatorStatusLabel(operatorSignal, outsideSessionAllowed)} tone="text-emerald-300" />
              <AnalysisRow label="candidate %" value={candidateRatio} tone="text-slate-200" />
              <AnalysisRow label="blocker" value={formatBlockerClassLabel(dominantBlocker, outsideSessionAllowed)} tone="text-amber-300" />
              <div className="mt-3 rounded-lg border border-slate-800 bg-[#0b121a] p-3 text-sm text-slate-400">{formatSessionAwareCopy(operatorSummary, outsideSessionAllowed)}</div>
            </section>
            <RevisionLoopPanel
              compareSummary={conceptRevisionCompare}
              acceptanceSummary={conceptAcceptance}
              acceptanceHistory={conceptAcceptanceHistory}
              stage7Summary={conceptStage7Decision}
              stageStatus={conceptStageStatus}
              activity={revisionActivity}
              results={lastRevisionResults}
              linkedRevisions={lastLinkedRevisions}
              recentLinkEvents={recentRevisionLinkEvents}
              reviews={conceptReviews}
              revisions={conceptRevisions}
              outsideSessionAllowed={outsideSessionAllowed}
            />
          </div>
          <section className="control-room-panel min-h-0 overflow-auto p-4">
            <PanelHeader title="Rule Stack" icon={<Shield size={14} strokeWidth={1.8} />} meta={`${rules?.required_checklist.length ?? 0} active`} />
            {rules ? <RuleStack items={rules.required_checklist} /> : <p className="text-sm text-slate-500">Loading rules...</p>}
          </section>
        </div>
      );
    }

    return (
      <div className="grid min-h-[360px] gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="min-h-0 space-y-4 overflow-auto pr-1">
          <section className="control-room-panel p-4">
            <PanelHeader title="Market Clocks" icon={<Clock3 size={14} strokeWidth={1.8} />} meta={snapshot?.session_context.weekend ? "weekend" : "weekday"} />
            <div className="grid gap-3 md:grid-cols-3">
              {tradingClocks.map((clock) => (
                <ClockTile key={`desk-${clock.id}`} label={clock.label} value={clock.value} meta={clock.meta} />
              ))}
            </div>
          </section>
          <section className="control-room-panel p-4">
            <PanelHeader title="Session Board" icon={<Clock3 size={14} strokeWidth={1.8} />} meta={`${rules?.allowed_sessions.length ?? 0} allowed`} />
            <div className="grid gap-3 md:grid-cols-2">
              {sessionBoard.map((session) => (
                <SessionWindowCard key={`desk-${session.id}`} session={session} />
              ))}
            </div>
          </section>
          <section className="control-room-panel p-4">
            <PanelHeader title="Desk Shortcuts" icon={<PanelBottom size={14} strokeWidth={1.8} />} meta="keyboard flow" />
            <div className="flex flex-wrap items-center gap-2">
              <ShortcutHint keys="R" label="Review" />
              <ShortcutHint keys="Esc" label={reviewDrawerOpen ? "Close Review" : investigationModeActive || selectedStructureFocus ? "Clear Focus" : "Standby"} />
              <ShortcutHint keys="J / K" label="Cycle Events" active={shortcutEventItems.length > 0} />
              <ShortcutHint keys="Cmd K" label="Palette" />
              {keyboardStructureShortcuts.map((item) => (
                <ShortcutHint key={item.key} keys={item.key} label={item.label} active={item.enabled} />
              ))}
            </div>
          </section>
        </div>
        <div className="min-h-0 space-y-4 overflow-auto pr-1">
          <section className="control-room-panel p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <PanelHeader title="Operator Scenes" icon={<PanelBottom size={14} strokeWidth={1.8} />} meta={`${savedOperatorScenes.length}/8 saved`} />
              <div className="flex flex-wrap items-center gap-2">
                <button type="button" onClick={saveCurrentScene} className="control-room-button">Save scene</button>
                <button type="button" onClick={exportSavedScenes} className="control-room-button">Export</button>
                <button type="button" onClick={() => sceneImportInputRef.current?.click()} className="control-room-button">Import</button>
              </div>
            </div>
            <div className="mt-4 grid gap-3 xl:grid-cols-2">
              {operatorScenes.map((scene) => (
                <OperatorSceneCard key={`desk-${scene.id}`} scene={scene} />
              ))}
            </div>
          </section>
          <section className="control-room-panel p-4">
            <PanelHeader title="Saved Local Scenes" meta={`${savedOperatorScenes.length}/8 saved`} />
            {savedOperatorSceneCards.length > 0 ? (
              <div className="grid gap-3 xl:grid-cols-2">
                {savedOperatorScenes.map((scene, index) => (
                  <div key={scene.id} className="rounded-lg border border-slate-800 bg-[#0b121a] p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-[13px] font-semibold text-slate-100">{scene.name}</p>
                        <p className="mt-2 text-[12px] text-slate-400">
                          {scene.state.preset !== "custom"
                            ? `${cleanLabel(scene.state.preset)} · ${scene.state.scope} event stream`
                            : `${scene.state.symbol} · ${scene.state.structureFocus ? `${cleanLabel(scene.state.structureFocus)} focus` : "desk posture"}`}
                        </p>
                        <p className="mt-2 text-[11px] text-slate-500">saved {formatTimestamp(scene.savedAt)}</p>
                        {savedOperatorSceneCards[index]?.active ? <TerminalBadge label="active" status="good" /> : null}
                      </div>
                      <div className="flex flex-col gap-2">
                        <button type="button" onClick={() => restoreSavedScene(scene)} className="control-room-mini-button">Restore</button>
                        <button type="button" onClick={() => renameSavedScene(scene.id)} className="control-room-mini-button">Rename</button>
                        <button type="button" onClick={() => toggleDefaultSavedScene(scene.id)} className="control-room-mini-button">
                          {scene.isDefault ? "Unset" : "Default"}
                        </button>
                        <button type="button" onClick={() => deleteSavedScene(scene.id)} className="control-room-mini-button danger">Delete</button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="rounded-lg border border-slate-800 bg-[#0b121a] px-4 py-4 text-sm text-slate-500">
                No saved local scenes yet. Save the current desk once you have a posture you want to reuse.
              </p>
            )}
          </section>
        </div>
      </div>
    );
  };

  return (
    <div className="h-[100dvh] min-w-[1180px] overflow-auto bg-[#070a0f] text-slate-100">
      <input
        ref={sceneImportInputRef}
        type="file"
        accept="application/json,.json"
        className="hidden"
        onChange={(event) => {
          void importSavedScenes(event);
        }}
      />
      <div className="mx-auto flex min-h-full max-w-[1600px] p-4">
        <aside className="control-room-sidebar">
          <div className="control-room-brand">TO</div>
          {workspaceTabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              title={tab.meta}
              onClick={() => setWorkspaceTab(tab.id)}
              className={`control-room-nav-button ${workspaceTab === tab.id ? "active" : ""}`}
            >
              {tab.label.slice(0, 3)}
            </button>
          ))}
          <button
            type="button"
            title="Command palette"
            onClick={() => setCommandPaletteOpen(true)}
            className="control-room-nav-button mt-auto"
          >
            Cmd
          </button>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col border border-slate-800/90 bg-[#090e14]/95 shadow-[0_22px_70px_rgba(0,0,0,0.34)]">
          <header className="flex min-h-[72px] shrink-0 flex-wrap items-center justify-between gap-4 border-b border-slate-800 bg-[#0b1118] px-5 py-3">
            <div>
              <h1 className="text-[20px] font-bold tracking-[-0.01em] text-slate-50">Trading Operations Control Room</h1>
              <p className="mt-1 text-[12px] text-slate-400">
                {selectedSymbol} perpetual · {snapshot?.health.bybit_env ?? "paper"} mode · {latestVisibleSessionLabel}
              </p>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2">
              {(rules?.allowed_instruments ?? ["BTCUSDT", "ETHUSDT"]).map((symbol) => (
                <button
                  key={symbol}
                  type="button"
                  onClick={() => setSelectedSymbol(symbol)}
                  className={`control-room-chip ${selectedSymbol === symbol ? "active" : ""}`}
                >
                  {symbol}
                </button>
              ))}
              <span className={`control-room-chip ${readinessStatus === "healthy_primary" ? "good" : readinessStatus === "degraded_fallback" ? "warn" : "danger"}`}>
                {formatOperatorStatusLabel(readinessStatus)}
              </span>
              <span className="control-room-chip">{snapshot?.health.bybit_env === "demo" ? "Demo venue" : "Local venue"}</span>
              <span className={`control-room-chip ${globalControl.effective?.paused ? "danger" : "good"}`}>
                {globalControl.effective?.paused ? "Emergency stop engaged" : "Emergency stop clear"}
              </span>
              <button type="button" onClick={() => setReviewDrawerOpen(true)} className="control-room-button">
                Review deck
              </button>
              <button
                type="button"
                onClick={() => void toggleGlobalKillSwitch(!Boolean(globalControl.effective?.paused))}
                className={`control-room-button ${globalControl.effective?.paused ? "good" : "danger"}`}
              >
                {globalControl.effective?.paused ? "Release stop" : "Emergency stop"}
              </button>
            </div>
          </header>

          <main className="grid min-h-0 flex-1 grid-rows-[auto_minmax(0,1fr)_auto] gap-4 overflow-auto p-4">
            {(error || tickerErrors.length > 0 || actionState.status !== "idle") ? (
              <section className="grid gap-2">
                {error ? <div className="control-room-alert danger">{error}</div> : null}
                {tickerErrors.length > 0 ? (
                  <div className="control-room-alert warn">
                    Ticker feed is partially degraded: {tickerErrors.map((item) => `${item.instrument} ${item.message}`).join(" · ")}
                  </div>
                ) : null}
                {actionState.status !== "idle" && actionState.message ? (
                  <div className={`control-room-alert ${actionState.status === "success" ? "good" : actionState.status === "error" ? "danger" : "info"}`}>
                    {actionState.message}
                  </div>
                ) : null}
              </section>
            ) : null}

            <section className="grid shrink-0 grid-cols-4 border border-slate-800 bg-[#0d141d]">
              <div className="control-room-decision-cell">
                <p className="control-room-eyebrow">Operator signal</p>
                <p className={`control-room-metric ${actionabilityTone}`}>{actionabilityLabel}</p>
                <p className="control-room-copy">{actionabilityDetail}</p>
              </div>
              <div className="control-room-decision-cell">
                <p className="control-room-eyebrow">Primary blocker</p>
                <p className="control-room-metric small">{primaryBlockerLabel}</p>
                <p className="control-room-copy">
                  {topReadinessBlocker?.summary ?? formatSessionAwareCopy(dominantBlocker === "n/a" ? "No dominant blocker recorded." : dominantBlocker, outsideSessionAllowed)}
                </p>
              </div>
              <div className="control-room-decision-cell">
                <p className="control-room-eyebrow">Risk posture</p>
                <p className={`control-room-metric small ${riskPostureTone}`}>{riskPostureLabel}</p>
                <p className="control-room-copy">{riskPostureDetail}</p>
              </div>
              <div className="control-room-decision-cell border-r-0">
                <p className="control-room-eyebrow">Next action</p>
                <p className="control-room-metric small text-cyan-200">{workflow.nextAction}</p>
                <p className="control-room-copy">Use the review deck for raw evidence and linked lifecycle details.</p>
              </div>
            </section>

            <section className="grid min-h-[640px] gap-4 xl:grid-cols-[minmax(0,1fr)_390px]">
              <article className="control-room-panel flex min-h-0 flex-col overflow-hidden">
                <div className="flex min-h-[58px] shrink-0 flex-wrap items-center justify-between gap-3 border-b border-slate-800 px-4 py-3">
                  <div>
                    <h2 className="text-[15px] font-bold tracking-[-0.01em] text-slate-100">ICT Structure Chart</h2>
                    <p className="mt-1 text-[12px] text-slate-500">
                      Clean overlays only · {rules?.timeframes.bias ?? "4H"} bias · {rules?.timeframes.setup ?? "15m"} setup · {rules?.timeframes.execution ?? "5m"} execution
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="control-room-segmented">
                      {CHART_TIMEFRAME_OPTIONS.map((option) => (
                        <button
                          key={option.value}
                          type="button"
                          onClick={() => setSelectedTimeframe(option.value)}
                          className={`control-room-segment ${selectedTimeframe === option.value ? "active" : ""}`}
                        >
                          {option.label}
                        </button>
                      ))}
                    </div>
                    <button type="button" onClick={() => setReviewDrawerOpen(true)} className="control-room-button">
                      Inspect
                    </button>
                  </div>
                </div>
                <div className="min-h-0 flex-1 p-2">
                  {chartError ? (
                    <div className="control-room-alert danger">{chartError}</div>
                  ) : (
                    <TerminalChart
                      symbol={selectedSymbol}
                      candles={candles}
                      proposal={currentProposal}
                      execution={activeExecution ?? lastExecution}
                      structure={selectedIctStructure}
                      selectedStructureFocus={effectiveStructureFocus}
                      structureFocusSource={structureFocusSource}
                      onFocusStructure={handleFocusStructure}
                      selectedTimeframe={selectedTimeframe}
                      ictContext={{
                        biasTimeframe: rules?.timeframes.bias ?? "4H",
                        setupTimeframe: rules?.timeframes.setup ?? "15m",
                        executionTimeframe: rules?.timeframes.execution ?? "5m",
                        sessionLabel: latestVisibleSessionLabel,
                        sessionValid: Boolean(snapshot?.session_context.session_valid),
                        direction: latestScan?.direction || "not_aligned",
                        decision: latestScan?.decision || "no_scan",
                        dominantBlocker,
                        operatorSignal,
                      }}
                      workflow={workflow}
                      selectedMarkerId={selectedTimelineEvent?.id ?? null}
                      markers={chartMarkers}
                      status={{
                        signal: currentSignal,
                        tradeState: currentTradeState,
                        session: latestVisibleSessionLabel,
                        verdict: conceptRecommendation,
                        operatorSignal,
                      }}
                    />
                  )}
                </div>
              </article>

              <aside className="control-room-panel min-h-0 overflow-auto">
                <section className="border-b border-slate-800 p-4">
                  <p className="control-room-eyebrow">Actionability</p>
                  <div className={`rounded-lg border p-4 ${
                    actionabilityTone.includes("emerald")
                      ? "border-emerald-400/25 bg-emerald-500/10"
                      : actionabilityTone.includes("cyan")
                        ? "border-cyan-400/25 bg-cyan-500/10"
                        : "border-amber-400/25 bg-amber-500/10"
                  }`}>
                    <p className={`text-[24px] font-bold tracking-[-0.02em] ${actionabilityTone}`}>{actionabilityLabel}</p>
                    <p className="mt-2 text-[12px] leading-5 text-slate-300">{actionabilityDetail}</p>
                  </div>
                </section>

                <section className="border-b border-slate-800 p-4">
                  <p className="control-room-eyebrow">House-rule checklist</p>
                  <div className="mt-3 grid gap-2">
                    {conceptLabMeters.map((item) => (
                      <div key={item.label} className="grid grid-cols-[1fr_auto] items-center gap-3 rounded-lg border border-slate-800 bg-[#0b121a] px-3 py-2">
                        <div>
                          <p className="text-[13px] font-semibold text-slate-100">{item.label}</p>
                          <p className="mt-1 text-[11px] text-slate-500">{item.detail}</p>
                        </div>
                        <span className={`h-2.5 w-2.5 rounded-full ${
                          item.tone === "good" ? "bg-emerald-300" : item.tone === "warn" ? "bg-amber-300" : item.tone === "danger" ? "bg-rose-300" : "bg-cyan-300"
                        }`} />
                      </div>
                    ))}
                  </div>
                </section>

                <section className="border-b border-slate-800 p-4">
                  <p className="control-room-eyebrow">Risk controls</p>
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    <div className="control-room-risk-tile">
                      <span>Kill switch</span>
                      <strong className={globalControl.effective?.paused ? "text-rose-200" : "text-emerald-200"}>
                        {globalControl.effective?.paused ? "Engaged" : "Clear"}
                      </strong>
                    </div>
                    <div className="control-room-risk-tile">
                      <span>Submission</span>
                      <strong className={orderSubmissionControl.effective?.paused ? "text-amber-100" : "text-emerald-200"}>
                        {orderSubmissionControl.effective?.paused ? "Paused" : "Live"}
                      </strong>
                    </div>
                    <div className="control-room-risk-tile">
                      <span>Auto execution</span>
                      <strong className={autoExecutionControl.effective?.paused ? "text-amber-100" : "text-emerald-200"}>
                        {autoExecutionControl.effective?.paused ? "Paused" : "Live"}
                      </strong>
                    </div>
                    <div className="control-room-risk-tile">
                      <span>Management</span>
                      <strong className={tradeManagementControl.effective?.paused ? "text-amber-100" : "text-emerald-200"}>
                        {tradeManagementControl.effective?.paused ? "Paused" : "Live"}
                      </strong>
                    </div>
                  </div>
                  <div className="mt-3 grid gap-2 md:grid-cols-2">
                    <ActionButton
                      label={orderSubmissionControl.effective?.paused ? "Resume submission" : "Pause submission"}
                      tone={orderSubmissionControl.effective?.paused ? "good" : "warn"}
                      busy={actionState.status === "pending" && actionState.actionKey === "order_submission"}
                      onClick={() =>
                        void toggleControl(
                          "order_submission",
                          !Boolean(orderSubmissionControl.effective?.paused),
                          !Boolean(orderSubmissionControl.effective?.paused)
                            ? "paused from trading web dashboard"
                            : "resumed from trading web dashboard",
                          !Boolean(orderSubmissionControl.effective?.paused)
                            ? "Order submission paused."
                            : "Order submission resumed.",
                        )
                      }
                    />
                    <ActionButton
                      label={autoExecutionControl.effective?.paused ? "Resume auto" : "Pause auto"}
                      tone={autoExecutionControl.effective?.paused ? "good" : "warn"}
                      busy={actionState.status === "pending" && actionState.actionKey === "auto_execution"}
                      onClick={() =>
                        void toggleControl(
                          "auto_execution",
                          !Boolean(autoExecutionControl.effective?.paused),
                          !Boolean(autoExecutionControl.effective?.paused)
                            ? "paused from trading web dashboard"
                            : "resumed from trading web dashboard",
                          !Boolean(autoExecutionControl.effective?.paused)
                            ? "Auto execution paused."
                            : "Auto execution resumed.",
                        )
                      }
                    />
                    <ActionButton
                      label={tradeManagementControl.effective?.paused ? "Resume management" : "Pause management"}
                      tone={tradeManagementControl.effective?.paused ? "good" : "warn"}
                      busy={actionState.status === "pending" && actionState.actionKey === "trade_management"}
                      onClick={() =>
                        void toggleControl(
                          "trade_management",
                          !Boolean(tradeManagementControl.effective?.paused),
                          !Boolean(tradeManagementControl.effective?.paused)
                            ? "paused from trading web dashboard"
                            : "resumed from trading web dashboard",
                          !Boolean(tradeManagementControl.effective?.paused)
                            ? "Trade management paused."
                            : "Trade management resumed.",
                        )
                      }
                    />
                    <ActionButton
                      label={globalControl.effective?.paused ? "Release stop" : "Emergency stop"}
                      tone={globalControl.effective?.paused ? "good" : "danger"}
                      busy={actionState.status === "pending" && actionState.actionKey === "global"}
                      onClick={() => void toggleGlobalKillSwitch(!Boolean(globalControl.effective?.paused))}
                    />
                  </div>
                </section>

                <section className="border-b border-slate-800 p-4">
                  <p className="control-room-eyebrow">Order plan</p>
                  <div className="mt-3 grid grid-cols-3 gap-2">
                    <div className="control-room-risk-tile"><span>Entry</span><strong className="text-cyan-200">{formatPrice(focusedEntry)}</strong></div>
                    <div className="control-room-risk-tile"><span>Stop</span><strong className="text-rose-200">{formatPrice(focusedStop)}</strong></div>
                    <div className="control-room-risk-tile"><span>Target</span><strong className="text-amber-100">{formatPrice(focusedTarget)}</strong></div>
                  </div>
                  <div className="mt-3 grid grid-cols-3 gap-2">
                    <ActionButton
                      label="Submit plan"
                      tone="good"
                      disabled={!showSubmitAction}
                      busy={actionState.status === "pending" && actionState.actionKey === "submit-proposal"}
                      onClick={() => void handleSubmitProposal()}
                    />
                    <ActionButton
                      label="Sync order"
                      tone="neutral"
                      disabled={!showSyncAction}
                      busy={actionState.status === "pending" && actionState.actionKey === "sync-proposal"}
                      onClick={() => void handleSyncProposal()}
                    />
                    <ActionButton
                      label="Cancel order"
                      tone="danger"
                      disabled={!showCancelAction}
                      busy={actionState.status === "pending" && actionState.actionKey === "cancel-proposal"}
                      onClick={() => void handleCancelProposal()}
                    />
                  </div>
                  <p className="mt-3 text-[12px] text-slate-500">
                    {focusedProposal ? `${focusedProposal.proposal_id} · ${focusedProposal.side} · ${focusedVenue}` : "No active proposal is currently linked to this market."}
                  </p>
                </section>

                <section className="p-4">
                  <p className="control-room-eyebrow">Runtime Surfaces</p>
                  <div className="mt-3 grid gap-3">
                    <div className="rounded-lg border border-slate-800 bg-[#0b121a] p-3">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-[13px] font-semibold text-slate-100">Public Event Stream</p>
                        <TerminalBadge label={formatOperatorStatusLabel(publicEventStreamStatus)} status={publicEventStreamBadgeStatus(publicEventStreamStatus)} />
                      </div>
                      <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-slate-500">
                        <span title={rawStatusTitle("connection", publicEventStreamConnection)}>Connection: {formatOperatorStatusLabel(publicEventStreamConnection)}</span>
                        <span title={rawStatusTitle("event_path_state", publicEventStreamPathState)}>Path: {formatOperatorStatusLabel(publicEventStreamPathState)}</span>
                        <span title={rawStatusTitle("last_public_event_at", publicEventStream.last_public_event_at)}>Last close: {publicEventStream.last_public_event_at ? formatRelativeTime(publicEventStream.last_public_event_at) : "-"}</span>
                        <span title={rawStatusTitle("fallback_active", publicEventStreamFallbackActive)}>Fallback: {publicEventStreamFallbackActive ? "active" : "standby"}</span>
                      </div>
                      <p className="mt-2 text-[11px] text-slate-600">{publicEventStreamSummary}</p>
                    </div>

                    <div className="rounded-lg border border-slate-800 bg-[#0b121a] p-3">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-[13px] font-semibold text-slate-100">Shadow Review</p>
                        <TerminalBadge label={`${shadowReviewSummary?.trace_count ?? 0} traces`} status={(shadowReviewSummary?.trace_count ?? 0) > 0 ? "good" : "neutral"} />
                      </div>
                      <p className="mt-2 text-[11px] text-slate-500">
                        {selectedSymbol}: {selectedShadowTraceCount} · top state {shadowTopState ? formatOperatorStatusLabel(shadowTopState, outsideSessionAllowed) : "none"} · top blocker {shadowTopBlocker ? formatBlockerClassLabel(shadowTopBlocker, outsideSessionAllowed) : "none"}
                      </p>
                      <p className="mt-2 text-[11px] text-slate-600">
                        {latestShadowBlockerCluster
                          ? `${formatSessionAwareCopy(latestShadowBlockerCluster.reason, outsideSessionAllowed)} · ${latestShadowBlockerCluster.count} trace${latestShadowBlockerCluster.count === 1 ? "" : "s"}`
                          : "No clustered blocker summary yet."}
                      </p>
                    </div>

                    <div className="rounded-lg border border-slate-800 bg-[#0b121a] p-3">
                      <p className="text-[13px] font-semibold text-slate-100">Signal Traces</p>
                      <div className="mt-2 grid gap-2">
                        {latestSignalTraces.length > 0 ? latestSignalTraces.map((item) => (
                          <div key={item.trace_id} className="rounded border border-slate-800 bg-[#091018] px-2 py-2">
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-[12px] text-slate-200" title={rawStatusTitle("decision", item.decision)}>
                                {item.symbol} · {formatOperatorStatusLabel(item.decision, outsideSessionAllowed)}
                              </span>
                              <TerminalBadge label={item.execution_eligible ? "Executable" : "Not executable"} status={item.execution_eligible ? "good" : "neutral"} />
                            </div>
                            <p className="mt-1 text-[11px] text-slate-500" title={`${rawStatusTitle("opportunity_state", item.opportunity_state)} · ${rawStatusTitle("blocker_class", item.blocker_class)}`}>
                              {formatOperatorStatusLabel(item.opportunity_state ?? "unknown", outsideSessionAllowed)} · {formatBlockerClassLabel(item.blocker_class ?? "no_blocker", outsideSessionAllowed)}
                            </p>
                          </div>
                        )) : <p className="text-sm text-slate-500">No recent signal traces for this symbol yet.</p>}
                      </div>
                    </div>

                    <div className="rounded-lg border border-slate-800 bg-[#0b121a] p-3">
                      <p className="text-[13px] font-semibold text-slate-100">Execution Intents</p>
                      <div className="mt-2 grid gap-2">
                        {latestExecutionIntents.length > 0 ? latestExecutionIntents.map((item) => (
                          <div key={item.intent_id} className="rounded border border-slate-800 bg-[#091018] px-2 py-2">
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-[12px] text-slate-200">{item.symbol} · {item.intent_id}</span>
                              <TerminalBadge label={formatOperatorStatusLabel(item.state)} status={executionIntentBadgeStatus(item.state)} />
                            </div>
                            <p className="mt-1 text-[11px] text-slate-500">
                              {formatOperatorStatusLabel(item.opportunity_state ?? "no_opportunity", outsideSessionAllowed)} · {item.proposal_id ?? "no proposal"}
                            </p>
                          </div>
                        )) : <p className="text-sm text-slate-500">No execution intents exist for this symbol in the current sample.</p>}
                      </div>
                    </div>

                    <div className="rounded-lg border border-slate-800 bg-[#0b121a] p-3">
                      <p className="text-[13px] font-semibold text-slate-100">Risk Checks</p>
                      <div className="mt-2 grid gap-2">
                        {latestExecutionRiskChecks.length > 0 ? latestExecutionRiskChecks.map((item) => (
                          <div key={item.risk_check_id} className="rounded border border-slate-800 bg-[#091018] px-2 py-2">
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-[12px] text-slate-200">{item.symbol ?? selectedSymbol} · {item.risk_check_id}</span>
                              <span title={rawStatusTitle("risk state", item.state)}>
                                <TerminalBadge label={formatOperatorStatusLabel(item.state)} status={riskCheckBadgeStatus(item.state)} />
                              </span>
                            </div>
                            <p className="mt-1 text-[11px] text-slate-500">{item.primary_reason ?? "No primary risk reason recorded."}</p>
                          </div>
                        )) : <p className="text-sm text-slate-500">No recent execution risk checks for this symbol yet.</p>}
                      </div>
                    </div>
                  </div>
                </section>
              </aside>
            </section>

            <section className="grid gap-4 xl:grid-cols-[1fr_0.9fr_0.8fr]">
              <article className="control-room-panel p-4">
                <PanelHeader title="Execution Lifecycle" meta={recentLifecycleRows.length > 0 ? `${recentLifecycleRows.length} active surfaces` : "awaiting surfaces"} icon={<TrainFront size={14} strokeWidth={1.8} />} />
                {recentLifecycleRows.length > 0 ? (
                  <div className="grid gap-2">
                    {recentLifecycleRows.map((item) => (
                      <div key={item.id} className="grid grid-cols-[132px_1fr_auto] items-center gap-3 border-b border-slate-800/80 py-2 last:border-b-0">
                        <span className="text-[12px] font-semibold text-slate-100">{item.stage}</span>
                        <span className="text-[12px] text-slate-400">{item.status} · {item.detail}</span>
                        <span className="text-[11px] text-slate-500">{item.updatedAt ? formatRelativeTime(item.updatedAt) : "-"}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-slate-500">No current trace, intent, or risk lifecycle row for this market yet.</p>
                )}
              </article>

              <article className="control-room-panel p-4">
                <PanelHeader title="Shadow Evidence" meta={shadowReviewSummary ? formatRelativeTime(shadowReviewSummary.computed_at) : "no shadow sample"} icon={<FileSearch size={14} strokeWidth={1.8} />} />
                <p className="control-room-metric small">{shadowReviewSummary?.trace_count ?? 0} traces</p>
                <p className="control-room-copy">
                  Potential misses: {shadowReviewSummary?.false_negative_candidate_count ?? 0} · {selectedSymbol}: {selectedShadowTraceCount}
                </p>
                <div className="mt-3 h-2 overflow-hidden rounded-full border border-slate-800 bg-[#091018]">
                  <div className="h-full rounded-full bg-gradient-to-r from-cyan-300 to-emerald-300" style={{ width: `${Math.min(100, Math.max(8, (shadowReviewSummary?.trace_count ?? 0) / 3))}%` }} />
                </div>
              </article>

              <article className="control-room-panel p-4">
                <PanelHeader title="System Notes" meta={formatRelativeTime(lastStreamAt)} icon={<Cable size={14} strokeWidth={1.8} />} />
                <div className="grid gap-2 text-[12px]">
                  <div className="flex justify-between gap-3"><span className="text-slate-500">Event path</span><strong className={readinessStatus === "healthy_primary" ? "text-emerald-200" : "text-amber-100"}>{formatOperatorStatusLabel(readinessStatus)}</strong></div>
                  <div className="flex justify-between gap-3"><span className="text-slate-500">Fallback polling</span><strong className={publicEventStreamFallbackActive ? "text-amber-100" : "text-slate-200"}>{publicEventStreamFallbackActive ? "Active" : "Standby"}</strong></div>
                  <div className="flex justify-between gap-3"><span className="text-slate-500">Private submission</span><strong className={orderSubmissionControl.effective?.paused ? "text-amber-100" : "text-emerald-200"}>{orderSubmissionControl.effective?.paused ? "Paused" : "Live"}</strong></div>
                  <div className="flex justify-between gap-3"><span className="text-slate-500">Candidate %</span><strong className="text-slate-200">{candidateRatio}</strong></div>
                </div>
              </article>
            </section>

            <section className="control-room-panel p-4">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="control-room-eyebrow">Command surface</p>
                  <h2 className="text-[17px] font-bold tracking-[-0.01em] text-slate-100">
                    {workspaceTabs.find((tab) => tab.id === workspaceTab)?.label ?? "Console"}
                  </h2>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {workspaceTabs.map((tab) => (
                    <WorkspaceTabButton
                      key={tab.id}
                      label={tab.label}
                      meta={tab.meta}
                      icon={tab.icon}
                      active={workspaceTab === tab.id}
                      onClick={() => setWorkspaceTab(tab.id)}
                    />
                  ))}
                </div>
              </div>
              {renderWorkspaceSurface()}
            </section>
          </main>
        </div>
      </div>

      {loading && !snapshot ? (
        <div className="pointer-events-none fixed bottom-4 right-4 rounded-lg border border-slate-800 bg-[#0b121a]/95 px-4 py-3 text-sm text-slate-400 shadow-[0_12px_40px_rgba(0,0,0,0.28)]">
          Loading operations control room...
        </div>
      ) : null}

      <CommandPalette
        open={commandPaletteOpen}
        query={commandPaletteQuery}
        onQueryChange={setCommandPaletteQuery}
        onClose={() => {
          setCommandPaletteOpen(false);
          setCommandPaletteQuery("");
        }}
        actions={filteredCommandPaletteActions}
        selectedIndex={commandPaletteIndex}
        onSelectIndex={setCommandPaletteIndex}
        onRunAction={runCommandPaletteAction}
      />

      <ReviewDrawer
        open={reviewDrawerOpen}
        onClose={() => setReviewDrawerOpen(false)}
        symbol={selectedSymbol}
        structure={selectedIctStructure}
        focusedStructure={effectiveStructureFocus}
        structureFocusSource={structureFocusSource}
        focusedStructureEventTitle={selectedTimelineEvent?.title ?? null}
        onFocusStructure={handleFocusStructure}
        latestScan={latestScan}
        conceptRuntime={conceptRuntime}
        compareSummary={conceptRevisionCompare}
        stage7Summary={conceptStage7Decision}
        stageStatus={conceptStageStatus}
        conceptEvents={conceptEvents}
        executionActions={selectedExecutionActions}
        timeline={selectedTimeline}
        allowedSessions={allowedSessions}
        outsideSessionAllowed={outsideSessionAllowed}
      />
    </div>
  );

}
