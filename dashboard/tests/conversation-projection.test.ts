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
        id: "matrix:$approval",
        roomId: "!manager:matrix.local",
        actor: { id: "@nativeadmin:matrix.local", label: "nativeadmin", role: "human" },
        summary: "Human approval granted for one bounded action",
        detail: { evidenceCategory: "approval", approvalState: "approved" },
        sourceRef: { eventId: "$approval" },
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
      approvalCount: 1,
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

  it("surfaces a pending human approval as actionable attention", () => {
    const detail = projectConversation("manager:default", [
      event({
        summary: "Worker is paused awaiting human approval",
        detail: { evidenceCategory: "approval", approvalState: "pending", status: "waiting" },
        sourceRef: { eventId: "$pending-approval" },
      }),
    ], controllerData);

    expect(detail.conversation).toMatchObject({
      approvalCount: 1,
      status: "attention",
    });
    expect(detail.attention).toMatchObject([{
      severity: "warning",
      summary: "待人工审批：Worker is paused awaiting human approval",
      sourceEventId: "$pending-approval",
    }]);
  });

  it("splits task-correlated events into separate conversations", () => {
    const events = [
      event({
        id: "matrix:$task-a-root",
        roomId: "!team:matrix.local",
        kind: "tool",
        runId: "run-a",
        summary: "task-a started",
        detail: { runId: "run-a", taskId: "task-a", status: "running" },
      }),
      event({
        id: "matrix:$task-a-message",
        kind: "message",
        summary: "runId=run-a task-a progress",
      }),
      event({
        id: "matrix:$task-b-root",
        roomId: "!worker:matrix.local",
        kind: "tool",
        runId: "run-b",
        summary: "task-b started",
        detail: { runId: "run-b", taskId: "task-b", status: "running" },
      }),
      event({
        id: "matrix:$task-b-message",
        kind: "message",
        summary: "runId=run-b task-b progress",
      }),
      event({
        id: "matrix:$general-message",
        kind: "message",
        summary: "a manager message without a task id",
      }),
    ];

    const projection = projectConversations(events, controllerData);

    expect(projection.conversations.map((conversation) => conversation.id).sort()).toEqual([
      "manager:default",
      "manager:default:run:run-a",
      "manager:default:run:run-b",
    ]);

    expect(projection.conversations).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: "manager:default:run:run-a",
          title: expect.stringContaining("run-a"),
          eventCount: 2,
          messageCount: 1,
        }),
        expect.objectContaining({
          id: "manager:default:run:run-b",
          title: expect.stringContaining("run-b"),
          eventCount: 2,
          messageCount: 1,
        }),
        expect.objectContaining({
          id: "manager:default",
          eventCount: 1,
          messageCount: 1,
        }),
      ]),
    );

    expect(
      projectConversation("manager:default:run:run-a", events, controllerData).observations.map(
        (observation) => observation.id,
      ),
    ).toEqual(["matrix:$task-a-root", "matrix:$task-a-message"]);
  });

  it("uses thread relations and unique task ids without guessing ambiguous messages", () => {
    const events = [
      event({
        id: "matrix:$run-a-root",
        kind: "tool",
        runId: "run-a",
        detail: { runId: "run-a", taskId: "task-a", status: "running" },
        sourceRef: { eventId: "$run-a-root" },
      }),
      event({
        id: "matrix:$run-b-root",
        kind: "tool",
        runId: "run-b",
        detail: { runId: "run-b", taskId: "task-b", status: "running" },
        sourceRef: { eventId: "$run-b-root" },
      }),
      event({
        id: "matrix:$run-a-text",
        summary: "follow-up mentions run-a only",
        sourceRef: { eventId: "$run-a-text" },
      }),
      event({
        id: "matrix:$run-a-reply",
        summary: "thread reply without an id",
        detail: { relatedEventId: "$run-a-root" },
        sourceRef: { eventId: "$run-a-reply" },
      }),
      event({
        id: "matrix:$run-b-task-text",
        summary: "taskId=task-b completed",
        sourceRef: { eventId: "$run-b-task-text" },
      }),
      event({
        id: "matrix:$ambiguous",
        summary: "mentions run-a and run-b together",
        sourceRef: { eventId: "$ambiguous" },
      }),
    ];

    const projection = projectConversations(events, controllerData);
    const runA = projectConversation("manager:default:run:run-a", events, controllerData);
    const runB = projectConversation("manager:default:run:run-b", events, controllerData);
    const general = projectConversation("manager:default", events, controllerData);

    expect(runA.observations.map((observation) => observation.id)).toEqual([
      "matrix:$run-a-root",
      "matrix:$run-a-text",
      "matrix:$run-a-reply",
    ]);
    expect(runB.observations.map((observation) => observation.id)).toEqual([
      "matrix:$run-b-root",
      "matrix:$run-b-task-text",
    ]);
    expect(general.observations.map((observation) => observation.id)).toEqual(["matrix:$ambiguous"]);
    expect(projection.conversations.find((conversation) => conversation.id === "manager:default:run:run-b")?.taskIds).toEqual(["task-b"]);
  });

  it("keeps structural room metadata out of the conversation detail", () => {
    const events = [
      event({ id: "matrix:$room-meta", kind: "system", summary: "room.meta event" }),
      event({ id: "matrix:$message", summary: "visible manager message" }),
    ];

    expect(projectConversation("manager:default", events, controllerData).observations.map((item) => item.id)).toEqual([
      "matrix:$message",
    ]);
  });
});
