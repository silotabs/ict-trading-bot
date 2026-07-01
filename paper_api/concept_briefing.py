#!/usr/bin/env python3

import re
from pathlib import Path

from concept_review_response import build_llm_response_contract
from shared_utils import clean_string as clean_text, utc_now_iso


BASE_DIR = Path(__file__).resolve().parent
DOSSIER_DIR = BASE_DIR.parent / "dossier"
HOUSE_SPEC_PATH = DOSSIER_DIR / "08_house_spec.md"
REVIEW_RUBRIC_PATH = DOSSIER_DIR / "11_review_rubric.md"
PAPER_PROTOCOL_PATH = DOSSIER_DIR / "09_paper_trading_protocol.md"
EXECUTION_SPEC_SUMMARY_PATH = DOSSIER_DIR / "12_execution_spec.md"
NOT_READY_RULE_PATH = DOSSIER_DIR / "rules" / "00_not_ready_for_execution.md"
SOURCE_MAP_PATH = DOSSIER_DIR / "sources" / "initial-source-map.md"

def clean_markdown_line(value):
    text = clean_text(value) or ""
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text.strip()


def format_percent(value):
    try:
        return f"{float(value or 0.0):.0%}"
    except (TypeError, ValueError):
        return "0%"


def read_lines(path):
    try:
        return Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def extract_markdown_bullets(path):
    sections = {}
    current_h2 = None
    current_h3 = None
    for raw_line in read_lines(path):
        line = raw_line.rstrip()
        if line.startswith("## "):
            current_h2 = clean_text(line[3:])
            current_h3 = None
            continue
        if line.startswith("### "):
            current_h3 = clean_text(line[4:])
            continue
        if line.startswith("- "):
            key = (current_h2, current_h3)
            sections.setdefault(key, []).append(clean_markdown_line(line[2:]))
    return sections


def extract_key_value_bullets(items):
    result = {}
    for item in items or []:
        match = re.match(r"(?P<key>[^:]+):\s*(?P<value>.+)", item)
        if not match:
            continue
        key = clean_text(match.group("key"))
        value = clean_text(match.group("value"))
        if key and value:
            result[key] = value
    return result


def build_house_spec_snapshot():
    bullets = extract_markdown_bullets(HOUSE_SPEC_PATH)
    current_mode = extract_key_value_bullets(bullets.get(("Current Mode", None), []))
    scope = extract_key_value_bullets(bullets.get(("Scope", None), []))
    return {
        "mode": {
            "skill_status": current_mode.get("Skill status"),
            "execution_mode": current_mode.get("Execution mode"),
            "live_order_placement": current_mode.get("Live order placement"),
            "paper_trading": current_mode.get("Paper trading"),
        },
        "scope": {
            "instrument_universe": scope.get("Instrument universe"),
            "primary_market": scope.get("Primary market"),
            "bias_timeframe": scope.get("Bias timeframe"),
            "setup_timeframe": scope.get("Setup timeframe"),
            "execution_timeframe": scope.get("Execution timeframe"),
            "market_condition_focus": scope.get("Market condition focus"),
        },
        "version_1_cancels": bullets.get(("Version 1 Setup Model", "What Cancels Version 1"), [])[:8],
        "hard_safety_gates": bullets.get(("Hard Safety Gates", None), [])[:8],
        "promotion_gates": bullets.get(("Paper-Trading Promotion Gates", None), [])[:8],
    }


def build_review_rubric_snapshot():
    bullets = extract_markdown_bullets(REVIEW_RUBRIC_PATH)
    return {
        "grade_a": bullets.get(("Grade Each Trade", "A"), [])[:8],
        "grade_d": bullets.get(("Grade Each Trade", "D"), [])[:8],
        "weekly_questions": bullets.get(("Weekly Questions", None), [])[:8],
    }


