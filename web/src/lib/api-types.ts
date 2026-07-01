export type HealthResponse = {
  status: string;
  service: string;
  strategy_version: string;
  db_path: string;
  bybit_env: string;
  bybit_market_base_url: string;
  bybit_private_base_url: string;
  bybit_private_submit_enabled: boolean;
  bybit_credentials_configured: boolean;
  operator_auth_configured: boolean;
  global_control_paused: boolean;
  global_control_reason: string | null;
};

export type ReadinessResponse = {
  status: string;
  service: string;
  checked_at: string;
  critical_component_count: number;
  blocker_count: number;
  blockers: Array<{
    component_key: string;
    status: string;
    summary: string;
  }>;
  operations: OperationsStatusResponse;
};

export type OperationsStatusResponse = {
  scanned_at: string;
  overall: {
    health: string;
    component_count: number;
    alert_count: number;
    counts_by_health: Record<string, number>;
  };
  components: OperationsComponentItem[];
};

export type OperationsComponentItem = {
  component_key: string;
  component_type: string;
  health: string;
  status: string;
  summary: string;
  details: Record<string, unknown>;
};

export type PublicEventStreamDetails = {
  connection_status?: string | null;
  event_path_state?: string | null;
  last_public_event_at?: string | null;
  last_public_event_age_seconds?: number | null;
  last_confirmed_close_processed_at?: string | null;
  last_confirmed_close_processed_age_seconds?: number | null;
  last_confirmed_close_reference_at?: string | null;
  last_fallback_poll_at?: string | null;
  last_fallback_carry_at?: string | null;
  fallback_active?: boolean | null;
  fallback_interval_seconds?: number | string | null;
  next_fallback_due_at?: string | null;
  next_fallback_due_in_seconds?: number | null;
  reconnect_count?: number | null;
  consecutive_event_errors?: number | null;
  last_error?: string | null;
};

export type ScanHistoryItem = {
  scan_id: string;
  created_at: string;
  source: string;
  scan_batch_id: string;
  instrument: string;
  category: string;
  decision: string;
  session: string;
  direction: string;
  scan_signature: string;
  candidate_logged: boolean;
  duplicate_candidate: boolean;
  journal_id: string | null;
};

export type SignalTraceItem = {
  trace_id: string;
  created_at: string;
  symbol: string;
  reference_timestamp: string;
  source_path: string;
  source_mode: string;
  decision: string;
  opportunity_state: string | null;
  shadow_mode: boolean;
  shadow_session_id: string | null;
  execution_eligible: boolean;
  blocker_class: string | null;
  primary_blocker_reason: string | null;
  session_state: string | null;
  narrative_state: string | null;
  context_state: string | null;
  scan_batch_id: string | null;
  scan_id: string | null;
  journal_id: string | null;
  webhook_id: string | null;
};

export type ProposalItem = {
  proposal_id: string;
  created_at: string;
  venue: string;
  status: string;
  symbol: string;
  side: string;
  order_type: string;
  qty: string;
  price: string;
  stop_loss: string | null;
  take_profit: string | null;
  webhook_id: string | null;
};

export type ExecutionStateItem = {
  proposal_id: string;
  updated_at: string;
  venue: string;
  symbol: string;
  sync_status: string;
  order_id: string | null;
  order_link_id: string | null;
  order_status: string | null;
  position_side: string | null;
  position_size: string | null;
  position_avg_price: string | null;
  unrealised_pnl: string | null;
};

export type ExecutionActionItem = {
  action_id: string;
  created_at: string;
  proposal_id: string;
  venue: string;
  action_type: string;
  status: string;
  order_id: string | null;
  order_link_id: string | null;
  symbol: string | null;
};

export type ExecutionIntentItem = {
  intent_id: string;
  created_at: string;
  updated_at: string;
  source_path: string | null;
  runtime_key: string | null;
  symbol: string;
  reference_timestamp: string | null;
  signal_trace_id: string | null;
  scan_id: string | null;
  scan_batch_id: string | null;
  scan_signature: string | null;
  decision: string | null;
  opportunity_state: string | null;
  state: string;
  terminal: boolean;
  proposal_id: string | null;
};

export type ExecutionRiskCheckItem = {
  risk_check_id: string;
  created_at: string;
  runtime_key: string | null;
  intent_id: string | null;
  proposal_id: string | null;
  symbol: string | null;
  state: string;
  primary_reason: string | null;
};

export type EventItem = {
  event_id: string;
  created_at: string;
  severity: string;
  event_type: string;
  summary: string;
  runtime_key?: string;
  proposal_id?: string | null;
  instrument?: string | null;
  symbol?: string | null;
};

