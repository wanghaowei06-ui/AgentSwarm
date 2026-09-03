import { describe, expect, it } from "vitest";

import { compactInboxPreview, isInboxNoise } from "../lib/inbox/preview";
import type { AgentTeamsEvent } from "../lib/types";

const event = (summary: string, overrides: Partial<AgentTeamsEvent> = {}): AgentTeamsEvent => ({
  id: `matrix:${summary.slice(0, 8)}`,
  source: "matrix",
  kind: "message",
  occurredAt: "2026-09-03T13:02:15.000Z",
  roomId: "!room:matrix.local",
  summary,
  sourceRef: { eventId: "$event" },
  ...overrides,
});

describe("Inbox preview", () => {
  it("omits internal phase and reply markers and truncates a readable message", () => {
    const result = compactInboxPreview([
      event("[PHASE-REPORT run-1] 13:02Z — worker is active\nNO_REPLY"),
      event("Manager   needs   the   final   receipt   " + "x".repeat(140)),
    ], "等待 Manager 消息");

    expect(result).toMatch(/^Manager needs the final receipt x+/);
    expect(result).not.toContain("PHASE-REPORT");
    expect(result).not.toContain("NO_REPLY");
    expect(result).toHaveLength(96);
    expect(result.endsWith("…")).toBe(true);
  });

  it("treats structural room events and a trailing NO_REPLY as inbox noise", () => {
    expect(isInboxNoise(event("room.meta event", { kind: "system" }))).toBe(true);
    expect(isInboxNoise(event("NO_REPLY"))).toBe(true);
    expect(compactInboxPreview([event("A concise update\nNO_REPLY")], "等待 Manager 消息")).toBe("A concise update");
  });
});
