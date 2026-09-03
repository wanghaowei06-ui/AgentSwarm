import { describe, expect, it } from "vitest";

import {
  eventEvidenceCategory,
  projectConversation,
  projectConversations,
} from "../lib/conversations/projection";
import type { AgentTeamsEvent, JsonObject } from "../lib/types";

const controllerData: JsonObject = {
  "/api/v1/managers": {
    managers: [{ name: "default", roomID: "!manager:matrix.local", matrixUserID: "@manager:matrix.local" }],
  },
  "/api/v1/teams": {
    teams: [{
      name: "research-team",
      teamRoomID: "!team:matrix.local",
      leaderDMRoomID: "!leader-dm:matrix.local",
      leaderName: "research-lead",
    }],
  },
  "/api/v1/workers": {
    workers: [{
      name: "research-worker",
      matrixUserID: "@research-worker:matrix.local",
      roomID: "!worker:matrix.local",
      team: "research-team",
      role: "worker",
    }],
  },
};

const event = (overrides: Partial<AgentTeamsEvent>): AgentTeamsEvent => ({
  id: "matrix:$event",
  source: "matrix",
  kind: "message",
  occurredAt: "2026-09-02T10:00:00.000Z",
  roomId: "!manager:matrix.local",
  actor: { id: "@manager:matrix.local", label: "manager", role: "manager" },
  summary: "Manager update",
  sourceRef: { eventId: "$event" },
  ...overrides,
});

describe("conversation projection", () => {
  it("groups a Manager conversation with Controller-known collaboration rooms", () => {
    const projection = projectConversations([
      event({ id: "matrix:$manager-message", sourceRef: { eventId: "$manager-message" } }),
      event({
        id: "matrix:$workflow",
        kind: "workflow",
        roomId: "!team:matrix.local",
        actor: { id: "@research-lead:matrix.local", label: "research-lead", role: "worker" },
        summary: "Delegated source review",
        detail: { status: "running", ownerAgentId: "research-lead" },
        sourceRef: { eventId: "$workflow" },
      }),
      event({
        id: "matrix:$skill",
        kind: "skill",
        roomId: "!leader-dm:matrix.local",
        actor: { id: "@research-lead:matrix.local", label: "research-lead", role: "worker" },
        summary: "task-management · completed",
        detail: { name: "task-management", status: "completed" },
        sourceRef: { eventId: "$skill" },
      }),
      event({
        id: "matrix:$failed-tool",
        kind: "tool",
        roomId: "!worker:matrix.local",
        actor: { id: "@research-worker:matrix.local", label: "research-worker", role: "worker" },
        summary: "mc cp · failed",
        detail: { name: "mc cp", status: "failed", error: "storage unavailable" },
        sourceRef: { eventId: "$failed-tool" },
      }),
      event({
        id: "matrix:$orphan",
        roomId: "!unlinked:matrix.local",
        actor: { id: "@someone:matrix.local", label: "someone", role: "human" },
        summary: "Unlinked room update",
        sourceRef: { eventId: "$orphan" },
      }),
    ], controllerData);

    expect(projection.conversations).toHaveLength(1);
    expect(projection.conversations[0]).toMatchObject({
      id: "manager:default",
      managerRoomId: "!manager:matrix.local",
      roomCount: 4,
      agentCount: 3,
      collaborationCount: 1,
      skillCount: 1,
      exceptionCount: 1,
      status: "attention",
    });
    expect(projection.conversations[0].rooms.map((room) => room.role)).toEqual([
      "manager",
      "team",
      "leader",
      "worker",
    ]);
    expect(projection.unassignedRooms.map((room) => room.roomId)).toEqual(["!unlinked:matrix.local"]);
  });

  it("returns the evidence-first timeline for one Manager conversation", () => {
    const events = [
      event({ id: "matrix:$manager", sourceRef: { eventId: "$manager" } }),
      event({
        id: "matrix:$skill",
        kind: "skill",
        roomId: "!leader-dm:matrix.local",
        detail: { name: "task-management", status: "completed" },
        sourceRef: { eventId: "$skill" },
      }),
    ];
    const detail = projectConversation("manager:default", events, controllerData);

    expect(detail.messages.map((item) => item.id)).toEqual(["matrix:$manager"]);
    expect(detail.evidence.map((item) => item.id)).toEqual(["matrix:$skill"]);
    expect(detail.observations.map((item) => item.id)).toEqual(["matrix:$manager", "matrix:$skill"]);
  });

  it("does not use a raw phase report as the Manager conversation subtitle", () => {
    const detail = projectConversation("manager:default", [
      event({
        summary: "[PHASE-REPORT run -12] 12:54Z — Phase 1 IN PROGRESS\n• Worker is active.",
        sourceRef: { eventId: "$phase-report" },
      }),
    ], controllerData);

    expect(detail.conversation.summary).toBe("最新执行进度已移到右侧证据栏");
  });

  it("uses real Matrix display names for Manager and worker room labels", () => {
    const detail = projectConversation("manager:default", [
      event({
        actor: {
          id: "@manager:matrix.local",
          label: "manager",
          displayName: "总控协调者",
          role: "manager",
        },
      }),
      event({
        id: "matrix:$worker",
        roomId: "!worker:matrix.local",
        actor: {
          id: "@research-worker:matrix.local",
          label: "research-worker",
          displayName: "证据分析员",
          role: "worker",
        },
        summary: "Worker update",
        sourceRef: { eventId: "$worker" },
      }),
      event({
        id: "matrix:$leader",
        roomId: "!leader-dm:matrix.local",
        actor: {
          id: "@research-lead:matrix.local",
          label: "research-lead",
          displayName: "研究组长",
          role: "worker",
        },
        summary: "Leader update",
        sourceRef: { eventId: "$leader" },
      }),
    ], controllerData);

    expect(detail.rooms.find((room) => room.role === "manager")).toMatchObject({
      label: "Manager · 总控协调者",
      agentName: "总控协调者",
    });
    expect(detail.rooms.find((room) => room.role === "worker")).toMatchObject({
      label: "Worker · 证据分析员",
      agentName: "证据分析员",
    });
    expect(detail.rooms.find((room) => room.role === "leader")).toMatchObject({
      label: "Leader · 研究组长",
      agentName: "研究组长",
    });
  });

  it("classifies failed tool calls as exception evidence", () => {
    expect(eventEvidenceCategory(event({
      kind: "tool",
      detail: { status: "failed" },
    }))).toBe("exception");
    expect(eventEvidenceCategory(event({ kind: "skill" }))).toBe("skill");
    expect(eventEvidenceCategory(event({ kind: "workflow" }))).toBe("collaboration");
  });
});