export type ControlItem = {
  control_key: string;
  paused: boolean;
  reason: string | null;
  updated_at: string | null;
  effective?: {
    paused: boolean;
    reason: string | null;
  };
};

export type ConceptRuntimeItem = {
  runtime_key: string;
  updated_at: string;
  heartbeat_at: string;
  last_scan_at: string | null;
  last_summary: Record<string, unknown>;
  state: Record<string, unknown>;
};

export type ConceptReviewSummaryItem = {
  review_id: string;
  created_at: string;
  concept_id: string;
  source: string;
  author: string | null;
  review_kind: string;
  overall: string | null;
  recommendation: string | null;
  primary_blocker: string | null;
  summary: string;
};

export type ConceptRevisionSummaryItem = {
  revision_id: string;
  created_at: string;
  concept_id: string;
  source: string;
  author: string | null;
  focus: string | null;
  status: string | null;
  summary: string;
};

export type ConceptRevisionCompareSummary = {
  review_count: number;
  revision_count: number;
  compare_artifact_count: number;
  stage5_readiness?: {
    stage: string;
    scope: string;
    status: string;
    score: number;
    ready_for_stage_6_from_daemon_state: boolean;
    summary: string;
    blockers: string[];
    checks: Array<{
      key: string;
      label: string;
      ok: boolean;
      required: boolean;
      detail: string;
    }>;
    metrics: {
      compare_artifact_count: number;
      leader_revision_id: string | null;
      latest_compare_verdict: string | null;
      latest_compare_review_id: string | null;
      stability_cycles: number;
      evaluation_history_count: number;
      last_changed_at: string | null;
    };
    caveat: string;
  };
  status_counts: Record<string, number>;
  focus_counts: Record<string, number>;
  source_counts: Record<string, number>;
  evaluation_history_count: number;
  latest_sample_started_at: string | null;
  takeaway: string;
  next_action: string;
  leader_explanation: string | null;
  compare_action: string | null;
  best_revision: {
    revision_id: string;
    review_id: string | null;
    focus: string | null;
    status: string | null;
    summary: string;
  } | null;
  best_ranked_revision: {
    revision_id: string;
    review_id: string | null;
    focus: string | null;
    status: string | null;
    summary: string;
    score: number;
    reasons: string[];
      history_count: number;
      latest_sample_started_at: string | null;
    } | null;
  latest_compare_artifact: {
    review_id: string;
    created_at: string | null;
    source: string | null;
    author: string | null;
    review_kind: string | null;
    summary: string | null;
    verdict: string | null;
    leader_revision_id: string | null;
    challenger_revision_id: string | null;
    comparison_summary: string | null;
    primary_risk: string | null;
    next_action_type: string | null;
    next_action_focus: string | null;
    next_action_summary: string | null;
    what_would_change_my_mind: string | null;
    confidence: string | null;
    grounding_refs_used: string[];
  } | null;
  latest_revision: {
    revision_id: string;
    review_id: string | null;
    focus: string | null;
    status: string | null;
    summary: string;
  } | null;
  ranked_revisions: Array<{
    revision_id: string;
    review_id: string | null;
    focus: string | null;
    status: string | null;
    summary: string;
    score: number;
    reasons: string[];
    history_count: number;
    latest_sample_started_at: string | null;
  }>;
};

export type ConceptAcceptanceSummary = {
  acceptance_artifact_count: number;
  latest_acceptance_review_id: string | null;
  latest_acceptance_verdict: string | null;
  latest_acceptance_status: string | null;
  primary_blocker: string | null;
  takeaway: string;
  acceptance_explanation: string | null;
  acceptance_action: string | null;
  ready_for_stage_7: boolean;
  stability_cycles?: number;
  last_changed_at?: string | null;
  stalled_cycles?: number;
  last_progress_at?: string | null;
  progress_direction?: string | null;
  evidence_progress?: {
    thresholds: Array<{
      key: string;
      label: string;
      actual: number;
      required: number;
      met: boolean;
    }>;
    thresholds_total_count: number;
    thresholds_met_count: number;
    threshold_progress_ratio: number;
    next_needed_metric: string | null;
    next_needed_label: string | null;
    candidate_ratio: number;
    latest_counts: {
      recent_scans: number;
      recent_proposals: number;
      recent_actions: number;
      recent_execution_state: number;
      working_orders: number;
      open_positions: number;
    };
    progress_summary: string;
  };
  latest_acceptance_artifact: {
    review_id: string | null;
    created_at: string | null;
    review_kind: string | null;
    summary: string | null;
    verdict: string | null;
    stage6_status: string | null;
    primary_blocker: string | null;
    next_action_type: string | null;
    next_action_focus: string | null;
    next_action_summary: string | null;
    what_would_change_my_mind: string | null;
    confidence: string | null;
    grounding_refs_used: string[];
  } | null;
  acceptance_gate: {
    stage: string;
    status: string;
    stage6_started: boolean;
    ready_for_stage_7: boolean;
    summary: string;
    next_action: string;
    provisional_outcome: string;
    blockers: string[];
    checks: Array<{
      key: string;
      label: string;
      blocker_label: string;
      ok: boolean;
      required_for_stage6: boolean;
      required_for_stage7: boolean;
      detail: string;
    }>;
    metrics: {
      candidate_ratio: number;
      compare_artifact_count: number;
      review_count: number;
      revision_count: number;
      evaluation_history_count: number;
      leader_history_count: number;
      improved_count: number;
      regressed_count: number;
      leader_status: string;
    };
    caveat: string;
  };
};

