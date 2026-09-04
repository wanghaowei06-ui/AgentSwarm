import { describe, expect, it, vi } from "vitest";

import { POST as postConversationMessage } from "../app/api/conversations/[conversationId]/messages/route";

const runtime = vi.hoisted(() => ({
  matrix: { sendMessage: vi.fn() },
  store: { snapshot: vi.fn() },
}));

vi.mock("../lib/runtime", () => ({
  ensureDashboardRuntime: vi.fn(async () => runtime),
}));

describe("conversation message API", () => {
  it("keeps a task reply in the task thread", async () => {
    runtime.store.snapshot.mockResolvedValueOnce({
      version: 1,
      events: [
        {
          id: "matrix:$root",
          source: "matrix",
          kind: "tool",
          runId: "run-a",
          occurredAt: "2026-09-04T10:00:00.000Z",
          roomId: "!manager:matrix.local",
          summary: "task started",
          detail: { runId: "run-a", taskId: "task-a", status: "running" },
          sourceRef: { eventId: "$root" },
        },
        {
          id: "matrix:$progress",
          source: "matrix",
          kind: "message",
          occurredAt: "2026-09-04T10:01:00.000Z",
          roomId: "!manager:matrix.local",
          summary: "task progress",
          detail: { relatedEventId: "$root" },
          sourceRef: { eventId: "$progress" },
        },
      ],
      projects: [],
      sync: { state: "live" },
      controller: {
        data: {
          "/api/v1/managers": {
            managers: [{ name: "default", roomID: "!manager:matrix.local" }],
          },
          "/api/v1/teams": { teams: [] },
          "/api/v1/workers": { workers: [] },
        },
      },
    });
    runtime.matrix.sendMessage.mockResolvedValueOnce({ eventId: "$sent", txnId: "txn-1" });

    const response = await postConversationMessage(new Request("http://dashboard.test/api/conversations/manager:default:run:run-a/messages", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text: "继续" }),
    }), {
      params: Promise.resolve({ conversationId: "manager:default:run:run-a" }),
    });

    expect(response.status).toBe(200);
    expect(runtime.matrix.sendMessage).toHaveBeenCalledWith("!manager:matrix.local", "继续", {
      threadRootEventId: "$root",
    });
  });
});