def build_official_source_highlights(limit=3):
    items = []
    lines = read_lines(SOURCE_MAP_PATH)
    in_section = False
    current = None
    for raw_line in lines:
        line = raw_line.rstrip()
        if line.startswith("## "):
            in_section = clean_text(line[3:]) == "Official Brand / Official Channel"
            current = None
            continue
        if not in_section:
            continue
        if line.startswith("### "):
            if current and current.get("title") and current.get("url"):
                items.append(current)
                if len(items) >= limit:
                    break
            current = {"title": clean_text(line[4:]), "url": None, "why_it_matters": None}
            continue
        if current is None:
            continue
        if line.startswith("- URL:"):
            current["url"] = clean_text(line.split(":", 1)[1])
        elif line.startswith("- Why it matters:"):
            current["why_it_matters"] = clean_text(line.split(":", 1)[1])
    if len(items) < limit and current and current.get("title") and current.get("url"):
        items.append(current)
    return items[:limit]


def build_grounding_refs():
    return [
        {
            "label": "House Spec",
            "path": str(HOUSE_SPEC_PATH),
            "purpose": "Current ICT house rules, setup model, and hard safety gates.",
        },
        {
            "label": "Review Rubric",
            "path": str(REVIEW_RUBRIC_PATH),
            "purpose": "Trade-grading rubric and weekly review questions.",
        },
        {
            "label": "Paper Trading Protocol",
            "path": str(PAPER_PROTOCOL_PATH),
            "purpose": "Paper-trading workflow guardrails and journaling expectations.",
        },
        {
            "label": "Execution Spec Summary",
            "path": str(EXECUTION_SPEC_SUMMARY_PATH),
            "purpose": "Sizing and execution constraints for paper-trade planning.",
        },
        {
            "label": "Not Ready For Execution",
            "path": str(NOT_READY_RULE_PATH),
            "purpose": "Reminder that the research dossier is not a live-trading specification.",
        },
        {
            "label": "Initial Source Map",
            "path": str(SOURCE_MAP_PATH),
            "purpose": "Local provenance map for official and secondary ICT sources.",
        },
    ]


def build_llm_review_tasks(review, decision, house_spec):
    overall = clean_text(decision.get("overall")) or "observe"
    tasks = [
        "Validate whether the current recommendation matches the evidence, without proposing live order placement.",
        "Name the single highest-leverage next action: collect more evidence, revise one rule, or compare against the next concept.",
        "Keep all suggestions compatible with the local house spec, paper-trading protocol, and hard safety gates.",
    ]

    dominant = decision.get("dominant_blocker") or {}
    blocker_name = clean_text(dominant.get("blocker"))
    if blocker_name:
        tasks.append(
            f"Explain whether {blocker_name} looks like a real rules problem or a temporary market-condition problem."
        )

    largest_gap = decision.get("largest_gap") or {}
    if clean_text(largest_gap.get("blocker")):
        tasks.append(
            "Assess whether the BTC/ETH gap suggests asymmetric market structure or an uneven implementation of the setup rules."
        )

    unmet = decision.get("unmet_evidence") or []
    if unmet:
        tasks.append(
            "Say which missing evidence threshold matters most right now and what kind of additional evidence would clear it fastest."
        )

    auto_blocker = review.get("auto_execution_top_blocker") or {}
    if clean_text(auto_blocker.get("event_type")):
        tasks.append(
            f"Judge whether the proposal-conversion bottleneck ({auto_blocker.get('label')}) is a setup-quality issue or an execution-plumbing issue."
        )

    if overall == "collecting":
        tasks.append(
            "Do not recommend broad rule changes yet unless the current evidence already shows a repeated structural failure mode."
        )
    elif overall == "revise":
        tasks.append(
            "Recommend only one conservative rule revision at a time, and state what evidence would confirm that revision helped."
        )
    elif overall == "compare":
        tasks.append(
            "Confirm whether Concept 1 is actually ready for comparison, or whether one final observational pass is still warranted."
        )

    safety = ((house_spec or {}).get("mode") or {}).get("live_order_placement")
    if safety:
        tasks.append(f"Respect the current execution posture: {safety}.")

    return tasks[:7]