export type ConceptAcceptanceHistoryItem = {
  entry_key: string;
  recorded_at: string;
  last_seen_at: string;
  cycles_seen: number;
  latest_acceptance_review_id: string | null;
  latest_acceptance_status: string | null;
  latest_acceptance_verdict: string | null;
  primary_blocker: string | null;
  acceptance_action: string | null;
  ready_for_stage_7: boolean;
  progress_direction: string | null;
  stalled_cycles: number;
  last_progress_at: string | null;
  progress_summary: string | null;
  thresholds_met_count: number;
  thresholds_total_count: number;
  next_needed_label: string | null;
  candidate_ratio: number;
  latest_counts: {
    recent_scans: number;
    recent_proposals: number;
    recent_actions: number;
    recent_execution_state: number;
  };
};

export type ConceptStage7DecisionSummary = {
  decision_artifact_count: number;
  latest_stage7_review_id: string | null;
  latest_stage7_verdict: string | null;
  latest_stage7_artifact: {
    review_id: string | null;
    created_at: string | null;
    review_kind: string | null;
    summary: string | null;
    verdict: string | null;
    stage7_readiness: string | null;
    primary_reason: string | null;
    supporting_evidence: string | null;
    next_action_type: string | null;
    next_action_focus: string | null;
    next_action_summary: string | null;
    what_would_change_my_mind: string | null;
    confidence: string | null;
    grounding_refs_used: string[];
  } | null;
  decision_takeaway: string;
  decision_action: string | null;
  stability_cycles?: number;
  last_changed_at?: string | null;
  stage7_gate: {
    stage: string;
    status: string;
    ready_for_stage_7: boolean;
    summary: string;
    next_action: string;
    suggested_path: string;
    primary_reason: string | null;
    blockers: string[];
    checks: Array<{
      key: string;
      label: string;
      blocker_label: string;
      ok: boolean;
      detail: string;
    }>;
    metrics: {
      candidate_ratio: number;
      acceptance_artifact_count: number;
      improved_count: number;
      regressed_count: number;
      leader_revision_id: string | null;
      leader_status: string | null;
      latest_compare_verdict: string | null;
    };
    caveat: string;
  };
};

export type ConceptStageStatusSummary = {
  roadmap_path: string;
  current_stage: {
    number: number;
    label: string;
  };
  next_stage: {
    number: number;
    label: string;
  } | null;
  status: string;
  summary: string;
  ready_for_next_stage: boolean;
  blockers: string[];
  current_focus: string;
  engineering_lane_complete: boolean;
  evidence_is_primary_constraint: boolean;
  diagnostics?: {
    operational_signal: string;
    explanation: string;
    progress_summary: string | null;
    stage5_ready: boolean;
    evidence_counts: {
      recent_scans: number;
      recent_proposals: number;
      recent_actions: number;
      recent_execution_state: number;
      working_orders: number;
      open_positions: number;
    };
    artifact_counts: {
      reviews: number;
      revisions: number;
      compare_artifacts: number;
      acceptance_artifacts: number;
      stage7_artifacts: number;
    };
    missing_thresholds: Array<{
      key: string;
      label: string;
      actual: number;
      required: number;
    }>;
    missing_artifacts: Array<{
      key: string;
      actual: number;
      required: number;
    }>;
    failed_checks: Array<{
      key: string;
      label: string;
      detail: string | null;
      required_for_stage7: boolean;
    }>;
  };
  metrics: {
    candidate_ratio: number;
    compare_artifact_count: number;
    acceptance_artifact_count: number;
    decision_artifact_count: number;
    leader_revision_id: string | null;
    leader_status: string | null;
    latest_compare_verdict: string | null;
    latest_stage7_verdict: string | null;
  };
};

export type ControlRoomTimelineItem = {
  id: string;
  created_at: string;
  source: string;
  kind: string;
  severity: string;
  event_type: string;
  title: string;
  summary: string;
  symbol: string | null;
  proposal_id: string | null;
  meta: string | null;
};

