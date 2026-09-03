import type { AgentTeamsEvent } from "../types";
import { isPhaseReport, isStructuralRoomEvent } from "../events/evidence";

export const MAX_INBOX_PREVIEW_LENGTH = 96;

const internalSystemMarker = /^(?:heartbeat|sync heartbeat|room\.meta event)$/i;

const normalizedSummary = (event: AgentTeamsEvent): string => event.summary
  .replace(/\s+/g, " ")
  .replace(/\s+NO_REPLY\s*$/i, "")
  .trim();

export const isInboxNoise = (event: AgentTeamsEvent): boolean => {
  if (isPhaseReport(event) || isStructuralRoomEvent(event)) {
    return true;
  }
  const summary = normalizedSummary(event);
  return !summary || /^NO_REPLY$/i.test(summary) || (event.kind === "system" && internalSystemMarker.test(summary));
};

const truncate = (value: string): string => value.length > MAX_INBOX_PREVIEW_LENGTH
  ? `${value.slice(0, MAX_INBOX_PREVIEW_LENGTH - 1).trimEnd()}…`
  : value;

export const compactInboxPreview = (events: AgentTeamsEvent[], fallback: string): string => {
  const latestReadable = [...events]
    .sort((left, right) => right.occurredAt.localeCompare(left.occurredAt))
    .find((event) => !isInboxNoise(event));
  if (!latestReadable) {
    return truncate(fallback.replace(/\s+/g, " ").trim());
  }
  return truncate(normalizedSummary(latestReadable));
};
