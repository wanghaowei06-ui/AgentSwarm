import { describe, expect, it } from "vitest";

import { projectRoom, projectRun, projectWorkspace } from "../lib/runs/projection";
import type { AgentTeamsEvent } from "../lib/types";

const workflow = (id: string, status: string, occurredAt: string): AgentTeamsEvent => ({
  id,
  source: "matrix",
  kind: "workflow",
  occurredAt,
  roomId: "!room:matrix.local",
  runId: "run-42",
  summary: status === "done" ? "Finished" : "Running",
  detail: {
    title: "Research workflow",
    status,
    steps: [
      { id: "collect", label: "Collect sources", status },
      { id: "merge", label: "Merge result", status: status === "done" ? "done" : "waiting" },
    ],
  },
  sourceRef: { eventId: id.replace("matrix:", "") },
});

describe("run projection", () => {
  it("associates a threaded message with a run through the explicit root event", () => {
    const events: AgentTeamsEvent[] = [
      { ...workflow("matrix:$workflow-root", "running", "2026-09-02T10:00:00.000Z") },
      {
        ...workflow("matrix:$workflow-update", "done", "2026-09-02T10:02:00.000Z"),
        detail: {
          title: "Research workflow",
          status: "done",
          relatedEventId: "$workflow-root",
          steps: [],
        },
      },
      {
        id: "matrix:$reply",
        source: "matrix",
        kind: "message",
        occurredAt: "2026-09-02T10:03:00.000Z",
        roomId: "!room:matrix.local",
        summary: "Worker result",
        detail: { threadRootEventId: "$workflow-root" },
        sourceRef: { eventId: "$reply" },
      },
      {
        id: "matrix:$other",
        source: "matrix",
        kind: "message",
        occurredAt: "2026-09-02T10:04:00.000Z",
        roomId: "!room:matrix.local",
        summary: "Unclassified room message",
        sourceRef: { eventId: "$other" },
      },
    ];

    const detail = projectRun("run-42", events);

    expect(detail.run).toMatchObject({
      id: "run-42",
      roomId: "!room:matrix.local",
      status: "done",
      title: "Research workflow",
    });
    expect(detail.messages.map((item) => item.id)).toEqual(["matrix:$reply"]);
    expect(detail.observations.map((item) => item.id)).toEqual([
      "matrix:$workflow-root",
      "matrix:$workflow-update",
      "matrix:$reply",
    ]);
    expect(detail.attention).toEqual([]);
  });

  it("keeps a room with no explicit workflow out of the run list", () => {
    const events: AgentTeamsEvent[] = [
      {
        id: "matrix:$message",
        source: "matrix",
        kind: "message",
        occurredAt: "2026-09-02T10:00:00.000Z",
        roomId: "!room:matrix.local",
        summary: "No run id here",
        sourceRef: { eventId: "$message" },
      },
    ];

    const workspace = projectWorkspace(events);

    expect(workspace.runs).toEqual([]);
    expect(workspace.rooms).toMatchObject([
      { roomId: "!room:matrix.local", messageCount: 1 },
    ]);
  });

  it("hides a superseded workflow event from the active timeline while keeping the replacement", () => {
    const replacement: AgentTeamsEvent = {
      ...workflow("matrix:$workflow-replacement", "done", "2026-09-02T10:02:00.000Z"),
      detail: {
        title: "Research workflow",
        status: "done",
        editedEventId: "$workflow-root",
        steps: [],
      },
    };

    const detail = projectRun("run-42", [
      workflow("matrix:$workflow-root", "running", "2026-09-02T10:00:00.000Z"),
      replacement,
    ]);

    expect(detail.observations.map((item) => item.id)).toEqual(["matrix:$workflow-replacement"]);
    expect(detail.run.status).toBe("done");
  });

  it("projects an unclassified room timeline without inventing a run", () => {
    const events: AgentTeamsEvent[] = [
      {
        id: "matrix:$room-message",
        source: "matrix",
        kind: "message",
        occurredAt: "2026-09-02T11:00:00.000Z",
        roomId: "!room:matrix.local",
        summary: "A room message before workflow metadata.",
        sourceRef: { eventId: "$room-message" },
      },
    ];

    const detail = projectRoom("!room:matrix.local", events);

    expect(detail.room.roomId).toBe("!room:matrix.local");
    expect(detail.messages.map((item) => item.summary)).toEqual(["A room message before workflow metadata."]);
    expect(projectWorkspace(events).runs).toEqual([]);
  });
});