export type ShadowReviewSummary = {
  computed_at: string;
  trace_count: number;
  false_negative_candidate_count: number;
  by_decision: Record<string, number>;
  by_opportunity_state: Record<string, number>;
  by_blocker_class: Record<string, number>;
  by_symbol: Record<string, number>;
  by_session_state: Record<string, number>;
  by_shadow_session: Record<string, number>;
  blocker_clusters: Array<{
    reason: string;
    count: number;
    top_decisions: Record<string, number>;
    top_opportunity_states: Record<string, number>;
    top_symbols: Record<string, number>;
    top_session_states: Record<string, number>;
  }>;
  reference_window: {
    from: string | null;
    to: string | null;
  };
};

export type DashboardSnapshot = {
  built_at: string;
  stream_poll_seconds: number;
  session_context: {
    now_utc: string;
    now_new_york: string;
    active_session: string;
    session_valid: boolean;
    weekend: boolean;
  };
  health: HealthResponse;
  operations: OperationsStatusResponse;
  scans: ScanHistoryItem[];
  proposals: ProposalItem[];
  executionState: ExecutionStateItem[];
  executionActions: ExecutionActionItem[];
  autoEvents: EventItem[];
  controls: ControlItem[];
  rules: RulesResponse;
  tickers: TickerPayload[];
  ticker_errors: Array<{
    instrument: string;
    message: string;
    http_status: number | null;
  }>;
  ictStructures: Record<string, IctStructurePayload>;
  conceptRuntime: ConceptRuntimeItem | null;
  conceptEvents: EventItem[];
  conceptReviews: ConceptReviewSummaryItem[];
  conceptRevisions: ConceptRevisionSummaryItem[];
  conceptRevisionCompare: ConceptRevisionCompareSummary;
  conceptAcceptance: ConceptAcceptanceSummary | null;
  conceptAcceptanceHistory: ConceptAcceptanceHistoryItem[];
  conceptStage7Decision: ConceptStage7DecisionSummary | null;
  conceptStageStatus: ConceptStageStatusSummary | null;
  timeline: ControlRoomTimelineItem[];
};

export type IctStructurePayload = {
  symbol: string;
  updated_at: string | null;
  decision: string;
  direction: string;
  session: string;
  liquidity_draw: string;
  narrative: {
    state: string;
    array_support: string;
    reason: string;
  };
  drt: {
    state: string;
    open_objective: string;
    range_high: number | null;
    range_low: number | null;
    midpoint: number | null;
    location: string;
    internal_high: number | null;
    internal_low: number | null;
    external_high: number | null;
    external_low: number | null;
  };
  bias: {
    state: string;
    range_high: number | null;
    range_low: number | null;
    midpoint: number | null;
    location: string;
  };
  liquidity_event: {
    state: string;
    level: number | null;
    at: string | null;
    direction: string;
    narrative_hint: string;
    defended_side: string;
    body_direction: string;
    tolerance: number | null;
    reason: string;
  };
  sweep: {
    state: string;
    level: number | null;
    at: string | null;
    tolerance: number | null;
    profile: string | null;
  };
  mss: {
    state: string;
    level: number | null;
    at: string | null;
    broken_swing_at: string | null;
    tolerance: number | null;
    micro_break: boolean;
  };
  displacement: {
    state: string;
    at: string | null;
    mode: string | null;
    range_multiple: number | null;
    body_multiple: number | null;
  };
  fvg: {
    state: string;
    lower: number | null;
    upper: number | null;
    midpoint: number | null;
    at: string | null;
  };
  pd_array: {
    name: string;
    location: string;
    range_relation: string;
    respect_state: string;
    ifvg_candidate: boolean;
  };
  levels: {
    ok: boolean;
    entry_price: number | null;
    stop_loss: number | null;
    take_profit: number | null;
    target_at: string | null;
    target_source: string | null;
    rr_multiple: number | null;
    error: string | null;
  };
};

export type RulesResponse = {
  strategy_version: string;
  execution_mode: string;
  allowed_instruments: string[];
  approved_proxies: string[];
  timeframes: {
    bias: string;
    setup: string;
    execution: string;
  };
  allowed_sessions: string[];
  weekend_policy: string;
  required_checklist: string[];
  blocking_conditions: string[];
};

export type TickerPayload = {
  source: string;
  instrument: string;
  category: string;
  ticker: {
    symbol: string;
    lastPrice: string;
    prevPrice24h: string;
    price24hPcnt: string;
    highPrice24h: string;
    lowPrice24h: string;
    volume24h: string;
  };
};

export type Candle = {
  start_ms: number;
  start_at: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  turnover: number;
};

export type KlinesPayload = {
  source: string;
  instrument: string;
  category: string;
  interval: string;
  count: number;
  candles: Candle[];
};
