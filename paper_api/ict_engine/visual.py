from __future__ import annotations

VALID_VISUAL_ANALYSIS_STATES = {"not_run", "manual_context_only", "partial", "verified"}


def derive_visual_analysis_state(chart_url=None, screenshot_paths=None, explicit_state=None):
    explicit = str(explicit_state or "").strip().lower()
    if explicit in VALID_VISUAL_ANALYSIS_STATES:
        return explicit
    if chart_url or (isinstance(screenshot_paths, list) and screenshot_paths):
        return "manual_context_only"
    return "not_run"