def build_revision_candidates(packet):
    decision = packet.get("decision") or {}
    evidence = packet.get("evidence") or {}
    pressure = packet.get("pressure_points") or {}
    dominant = pressure.get("dominant_blocker") or {}
    gap = pressure.get("cross_market_gap") or {}
    unmet = evidence.get("unmet_thresholds") or []

    candidates = []
    evidence_candidate = None

    if unmet:
        rendered = ", ".join(
            f"{item.get('metric')} {item.get('actual')}/{item.get('required')}" for item in unmet[:3]
        )
        revising_now = clean_text(decision.get("overall")) == "revise"
        evidence_candidate = {
            "id": "collect-evidence-first",
            "mode": "observe",
            "readiness": "later" if revising_now else "now",
            "focus": "evidence_thresholds",
            "title": (
                "Keep lifecycle evidence visible while reviewing one rule"
                if revising_now
                else "Keep collecting evidence before changing rules"
            ),
            "rationale": f"The concept is still below the minimum evidence threshold: {rendered}.",
            "guardrails": [
                "Do not relax core safety gates yet.",
                "Do not treat missing evidence as proof that the rules are wrong.",
                "Wait for one more proposal and one more execution-state row before judging promotion or comparison readiness.",
            ],
            "success_signals": [
                "Recent proposal count reaches the decision threshold.",
                "Recent execution-state count reaches the decision threshold.",
                "Fresh sample windows keep the harness healthy while evidence increases.",
            ],
            "abort_signals": [
                "The harness falls back to blocked or watch-heavy behavior.",
                "The evidence still does not grow after another meaningful session window.",
            ],
        }

    if clean_text(gap.get("blocker")) and float(gap.get("gap") or 0.0) >= 0.35:
        candidates.append(
            {
                "id": "review-cross-market-bias",
                "mode": "review",
                "readiness": "next_review_window" if (decision.get("overall") == "collecting") else "now",
                "focus": clean_text(gap.get("blocker")) or "cross_market_gap",
                "title": "Review the cross-market imbalance before broad rule relaxation",
                "rationale": (
                    f"{gap.get('blocker')} is materially stricter on "
                    f"{gap.get('highest_instrument') or 'one market'} "
                    f"({format_percent(gap.get('highest_ratio'))}) than on "
                    f"{gap.get('lowest_instrument') or 'the other market'} "
                    f"({format_percent(gap.get('lowest_ratio'))})."
                ),
                "guardrails": [
                    "Change only one market-structure heuristic at a time.",
                    "Do not relax session, sweep, or FVG safety gates while reviewing the bias heuristic.",
                    "Prefer explanation and calibration before a broad threshold reduction.",
                ],
                "success_signals": [
                    "BTC/ETH blocker gap narrows in the next clean replay sample.",
                    "Candidate flow improves without turning no-paper-trade scans into low-quality paper trades.",
                ],
                "abort_signals": [
                    "The gap remains wide after the review change.",
                    "Lower-quality candidates begin passing without producing better proposal conversion.",
                ],
            }
        )

    if clean_text(dominant.get("blocker")) and float(dominant.get("ratio") or 0.0) >= 0.35:
        blocker_name = clean_text(dominant.get("blocker")) or "dominant blocker"
        candidates.append(
            {
                "id": f"review-{blocker_name}",
                "mode": "review",
                "readiness": "later" if (decision.get("overall") == "collecting") else "now",
                "focus": blocker_name,
                "title": f"Prepare a one-variable review of {blocker_name}",
                "rationale": f"{blocker_name} is still leading the replay pressure at about {format_percent(dominant.get('ratio'))}.",
                "guardrails": [
                    "Review one threshold or interpretation rule only.",
                    "Keep the rest of the Version 1 setup model unchanged during the experiment.",
                    "Define ahead of time what evidence would count as improvement.",
                ],
                "success_signals": [
                    "Candidate ratio improves from zero without a surge in weak scans.",
                    "Proposal conversion becomes healthier after the blocker softens.",
                ],
                "abort_signals": [
                    "Candidate ratio stays flat after the rule review.",
                    "Proposal quality drops or cross-market imbalance gets worse.",
                ],
            }
        )

    if not candidates:
        if evidence_candidate is not None:
            candidates.append(evidence_candidate)
        else:
            candidates.append(
                {
                    "id": "continue-monitoring",
                    "mode": "observe",
                    "readiness": "now",
                    "focus": "concept_observation",
                    "title": "Continue monitoring the current concept state",
                    "rationale": "No single revision path is clearly justified yet.",
                    "guardrails": [
                        "Keep the concept under observation with the current house spec.",
                        "Do not introduce multiple simultaneous rule changes.",
                    ],
                    "success_signals": [
                        "A clearer blocker or stronger evidence threshold crossing appears.",
                    ],
                    "abort_signals": [
                        "The harness blocks again and invalidates the current observation window.",
                    ],
                }
            )
    elif evidence_candidate is not None:
        if clean_text(decision.get("overall")) == "collecting":
            candidates.insert(0, evidence_candidate)
        else:
            candidates.append(evidence_candidate)

    return candidates[:3]


