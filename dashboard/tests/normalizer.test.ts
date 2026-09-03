import { describe, expect, it } from "vitest";

import { normalizeMatrixEvent, reclassifyStoredEvent } from "../lib/events/normalizer";

describe("normalizeMatrixEvent", () => {
  it("uses the real Matrix member display name when one is available", () => {
    const event = normalizeMatrixEvent({
      event_id: "$named-message",
      room_id: "!room:matrix.local",
      sender: "@manager:matrix.local",
      origin_server_ts: 1760000000000,
      type: "m.room.message",
      content: { msgtype: "m.text", body: "Named Manager update" },
    }, new Map([["!room:matrix.local\u0000@manager:matrix.local", "总控协调者"]]));

    expect(event.actor).toMatchObject({
      label: "manager",
      displayName: "总控协调者",
    });
  });

  it("keeps a WorkerFlow card as a workflow observation tied to its run and room", () => {
    const event = normalizeMatrixEvent({
      event_id: "$workflow-start",
      room_id: "!room:matrix.local",
      sender: "@worker-a:matrix.local",
      origin_server_ts: 1760000000000,
      type: "m.room.message",
      content: {
        msgtype: "m.notice",
        body: "Research workflow started",
        "agentteams.workflow": {
          type: "workerflow",
          runId: "run-42",
          status: "running",
          title: "Research workflow",
          summary: "Two workers are preparing the result.",
          ownerRole: "worker",
          ownerAgentId: "worker-a",
          steps: [
            { id: "collect", label: "Collect sources", status: "running" },
          ],
        },
      },
    });

    expect(event).toMatchObject({
      id: "matrix:$workflow-start",
      source: "matrix",
      kind: "workflow",
      roomId: "!room:matrix.local",
      runId: "run-42",
      summary: "Two workers are preparing the result.",
      sourceRef: { eventId: "$workflow-start" },
    });
    expect(event.detail).toMatchObject({
      title: "Research workflow",
      status: "running",
      steps: [{ id: "collect", label: "Collect sources", status: "running" }],
    });
  });

  it("turns a structured tool event into a redacted tool observation", () => {
    const event = normalizeMatrixEvent({
      event_id: "$tool-1",
      room_id: "!room:matrix.local",
      sender: "@manager:matrix.local",
      origin_server_ts: 1760000001000,
      type: "m.room.message",
      content: {
        msgtype: "m.notice",
        body: "tool call",
        "agentteams.tool": {
          name: "search_sources",
          callId: "call-1",
          status: "completed",
          args: { query: "agent teams", apiKey: "secret-value" },
          result: { count: 3, password: "hidden-value" },
        },
      },
    });

    expect(event).toMatchObject({
      id: "matrix:$tool-1",
      kind: "tool",
      roomId: "!room:matrix.local",
      summary: "search_sources · completed",
    });
    expect(JSON.stringify(event.detail)).not.toContain("secret-value");
    expect(JSON.stringify(event.detail)).not.toContain("hidden-value");
  });

  it("keeps a structured Skill invocation as first-class evidence", () => {
    const event = normalizeMatrixEvent({
      event_id: "$skill-1",
      room_id: "!room:matrix.local",
      sender: "@worker-a:matrix.local",
      origin_server_ts: 1760000001500,
      type: "m.room.message",
      content: {
        msgtype: "m.notice",
        body: "skill call",
        "agentteams.skill": {
          name: "task-management",
          skillName: "task-management",
          status: "completed",
          runId: "run-42",
          arguments: { token: "secret-value" },
        },
      },
    });

    expect(event).toMatchObject({
      id: "matrix:$skill-1",
      kind: "skill",
      runId: "run-42",
      summary: "task-management · completed",
      detail: { name: "task-management", skillName: "task-management", status: "completed" },
    });
    expect(JSON.stringify(event.detail)).not.toContain("secret-value");
  });

  it("normalizes the real Matrix Markdown Skill invocation format", () => {
    const event = normalizeMatrixEvent({
      event_id: "$markdown-skill-1",
      room_id: "!room:matrix.local",
      sender: "@leader-a:matrix.local",
      origin_server_ts: 1760000001600,
      type: "m.room.message",
      content: {
        msgtype: "m.text",
        body: "🔧 **Skill**\n```\n{\"skill\":\"teamharness-task-delegation\"}\n```",
      },
    });

    expect(event).toMatchObject({
      kind: "skill",
      summary: "teamharness-task-delegation · observed",
      detail: {
        name: "teamharness-task-delegation",
        skillName: "teamharness-task-delegation",
        status: "observed",
        invocationFormat: "matrix-markdown",
      },
    });
  });

  it("normalizes a real Matrix Markdown TeamHarness call as collaboration evidence", () => {
    const event = normalizeMatrixEvent({
      event_id: "$markdown-tool-1",
      room_id: "!room:matrix.local",
      sender: "@leader-a:matrix.local",
      origin_server_ts: 1760000001700,
      type: "m.room.message",
      content: {
        msgtype: "m.text",
        body: "🔧 **teamharness__taskflow** ``` {\"action\":\"delegate_task\",\"project_id\":\"run-42\"} ```",
      },
    });

    expect(event).toMatchObject({
      kind: "tool",
      summary: "teamharness__taskflow · observed",
      detail: {
        name: "teamharness__taskflow",
        evidenceCategory: "collaboration",
        invocationFormat: "matrix-markdown",
        projectId: "run-42",
      },
    });
  });

  it("classifies explicit Matrix human approval evidence without treating ACCEPTED as approval", () => {
    const event = normalizeMatrixEvent({
      event_id: "$approval-1",
      room_id: "!room:matrix.local",
      sender: "@nativeadmin:matrix.local",
      origin_server_ts: 1760000001800,
      type: "m.room.message",
      content: {
        msgtype: "m.text",
        body: "M2-E 一次性 Human 审批：我仅授权外部 operator 对上述同一 Worker 执行一次 docker rm -f。",
      },
    });

    expect(event).toMatchObject({
      kind: "message",
      detail: {
        evidenceCategory: "approval",
        approvalState: "approved",
        approvalActor: "human",
      },
    });
    expect(event.summary).toContain("Human 审批");
  });

  it("does not classify approval policy text as a human approval decision", () => {
    const event = normalizeMatrixEvent({
      event_id: "$approval-policy-1",
      room_id: "!room:matrix.local",
      sender: "@manager:matrix.local",
      origin_server_ts: 1760000001850,
      type: "m.room.message",
      content: {
        msgtype: "m.text",
        body: "No high-risk side effects are pending; nothing requires your approval yet. If a security-approval denial occurs, record BLOCKED honestly.",
      },
    });

    expect(event.detail).not.toHaveProperty("evidenceCategory", "approval");
  });

  it("classifies explicit failure text as exception evidence", () => {
    const event = normalizeMatrixEvent({
      event_id: "$exception-1",
      room_id: "!room:matrix.local",
      sender: "@manager:matrix.local",
      origin_server_ts: 1760000001900,
      type: "m.room.message",
      content: {
        msgtype: "m.notice",
        body: "⚠️ API provider returned a billing error; the branch is blocked.",
      },
    });

    expect(event).toMatchObject({
      kind: "message",
      detail: { evidenceCategory: "exception", status: "blocked" },
    });
  });

  it("reclassifies historical Matrix messages already stored before Markdown parsing", () => {
    const event = reclassifyStoredEvent({
      id: "matrix:$stored-tool",
      source: "matrix",
      kind: "message",
      occurredAt: "2026-09-02T10:00:00.000Z",
      roomId: "!room:matrix.local",
      actor: { id: "@leader-a:matrix.local", label: "leader-a", role: "worker" },
      summary: "🔧 **Skill**\n```\n{\"skill\":\"teamharness-roomflow\"}\n```",
      detail: { msgtype: "m.text" },
      sourceRef: { eventId: "$stored-tool" },
    });

    expect(event).toMatchObject({
      kind: "skill",
      summary: "teamharness-roomflow · observed",
      detail: { name: "teamharness-roomflow", invocationFormat: "matrix-markdown" },
    });
  });

  it("keeps an ordinary Matrix message as a user-visible message", () => {
    const event = normalizeMatrixEvent({
      event_id: "$message-1",
      room_id: "!room:matrix.local",
      sender: "@alice:matrix.local",
      origin_server_ts: 1760000002000,
      type: "m.room.message",
      content: {
        msgtype: "m.text",
        body: "Please compare the two reports.",
      },
    });

    expect(event).toMatchObject({
      id: "matrix:$message-1",
      kind: "message",
      summary: "Please compare the two reports.",
      detail: { msgtype: "m.text" },
    });
  });

  it("does not invent a run when a message has no explicit run correlation", () => {
    const event = normalizeMatrixEvent({
      event_id: "$unlinked",
      room_id: "!room:matrix.local",
      sender: "@worker-a:matrix.local",
      origin_server_ts: 1760000003000,
      type: "m.room.message",
      content: { msgtype: "m.text", body: "Unclassified update" },
    });

    expect(event.kind).toBe("message");
    expect(event.runId).toBeUndefined();
  });

  it("preserves Matrix thread and reply targets for run correlation", () => {
    const event = normalizeMatrixEvent({
      event_id: "$thread-reply",
      room_id: "!room:matrix.local",
      sender: "@worker-a:matrix.local",
      origin_server_ts: 1760000004000,
      type: "m.room.message",
      content: {
        msgtype: "m.text",
        body: "The worker finished the source review.",
        "m.relates_to": {
          rel_type: "m.thread",
          event_id: "$workflow-root",
          "m.in_reply_to": { event_id: "$workflow-update" },
        },
      },
    });

    expect(event.detail).toMatchObject({
      threadRootEventId: "$workflow-root",
      relatedEventId: "$workflow-update",
    });
  });
});
