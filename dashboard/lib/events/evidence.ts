import type { AgentTeamsEvent, EvidenceCategory } from "../types";

export type PhaseReportInfo = {
  runLabel: string;
  reportedAt?: string;
  headline: string;
  highlights: string[];
};

const textValue = (value: unknown): string =>
  typeof value === "string" ? value.trim().toLowerCase() : "";

const hasFailureStatus = (value: unknown): boolean =>
  ["failed", "failure", "error", "errored", "unavailable", "degraded", "cancelled", "canceled", "waiting", "blocked"]
    .includes(textValue(value));

const phaseReportHeader = /^\s*\[\s*PHASE[-\s]?REPORT\s+([^\]]+)\]\s*(.*)$/i;

const cleanReportLine = (value: string): string =>
  value
    .replace(/^\s*[•*-]\s*/, "")
    .replace(/\*\*/g, "")
    .replace(/`/g, "")
    .trim()
    .slice(0, 280);

export const phaseReportInfo = (event: AgentTeamsEvent): PhaseReportInfo | undefined => {
  if (event.kind !== "message") {
    return undefined;
  }
  const lines = event.summary.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const header = lines[0] ? phaseReportHeader.exec(lines[0]) : undefined;
  if (!header) {
    return undefined;
  }
  const clock = /^(\d{1,2}:\d{2}(?::\d{2})?Z)\s*(?:[-—–:]\s*)?(.*)$/i.exec(header[2].trim());
  const headerHeadline = cleanReportLine(clock ? clock[2] : header[2] || "");
  const bodyLines = lines.slice(1);
  const bodyHeadlineIndex = !headerHeadline
    ? bodyLines.findIndex((line) => !/^\s*[•*-]\s*/.test(line))
    : -1;
  const headline = headerHeadline
    || (bodyHeadlineIndex >= 0 ? cleanReportLine(bodyLines[bodyHeadlineIndex]) : "Phase report");
  return {
    runLabel: cleanReportLine(header[1]),
    ...(clock?.[1] ? { reportedAt: clock[1] } : {}),
    headline,
    highlights: bodyLines
      .filter((_line, index) => index !== bodyHeadlineIndex)
      .map(cleanReportLine)
      .filter(Boolean)
      .slice(0, 3),
  };
};

export const isPhaseReport = (event: AgentTeamsEvent): boolean =>
  Boolean(phaseReportInfo(event));

export const isStructuralRoomEvent = (event: AgentTeamsEvent): boolean =>
  event.kind === "system" && /^(?:m\.)?room\.[\w.-]+\s+event$/i.test(event.summary.trim());

export const isCentralConversationEvent = (event: AgentTeamsEvent): boolean =>
  !isPhaseReport(event) && !isStructuralRoomEvent(event);

export const latestPhaseReports = (events: AgentTeamsEvent[]): AgentTeamsEvent[] => {
  const latestByRun = new Map<string, AgentTeamsEvent>();
  for (const event of events) {
    const info = phaseReportInfo(event);
    if (!info) {
      continue;
    }
    const key = info.runLabel || event.roomId || event.id;
    const previous = latestByRun.get(key);
    if (!previous || previous.occurredAt.localeCompare(event.occurredAt) < 0) {
      latestByRun.set(key, event);
    }
  }
  return [...latestByRun.values()].sort((left, right) => right.occurredAt.localeCompare(left.occurredAt));
};

export const eventEvidenceCategory = (event: AgentTeamsEvent): EvidenceCategory => {
  const status = event.detail?.status;
  if ((event.kind === "workflow" || event.kind === "tool" || event.kind === "skill" || event.kind === "system") && hasFailureStatus(status)) {
    return "exception";
  }
  if (event.kind === "system" && /degraded|unavailable|error|failed/i.test(event.summary)) {
    return "exception";
  }
  if (event.kind === "workflow") {
    return "collaboration";
  }
  if (event.kind === "skill") {
    return "skill";
  }
  if (event.kind === "tool") {
    return "tool";
  }
  if (event.kind === "artifact") {
    return "artifact";
  }
  if (event.kind === "message") {
    return "message";
  }
  return "system";
};

export const isPriorityEvidence = (event: AgentTeamsEvent): boolean =>
  ["collaboration", "skill", "tool", "exception"].includes(eventEvidenceCategory(event));
