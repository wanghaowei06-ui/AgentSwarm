import { describe, expect, it } from "vitest";
import type { AgentTeamsEvent } from "../lib/types";
import { toThreadMessageLike } from "../lib/ui/thread-message";

const event = (overrides: Partial<AgentTeamsEvent>): AgentTeamsEvent => ({
  id: "matrix:$message",
  source: "matrix",
  kind: "message",
  occurredAt: "2026-09-02T08:00:00.000Z",
  roomId: "!room:example.test",
  actor: { id: "@alice:example.test", label: "alice", role: "human" },
  summary: "Please inspect the deployment trace.",
  sourceRef: { eventId: "$message" },
  ...overrides,
});

describe("toThreadMessageLike", () => {
  it("maps human Matrix messages to assistant-ui user messages", () => {
    const result = toThreadMessageLike(event({ runId: "run-42" }));

    expect(result).toMatchObject({
      id: "matrix:$message",
      role: "user",
      content: [{ type: "text", text: "Please inspect the deployment trace." }],
      metadata: {
        custom: {
          runId: "run-42",
          actorRole: "human",
          sourceEventId: "$message",
        },
      },
    });
    expect(result?.createdAt).toEqual(new Date("2026-09-02T08:00:00.000Z"));
  });

  it("maps agent messages to assistant messages without leaking raw event detail", () => {
    const result = toThreadMessageLike(event({
      actor: { id: "@manager:example.test", label: "manager", role: "manager" },
      summary: "I assigned the trace review to the worker.",
      detail: { token: "should-never-reach-the-browser" },
    }));

    expect(result).toMatchObject({
      role: "assistant",
      content: [{ type: "text", text: "I assigned the trace review to the worker." }],
      metadata: { custom: { actorRole: "manager" } },
    });
    expect(JSON.stringify(result)).not.toContain("should-never-reach-the-browser");
  });

  it("leaves workflow and tool observations for the richer event cards", () => {
    expect(toThreadMessageLike(event({ kind: "workflow" }))).toBeNull();
    expect(toThreadMessageLike(event({ kind: "tool" }))).toBeNull();
  });
});