def build_llm_handoff(packet):
    tasks = packet.get("llm_review_tasks") or []
    task_lines = "\n".join(f"{index}. {item}" for index, item in enumerate(tasks, start=1))
    return "\n".join(
        [
            "You are reviewing the current Concept 1 state for a conservative ICT paper-trading workflow.",
            "Stay analysis-only. Do not recommend live order placement, broker-ready execution, or unsafe automation shortcuts.",
            "Use the brief below, the listed local grounding files, and the hard safety gates as constraints.",
            "",
            "Return:",
            "1. A verdict on whether the current recommendation is sound.",
            "2. The primary blocker or evidence gap.",
            "3. One conservative next experiment or follow-up action.",
            "4. What evidence would change your mind.",
            "5. If a rule review is justified, keep it to one variable at a time.",
            "",
            "Review tasks:",
            task_lines or "1. Validate the current concept state conservatively.",
            "",
            packet.get("brief_markdown") or "",
        ]
    ).strip()


def build_concept_brief_packet(review, decision):
    review = review if isinstance(review, dict) else {}
    decision = decision if isinstance(decision, dict) else {}
    house_spec = build_house_spec_snapshot()
    rubric = build_review_rubric_snapshot()
    dominant = decision.get("dominant_blocker") or {}
    largest_gap = decision.get("largest_gap") or {}
    background_lab = review.get("background_lab") or {}
    evidence = decision.get("evidence") or {}
    review_evidence = review.get("evidence") or {}
    auto_blocker = review.get("auto_execution_top_blocker") or {}

    packet = {
        "generated_at": utc_now_iso(),
        "concept_id": clean_text((decision.get("policy") or {}).get("concept_id")) or "concept-1",
        "decision": {
            "overall": clean_text(decision.get("overall")),
            "recommendation": clean_text(decision.get("recommendation")),
            "operator_signal": clean_text(decision.get("operator_signal")),
            "operator_summary": clean_text(decision.get("operator_summary")),
        },
        "review": {
            "overall": clean_text(review.get("overall")),
            "recommendation": clean_text(review.get("recommendation")),
            "sample_window": review.get("sample_window") or {},
            "scan_mix": review.get("scan_mix") or {},
            "execution_mix": review.get("execution_mix") or {},
            "auto_execution_blocker_mix": review.get("auto_execution_blocker_mix") or {},
        },
        "evidence": {
            "recent_scans": int(evidence.get("recent_scan_count") or review_evidence.get("recent_scan_count") or 0),
            "recent_proposals": int(evidence.get("recent_proposal_count") or review_evidence.get("recent_proposal_count") or 0),
            "recent_actions": int(evidence.get("recent_action_count") or review_evidence.get("recent_action_count") or 0),
            "recent_execution_state": int(
                evidence.get("recent_execution_state_count")
                or review_evidence.get("recent_execution_state_count")
                or 0
            ),
            "working_orders": int(review_evidence.get("working_order_count") or 0),
            "open_positions": int(review_evidence.get("open_position_count") or 0),
            "unmet_thresholds": decision.get("unmet_evidence") or [],
        },
        "pressure_points": {
            "candidate_ratio": float(decision.get("candidate_ratio") or 0.0),
            "dominant_blocker": {
                "blocker": clean_text(dominant.get("blocker")),
                "ratio": float(dominant.get("ratio") or 0.0),
            },
            "cross_market_gap": {
                "blocker": clean_text(largest_gap.get("blocker")),
                "highest_instrument": clean_text((largest_gap.get("highest") or {}).get("instrument")),
                "highest_ratio": float(((largest_gap.get("highest") or {}).get("ratio")) or 0.0),
                "lowest_instrument": clean_text((largest_gap.get("lowest") or {}).get("instrument")),
                "lowest_ratio": float(((largest_gap.get("lowest") or {}).get("ratio")) or 0.0),
                "ratios": largest_gap.get("ratios") or {},
                "gap": float(largest_gap.get("gap") or 0.0),
            },
            "conversion_blocker": {
                "event_type": clean_text(auto_blocker.get("event_type")),
                "label": clean_text(auto_blocker.get("label")),
                "count": int(auto_blocker.get("count") or 0),
            },
        },
        "background_lab": {
            "overall": clean_text(background_lab.get("overall")),
            "recommendation": clean_text(background_lab.get("recommendation")),
            "candidate_ratio": float(background_lab.get("candidate_ratio") or 0.0),
            "dominant_blocker": clean_text(background_lab.get("dominant_blocker")),
            "dominant_blocker_ratio": float(background_lab.get("dominant_blocker_ratio") or 0.0),
            "operator_signal": clean_text(background_lab.get("operator_signal")),
            "operator_summary": clean_text(background_lab.get("operator_summary")),
            "updated_at": clean_text(background_lab.get("updated_at")),
        },
        "issues": [
            {
                "severity": clean_text(item.get("severity")),
                "code": clean_text(item.get("code")),
                "summary": clean_text(item.get("summary")),
            }
            for item in (decision.get("issues") or [])[:8]
        ],
        "next_focus": (decision.get("next_focus") or review.get("next_focus") or [])[:6],
        "house_spec": house_spec,
        "review_rubric": rubric,
        "grounding_refs": build_grounding_refs(),
        "official_source_highlights": build_official_source_highlights(),
    }
    packet["llm_review_tasks"] = build_llm_review_tasks(review, decision, house_spec)
    packet["revision_candidates"] = build_revision_candidates(packet)
    packet["llm_response_contract"] = build_llm_response_contract()
    packet["brief_markdown"] = render_concept_brief_markdown(packet)
    packet["llm_prompt"] = build_llm_handoff(packet)
    return packet


