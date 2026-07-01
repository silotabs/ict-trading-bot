# UI Productization Samples

Static design graphics for the enterprise trading operations desk direction. These are planning artifacts only; they do not change runtime code.

## Samples

- `01_enterprise_operations_desk.svg` - full dashboard layout with compact header, decision strip, ICT chart, decision rail, and evidence footer.
- `02_decision_rail_detail.svg` - detailed right-rail concept focused on operator signal, blocker, checklist, and next action.
- `03_execution_lifecycle_review.svg` - review deck and execution lifecycle concept for signal trace to exchange status.
- `04_enterprise_control_room_v2.html` - revised higher-fidelity control-room mockup. This supersedes the first three rough SVG wireframes.

## Product Direction

- Keep the chart as the primary workspace.
- Make the first visible answer: can the operator act, and why?
- Hide raw backend enum values behind hover/details.
- Move daemon, harness, and lab language into advanced/admin views.
- Keep emergency controls visually separate from normal analysis controls.

## V2 Correction Notes

The first SVG samples are rough structural sketches, not final visual direction. The V2 mockup moves toward a more credible operations product:

- workflow-based navigation instead of terminal-style tabs;
- compact top bar with environment, stream health, policy state, and emergency control;
- decision strip before chart details;
- chart overlays limited to ICT structures that matter for action;
- right rail focused on actionability, checklist, risk, and next action;
- bottom panels reserved for lifecycle, shadow evidence, and system notes.
