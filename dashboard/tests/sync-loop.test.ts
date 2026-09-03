import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { EventHub } from "../lib/events/hub";
import { DashboardSyncLoop } from "../lib/events/sync-loop";
import { EventStore } from "../lib/events/store";

const waitFor = async (predicate: () => Promise<boolean>, timeoutMs = 1_000): Promise<void> => {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    if (await predicate()) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error("condition was not met before the test timeout");
};

describe("DashboardSyncLoop", () => {
  it("persists a Matrix cursor, normalizes timeline events and broadcasts them", async () => {
    const dataDir = await mkdtemp(join(tmpdir(), "agentteams-dashboard-sync-"));
    const store = new EventStore({ dataDir });
    const hub = new EventHub();
    const subscription = hub.subscribe();
    let syncCalls = 0;
    const matrix = {
      joinedRooms: async () => ["!room:matrix.local"],
      roomState: async () => [{
        type: "m.room.member",
        state_key: "@manager:matrix.local",
        content: { membership: "join", displayname: "总控协调者" },
      }],
      history: async () => ({ chunk: [] }),
      sync: async () => {
        syncCalls += 1;
        if (syncCalls > 1) {
          await new Promise((resolve) => setTimeout(resolve, 50));
        }
        return {
          next_batch: "s-2",
          rooms: {
            join: {
              "!room:matrix.local": {
                timeline: {
                  events: [{
                    event_id: "$live-message",
                    sender: "@manager:matrix.local",
                    origin_server_ts: 1760000000000,
                    type: "m.room.message",
                    content: { msgtype: "m.text", body: "Live from Matrix" },
                  }],
                },
              },
            },
          },
        };
      },
    };
    const controller = {
      getStatus: async () => ({
        data: { kubeMode: "embedded", totalWorkers: 1, totalTeams: 1, totalHumans: 1 },
        source: "controller" as const,
        endpoint: "/api/v1/status",
        receivedAt: "2026-09-02T10:00:00.000Z",
      }),
      getWorkers: async () => ({ data: { workers: [], total: 0 }, source: "controller" as const, endpoint: "/api/v1/workers", receivedAt: "2026-09-02T10:00:00.000Z" }),
      getTeams: async () => ({ data: { teams: [], total: 0 }, source: "controller" as const, endpoint: "/api/v1/teams", receivedAt: "2026-09-02T10:00:00.000Z" }),
      getManagers: async () => ({ data: { managers: [], total: 0 }, source: "controller" as const, endpoint: "/api/v1/managers", receivedAt: "2026-09-02T10:00:00.000Z" }),
    };

    const loop = new DashboardSyncLoop({
      matrix,
      controller,
      store,
      hub,
      matrixSyncTimeoutMs: 1,
      controllerPollIntervalMs: 60_000,
      reconnectDelayMs: 10,
    });
    await loop.start();

    await waitFor(async () => {
      const current = await store.snapshot();
      return current.cursor === "s-2"
        && current.sync.state === "live"
        && current.events.some((event) => event.id === "matrix:$live-message");
    });
    const snapshot = await store.snapshot();
    expect(snapshot.cursor).toBe("s-2");
    expect(snapshot.sync.state).toBe("live");
    expect(snapshot.events[0]).toMatchObject({
      kind: "message",
      roomId: "!room:matrix.local",
      summary: "Live from Matrix",
      actor: { displayName: "总控协调者" },
    });
    await expect(subscription.next()).resolves.toMatchObject({
      id: "matrix:$live-message",
      type: "observation",
    });

    await loop.stop();
  });
});
