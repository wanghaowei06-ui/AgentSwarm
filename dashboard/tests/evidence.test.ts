import { describe, expect, it } from "vitest";

import {
  eventEvidenceCategory,
  isCentralConversationEvent,
  isPhaseReport,
  latestPhaseReports,
  phaseReportInfo,
} from "../lib/events/evidence";
import type { AgentTeamsEvent } from "../lib/types";

const phaseReport = (overrides: Partial<AgentTeamsEvent> = {}): AgentTeamsEvent => ({
  id: "matrix:$phase-report-1",
  source: "matrix",
  kind: "message",
  occurredAt: "2026-09-02T12:54:00.000Z",
  roomId: "!manager:matrix.local",
  actor: { id: "@manager:matrix.local", label: "manager", role: "manager" },
  summary: `[PHASE-REPORT run -12] 12:54Z — Phase 1 IN PROGRESS
• Delegated 12:38-12:39 → native-worker (Running).
• result.md: not yet in MinIO. Fault injection: NOT_OBSERVED.`,
  sourceRef: { eventId: "$phase-report-1" },
  ...overrides,
});

describe("phase report presentation", () => {
  it("keeps raw phase reports out of the central conversation and formats their evidence", () => {
    const event = phaseReport();

    expect(isPhaseReport(event)).toBe(true);
    expect(isCentralConversationEvent(event)).toBe(false);
    expect(phaseReportInfo(event)).toEqual({
      runLabel: "run -12",
      reportedAt: "12:54Z",
      headline: "Phase 1 IN PROGRESS",
      highlights: [
        "Delegated 12:38-12:39 → native-worker (Running).",
        "result.md: not yet in MinIO. Fault injection: NOT_OBSERVED.",
      ],
    });
  });

  it("keeps only the latest report for each run in the side evidence rail", () => {
    const latest = latestPhaseReports([
      phaseReport({ id: "matrix:$older", occurredAt: "2026-09-02T12:44:00.000Z" }),
      phaseReport({ id: "matrix:$newer", occurredAt: "2026-09-02T12:54:00.000Z" }),
      phaseReport({
        id: "matrix:$other-run",
        occurredAt: "2026-09-02T12:53:00.000Z",
        summary: "[PHASE-REPORT run other] 12:53Z — Phase 2 REVIEW",
      }),
    ]);

    expect(latest.map((event) => event.id)).toEqual([
      "matrix:$newer",
      "matrix:$other-run",
    ]);
  });

  it("uses the first non-bullet line as the headline when the report header only has a time", () => {
    const info = phaseReportInfo(phaseReport({
      summary: `[PHASE-REPORT run m2g] 12:41Z
Phase 1 (primary, Team A): IN PROGRESS — delegation chain complete.
• Leader delegated the task to the worker.`,
    }));

    expect(info).toMatchObject({
      reportedAt: "12:41Z",
      headline: "Phase 1 (primary, Team A): IN PROGRESS — delegation chain complete.",
      highlights: ["Leader delegated the task to the worker."],
    });
  });

  it("keeps Matrix room metadata events out of the central conversation", () => {
    const event = phaseReport({
      id: "matrix:$room-meta",
      kind: "system",
      summary: "room.meta event",
    });

    expect(isCentralConversationEvent(event)).toBe(false);
  });

  it("uses explicit evidence categories for real text-derived observations", () => {
    expect(eventEvidenceCategory(phaseReport({
      detail: { evidenceCategory: "approval", approvalState: "approved" },
    }))).toBe("approval");
    expect(eventEvidenceCategory(phaseReport({
      detail: { evidenceCategory: "collaboration" },
    }))).toBe("collaboration");
  });
});
