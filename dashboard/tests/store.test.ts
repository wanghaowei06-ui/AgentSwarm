import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { EventStore } from "../lib/events/store";
import { matrixMemberKey } from "../lib/events/normalizer";
import type { AgentTeamsEvent } from "../lib/types";

const event = (id: string, occurredAt: string): AgentTeamsEvent => ({
  id,
  source: "matrix",
  kind: "message",
  occurredAt,
  roomId: "!room:matrix.local",
  summary: id,
  sourceRef: { eventId: id.replace("matrix:", "") },
});

describe("EventStore", () => {
  it("persists cursor and deduplicates events across process restarts", async () => {
    const dataDir = await mkdtemp(join(tmpdir(), "agentteams-dashboard-store-"));
    const first = new EventStore({ dataDir });
    await first.init();
    await first.setCursor("s-1");
    await first.append([event("matrix:$one", "2026-09-02T10:00:00.000Z")]);
    await first.append([event("matrix:$one", "2026-09-02T10:00:00.000Z")]);

    const second = new EventStore({ dataDir });
    await second.init();
    const snapshot = await second.snapshot();

    expect(snapshot.cursor).toBe("s-1");
    expect(snapshot.events).toHaveLength(1);
    expect(snapshot.events[0].id).toBe("matrix:$one");
  });

  it("writes a recoverable JSON snapshot without credentials or raw private fields", async () => {
    const dataDir = await mkdtemp(join(tmpdir(), "agentteams-dashboard-store-"));
    const store = new EventStore({ dataDir });
    await store.init();
    await store.append([
      {
        ...event("matrix:$safe", "2026-09-02T10:00:00.000Z"),
        detail: { name: "search", apiKey: "[redacted]" },
      },
    ]);

    const raw = await readFile(join(dataDir, "state.json"), "utf8");
    expect(raw).toContain("matrix:$safe");
    expect(raw).not.toContain('"password"');
    expect(raw).not.toContain('"access_token"');
  });

  it("clears a stale sync error after the source recovers", async () => {
    const dataDir = await mkdtemp(join(tmpdir(), "agentteams-dashboard-store-"));
    const store = new EventStore({ dataDir });
    await store.init();

    await store.setSyncState("degraded", { error: "Matrix disconnected" });
    await store.setSyncState("live");

    expect((await store.snapshot()).sync).not.toHaveProperty("lastError");
  });

  it("enriches persisted events with the latest real Matrix display name", async () => {
    const dataDir = await mkdtemp(join(tmpdir(), "agentteams-dashboard-store-"));
    const store = new EventStore({ dataDir });
    await store.init();
    await store.append([{
      ...event("matrix:$named", "2026-09-02T10:00:00.000Z"),
      actor: { id: "@manager:matrix.local", label: "manager", role: "manager" },
    }]);

    await store.enrichActorDisplayNames(new Map([
      [matrixMemberKey("!room:matrix.local", "@manager:matrix.local"), "总控协调者"],
    ]));

    await expect(store.snapshot()).resolves.toMatchObject({
      events: [{ actor: { displayName: "总控协调者" } }],
    });
  });
});
