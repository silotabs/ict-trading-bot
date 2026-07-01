import { postJson } from "./api-core";
import type { ControlItem } from "./api-types";

export async function updateControlState(control_key: string, paused: boolean, reason: string) {
  return postJson<ControlItem & { event_id?: string }>("/v1/control/state", {
    control_key,
    paused,
    reason,
    updated_by: "trading_web_dashboard",
    metadata: {
      source: "web_terminal",
    },
  });
}

export async function updateKillSwitch(paused: boolean, reason: string) {
  return postJson<ControlItem & { event_id?: string }>("/v1/control/kill-switch", {
    paused,
    reason,
    updated_by: "trading_web_dashboard",
    metadata: {
      source: "web_terminal",
    },
  });
}

export async function submitProposal(proposalId: string) {
  return postJson<Record<string, unknown>>(`/v1/order-proposals/${encodeURIComponent(proposalId)}/submit`, {
    confirm: true,
  });
}

export async function syncProposal(proposalId: string) {
  return postJson<Record<string, unknown>>(`/v1/order-proposals/${encodeURIComponent(proposalId)}/sync`, {});
}

export async function cancelProposal(proposalId: string) {
  return postJson<Record<string, unknown>>(`/v1/order-proposals/${encodeURIComponent(proposalId)}/cancel`, {
    confirm: true,
  });
}
