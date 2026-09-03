import { describe, expect, it } from "vitest";

import {
  buildWorkspaceSnapshot,
  formatSseFrame,
  parseMessageBody,
  parseMxcUri,
} from "../lib/api/contracts";

describe("Dashboard API contracts", () => {
  it("reports an unavailable controller without manufacturing a healthy snapshot", () => {
    const response = buildWorkspaceSnapshot({
      version: 1,
      events: [],
      sync: { state: "connecting" },
    });

    expect(response.controller).toEqual({ state: "unavailable", error: undefined });
    expect(response.runs).toEqual([]);
    expect(response.capabilities).toEqual({ liveSync: true, traceQuery: false });
    expect(response.sync.state).toBe("connecting");
  });

  it("accepts a trimmed message and keeps an optional explicit thread root", () => {
    expect(parseMessageBody({ text: "  Continue the merge  ", threadRootEventId: "$root" })).toEqual({
      text: "Continue the merge",
      threadRootEventId: "$root",
    });
  });

  it("rejects empty, oversized, and non-object message bodies", () => {
    expect(() => parseMessageBody({ text: "   " })).toThrow(/message text is required/);
    expect(() => parseMessageBody({ text: "x".repeat(12_001) })).toThrow(/at most 12000/);
    expect(() => parseMessageBody(null)).toThrow(/request body must be an object/);
  });

  it("formats an SSE frame with an event id and JSON data", () => {
    expect(formatSseFrame({ id: "matrix:$event", type: "observation", data: { summary: "ready" } })).toBe(
      'id: matrix:$event\nevent: observation\ndata: {"summary":"ready"}\n\n',
    );
  });

  it("accepts only Matrix MXC media references", () => {
    expect(parseMxcUri("mxc://matrix.local/media-id")).toEqual({
      serverName: "matrix.local",
      mediaId: "media-id",
    });
    expect(() => parseMxcUri("https://example.com/file")).toThrow(/mxc/);
  });
});
