import { describe, expect, it } from "vitest";

import {
  projectConversation,
  projectConversationSummary,
} from "../lib/projects/projection";
import type { AgentTeamsEvent, DashboardProject } from "../lib/types";

const project: DashboardProject = {
  id: "dashboard-project:receipt",
  kind: "project",
  name: "材料核验",
  status: "active",
  managerUserId: "@manager:matrix.local",
  managerRoomId: "!manager-project:matrix.local",
  rooms: [
    {
      roomId: "!manager-project:matrix.local",
      name: "Manager 私聊",
      kind: "manager",
      inviteUserIds: ["@manager:matrix.local"],
      createdAt: "2026-09-03T10:00:00.000Z",
    },
    {
      roomId: "!project-main:matrix.local",
      name: "主讨论",
      kind: "project",
      inviteUserIds: ["@manager:matrix.local", "@worker:matrix.local"],
      createdAt: "2026-09-03T10:00:01.000Z",
    },
  ],
  createdAt: "2026-09-03T10:00:00.000Z",
  updatedAt: "2026-09-03T10:00:01.000Z",
};

const event = (overrides: Partial<AgentTeamsEvent>): AgentTeamsEvent => ({
  id: "matrix:$event",
  source: "matrix",
  kind: "message",
  occurredAt: "2026-09-03T10:01:00.000Z",
  roomId: "!manager-project:matrix.local",
  actor: { id: "@manager:matrix.local", label: "manager", role: "manager" },
  summary: "Manager reply",
  sourceRef: { eventId: "$event" },
  ...overrides,
});

describe("project projection", () => {
  it("keeps project timelines isolated by persisted room IDs", () => {
    const detail = projectConversation(project, [
      event({ roomId: "!manager-project:matrix.local", summary: "Manager reply" }),
      event({
        id: "matrix:$project",
        roomId: "!project-main:matrix.local",
        summary: "Project update",
        sourceRef: { eventId: "$project" },
      }),
      event({
        id: "matrix:$other",
        roomId: "!other-project:matrix.local",
        summary: "Must not leak",
        sourceRef: { eventId: "$other" },
      }),
    ]);

    expect(detail.messages.map((item) => item.summary)).toEqual([
      "Manager reply",
      "Project update",
    ]);
    expect(detail.conversation.managerRoomId).toBe("!manager-project:matrix.local");
    expect(detail.rooms.map((room) => room.roomId)).toEqual([
      "!manager-project:matrix.local",
      "!project-main:matrix.local",
    ]);
  });

  it("projects the project source and real event counters", () => {
    const summary = projectConversationSummary(project, [
      event({
        id: "matrix:$workflow",
        kind: "workflow",
        summary: "Delegated review",
        detail: { status: "running" },
        sourceRef: { eventId: "$workflow" },
      }),
      event({
        id: "matrix:$skill",
        kind: "skill",
        roomId: "!project-main:matrix.local",
        summary: "evidence-check · completed",
        detail: { status: "completed" },
        sourceRef: { eventId: "$skill" },
      }),
    ]);

    expect(summary).toMatchObject({
      source: "dashboard-project",
      projectId: "dashboard-project:receipt",
      projectStatus: "active",
      roomCount: 2,
      messageCount: 0,
      collaborationCount: 1,
      skillCount: 1,
    });
  });
});