def render_concept_brief_markdown(packet):
    decision = packet.get("decision") or {}
    review = packet.get("review") or {}
    evidence = packet.get("evidence") or {}
    pressure = packet.get("pressure_points") or {}
    dominant = pressure.get("dominant_blocker") or {}
    gap = pressure.get("cross_market_gap") or {}
    conversion = pressure.get("conversion_blocker") or {}
    background_lab = packet.get("background_lab") or {}
    house_spec = packet.get("house_spec") or {}
    rubric = packet.get("review_rubric") or {}
    refs = packet.get("grounding_refs") or []
    source_highlights = packet.get("official_source_highlights") or []

    lines = [
        "# Concept 1 Review Brief",
        "",
        f"- Generated at: {packet.get('generated_at')}",
        f"- Decision: {(decision.get('overall') or '-')} / {(decision.get('recommendation') or '-')}",
        f"- Operator signal: {(decision.get('operator_signal') or '-')} — {(decision.get('operator_summary') or '-')}",
        f"- Review state: {(review.get('overall') or '-')} / {(review.get('recommendation') or '-')}",
        "",
        "## Evidence Snapshot",
        f"- Recent scans: {evidence.get('recent_scans', 0)}",
        f"- Recent proposals: {evidence.get('recent_proposals', 0)}",
        f"- Recent actions: {evidence.get('recent_actions', 0)}",
        f"- Recent execution-state rows: {evidence.get('recent_execution_state', 0)}",
        f"- Working orders: {evidence.get('working_orders', 0)}",
        f"- Open positions: {evidence.get('open_positions', 0)}",
    ]

    unmet = evidence.get("unmet_thresholds") or []
    if unmet:
        rendered = ", ".join(
            f"{item.get('metric')}={item.get('actual')}/{item.get('required')}" for item in unmet
        )
        lines.append(f"- Unmet thresholds: {rendered}")

    lines.extend(
        [
            "",
            "## Pressure Points",
            f"- Candidate ratio: {format_percent(pressure.get('candidate_ratio'))}",
            f"- Dominant blocker: {(dominant.get('blocker') or '-')} at {format_percent(dominant.get('ratio'))}",
        ]
    )

    if gap.get("blocker"):
        lines.append(
            "- Cross-market gap: "
            f"{gap.get('blocker')} gap {format_percent(gap.get('gap'))} "
            f"({gap.get('highest_instrument') or '-'} {format_percent(gap.get('highest_ratio'))}, "
            f"{gap.get('lowest_instrument') or '-'} {format_percent(gap.get('lowest_ratio'))})"
        )
    if conversion.get("event_type"):
        lines.append(
            f"- Proposal-conversion blocker: {(conversion.get('label') or conversion.get('event_type'))} "
            f"({conversion.get('count', 0)} recent events)"
        )
    if background_lab.get("overall"):
        lines.append(
            "- Background lab: "
            f"{background_lab.get('overall')} / {background_lab.get('recommendation')} "
            f"with {format_percent(background_lab.get('candidate_ratio'))} candidate ratio"
        )

    issues = packet.get("issues") or []
    if issues:
        lines.extend(["", "## Current Concerns"])
        for item in issues[:6]:
            lines.append(f"- {item.get('severity', 'info').upper()}: {item.get('summary')}")

    next_focus = packet.get("next_focus") or []
    if next_focus:
        lines.extend(["", "## Immediate Next Focus"])
        for item in next_focus:
            lines.append(f"- {item}")

    mode = house_spec.get("mode") or {}
    scope = house_spec.get("scope") or {}
    lines.extend(
        [
            "",
            "## House Guardrails",
            f"- Execution mode: {(mode.get('execution_mode') or '-')}",
            f"- Live order placement: {(mode.get('live_order_placement') or '-')}",
            "- Timeframe stack: "
            f"{scope.get('bias_timeframe') or '-'} / {scope.get('setup_timeframe') or '-'} / {scope.get('execution_timeframe') or '-'}",
        ]
    )
    for item in (house_spec.get("version_1_cancels") or [])[:4]:
        lines.append(f"- Cancel condition: {item}")
    for item in (house_spec.get("hard_safety_gates") or [])[:4]:
        lines.append(f"- Safety gate: {item}")

    lines.extend(["", "## Review Rubric Anchors"])
    for item in (rubric.get("grade_a") or [])[:4]:
        lines.append(f"- A-grade anchor: {item}")
    for item in (rubric.get("grade_d") or [])[:3]:
        lines.append(f"- D-grade failure: {item}")

    tasks = packet.get("llm_review_tasks") or []
    if tasks:
        lines.extend(["", "## LLM Review Tasks"])
        for index, item in enumerate(tasks, start=1):
            lines.append(f"{index}. {item}")

    revision_candidates = packet.get("revision_candidates") or []
    if revision_candidates:
        lines.extend(["", "## Conservative Revision Paths"])
        for item in revision_candidates:
            lines.append(
                f"- {item.get('title')} [{item.get('mode')}/{item.get('readiness')}]: {item.get('rationale')}"
            )

    if source_highlights:
        lines.extend(["", "## Official Source Highlights"])
        for item in source_highlights:
            lines.append(f"- {item.get('title')}: {item.get('url')}")

    if refs:
        lines.extend(["", "## Grounding Files"])
        for item in refs:
            lines.append(f"- {item.get('label')}: {item.get('path')} — {item.get('purpose')}")

    return "\n".join(lines).strip()
