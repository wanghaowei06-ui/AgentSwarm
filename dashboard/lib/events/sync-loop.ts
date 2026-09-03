import { createHash } from "node:crypto";

import type { ControllerRead } from "../controller/client";
import type { JsonObject } from "../types";
import type { MatrixHistoryResponse, MatrixSyncResponse } from "../matrix/client";
import type { MatrixEvent, MatrixStateEvent } from "../matrix/types";
import { matrixMemberKey, normalizeMatrixEvent, sanitizeObservationValue } from "./normalizer";
import { EventHub } from "./hub";
import { EventStore } from "./store";

type MatrixSyncSource = {
  joinedRooms(): Promise<string[]>;
  roomState?(roomId: string): Promise<MatrixStateEvent[]>;
  history(roomId: string, options?: { limit?: number; from?: string; to?: string }): Promise<MatrixHistoryResponse>;
  sync(options?: { since?: string; timeoutMs?: number; filter?: string }): Promise<MatrixSyncResponse>;
};

type ControllerSource = {
  getStatus(): Promise<ControllerRead<JsonObject>>;
  getWorkers(): Promise<ControllerRead<JsonObject>>;
  getTeams(): Promise<ControllerRead<JsonObject>>;
  getManagers(): Promise<ControllerRead<JsonObject>>;
};

type DashboardSyncLoopOptions = {
  matrix: MatrixSyncSource;
  controller: ControllerSource;
  store: EventStore;
  hub: EventHub;
  matrixSyncTimeoutMs?: number;
  controllerPollIntervalMs?: number;
  reconnectDelayMs?: number;
};

const isObject = (value: unknown): value is JsonObject =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const stringValue = (value: unknown): string =>
  typeof value === "string" ? value.trim() : "";

const asMatrixEvent = (value: unknown, roomId: string): MatrixEvent | undefined => {
  if (!isObject(value) || typeof value.event_id !== "string" || typeof value.sender !== "string" || typeof value.type !== "string" || !isObject(value.content)) {
    return undefined;
  }
  if (typeof value.origin_server_ts !== "number") {
    return undefined;
  }
  return {
    event_id: value.event_id,
    room_id: typeof value.room_id === "string" ? value.room_id : roomId,
    sender: value.sender,
    origin_server_ts: value.origin_server_ts,
    type: value.type,
    content: value.content,
    unsigned: isObject(value.unsigned) ? value.unsigned : undefined,
  };
};

const syncTimelineEvents = (sync: MatrixSyncResponse): MatrixEvent[] => {
  const rooms = isObject(sync.rooms) && isObject(sync.rooms.join) ? sync.rooms.join : {};
  const result: MatrixEvent[] = [];
  for (const [roomId, value] of Object.entries(rooms)) {
    if (!isObject(value) || !isObject(value.timeline) || !Array.isArray(value.timeline.events)) {
      continue;
    }
    for (const rawEvent of value.timeline.events) {
      const event = asMatrixEvent(rawEvent, roomId);
      if (event) {
        result.push(event);
      }
    }
  }
  return result;
};

const historyEvents = (roomId: string, history: MatrixHistoryResponse): MatrixEvent[] => {
  if (!Array.isArray(history.chunk)) {
    return [];
  }
  return history.chunk
    .map((event) => asMatrixEvent(event, roomId))
    .filter((event): event is MatrixEvent => Boolean(event));
};

const roomMemberDisplayNames = async (
  matrix: MatrixSyncSource,
  roomIds: string[],
): Promise<ReadonlyMap<string, string>> => {
  if (!matrix.roomState) {
    return new Map();
  }
  const results = await Promise.allSettled(roomIds.map(async (roomId) => ({
    roomId,
    state: await matrix.roomState?.(roomId),
  })));
  const displayNames = new Map<string, string>();
  for (const result of results) {
    if (result.status !== "fulfilled" || !result.value.state) {
      continue;
    }
    for (const event of result.value.state) {
      if (event.type !== "m.room.member" || typeof event.state_key !== "string") {
        continue;
      }
      const displayName = stringValue(event.content.displayname);
      if (displayName) {
        displayNames.set(matrixMemberKey(result.value.roomId, event.state_key), displayName);
      }
    }
  }
  return displayNames;
};

const stableDigest = (value: unknown): string =>
  createHash("sha256").update(JSON.stringify(value)).digest("hex").slice(0, 16);

const controllerObservation = (read: ControllerRead<JsonObject>) => ({
  id: `controller:${read.endpoint}:${stableDigest(read.data)}`,
  source: "controller" as const,
  kind: "system" as const,
  occurredAt: read.receivedAt,
  summary: `Controller ${read.endpoint} responded`,
  detail: {
    endpoint: read.endpoint,
    data: sanitizeObservationValue(read.data),
  },
  sourceRef: { endpoint: read.endpoint },
});

const delay = (milliseconds: number, signal: AbortSignal): Promise<void> =>
  new Promise((resolve) => {
    const timer = setTimeout(resolve, milliseconds);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve();
    }, { once: true });
  });

export class DashboardSyncLoop {
  private readonly matrix: MatrixSyncSource;
  private readonly controller: ControllerSource;
  private readonly store: EventStore;
  private readonly hub: EventHub;
  private readonly matrixSyncTimeoutMs: number;
  private readonly controllerPollIntervalMs: number;
  private readonly reconnectDelayMs: number;
  private running = false;
  private abortController?: AbortController;
  private loopPromise?: Promise<void>;

  constructor(options: DashboardSyncLoopOptions) {
    this.matrix = options.matrix;
    this.controller = options.controller;
    this.store = options.store;
    this.hub = options.hub;
    this.matrixSyncTimeoutMs = options.matrixSyncTimeoutMs ?? 25_000;
    this.controllerPollIntervalMs = options.controllerPollIntervalMs ?? 10_000;
    this.reconnectDelayMs = options.reconnectDelayMs ?? 2_000;
  }

  async start(): Promise<void> {
    if (this.running) {
      return;
    }
    await this.store.init();
    this.running = true;
    this.abortController = new AbortController();
    await this.store.setSyncState("connecting");
    this.loopPromise = this.run(this.abortController.signal);
  }

  async stop(): Promise<void> {
    if (!this.running) {
      return;
    }
    this.running = false;
    this.abortController?.abort();
    await this.loopPromise;
    await this.store.setSyncState("stopped");
    this.loopPromise = undefined;
    this.abortController = undefined;
  }

  private async run(signal: AbortSignal): Promise<void> {
    let snapshot = await this.store.snapshot();
    let cursor = snapshot.cursor;
    let joinedRooms: string[] = [];
    let displayNames: ReadonlyMap<string, string> = new Map();
    let hydrateHistory = !cursor;
    let lastControllerPoll = 0;

    while (!signal.aborted) {
      try {
        if (!joinedRooms.length) {
          joinedRooms = await this.matrix.joinedRooms();
          displayNames = await roomMemberDisplayNames(this.matrix, joinedRooms);
          await this.store.enrichActorDisplayNames(displayNames);
        }
        const sync = await this.matrix.sync({
          since: cursor,
          timeoutMs: this.matrixSyncTimeoutMs,
        });
        const rawEvents = syncTimelineEvents(sync);
        if (hydrateHistory) {
          hydrateHistory = false;
          const historyResults = await Promise.allSettled(
            joinedRooms.map((roomId) => this.matrix.history(roomId, { limit: 100 })),
          );
          historyResults.forEach((result, index) => {
            if (result.status === "fulfilled") {
              rawEvents.push(...historyEvents(joinedRooms[index], result.value));
            }
          });
        }
        const normalized = rawEvents.map((event) => normalizeMatrixEvent(event, displayNames));
        const fresh = await this.store.append(normalized);
        for (const event of fresh) {
          this.hub.publish({ id: event.id, type: "observation", data: event });
          if (event.runId || event.kind === "workflow") {
            this.hub.publish({ id: `${event.id}:run`, type: "run.updated", data: event });
          }
        }
        cursor = sync.next_batch;
        await this.store.setCursor(cursor);
        await this.store.setSyncState("live");
        this.hub.publish({
          id: `sync:${cursor}`,
          type: "sync.status",
          data: { state: "live", cursor },
        });

        if (Date.now() - lastControllerPoll >= this.controllerPollIntervalMs) {
          lastControllerPoll = Date.now();
          await this.pollController();
        }
        snapshot = await this.store.snapshot();
        if (snapshot.cursor !== cursor) {
          cursor = snapshot.cursor || cursor;
        }
      } catch (error) {
        if (signal.aborted) {
          break;
        }
        const message = error instanceof Error ? error.message : "Matrix sync failed";
        await this.store.setSyncState("degraded", { error: message });
        const event = {
          id: `system:sync-error:${Date.now()}`,
          source: "matrix" as const,
          kind: "system" as const,
          occurredAt: new Date().toISOString(),
          summary: `Matrix sync degraded: ${message}`,
          detail: { state: "degraded", error: message },
          sourceRef: {},
        };
        const fresh = await this.store.append([event]);
        for (const observation of fresh) {
          this.hub.publish({ id: observation.id, type: "observation", data: observation });
        }
        this.hub.publish({
          id: `sync:degraded:${Date.now()}`,
          type: "sync.status",
          data: { state: "degraded", error: message },
        });
        await delay(this.reconnectDelayMs, signal);
        joinedRooms = [];
      }
    }
  }

  private async pollController(): Promise<void> {
    const reads = await Promise.allSettled([
      this.controller.getStatus(),
      this.controller.getWorkers(),
      this.controller.getTeams(),
      this.controller.getManagers(),
    ]);
    const fulfilled = reads.filter(
      (result): result is PromiseFulfilledResult<ControllerRead<JsonObject>> => result.status === "fulfilled",
    );
    if (!fulfilled.length) {
      return;
    }
    const data: JsonObject = {};
    for (const result of fulfilled) {
      data[result.value.endpoint] = sanitizeObservationValue(result.value.data);
      const event = controllerObservation(result.value);
      const fresh = await this.store.append([event]);
      for (const observation of fresh) {
        this.hub.publish({ id: observation.id, type: "observation", data: observation });
      }
    }
    const latest = fulfilled.map((result) => result.value.receivedAt).sort().at(-1) || new Date().toISOString();
    await this.store.setControllerSnapshot({
      data,
      receivedAt: latest,
      endpoint: "/api/v1/status",
    });
    this.hub.publish({
      id: `controller:${latest}`,
      type: "controller.updated",
      data: { data, receivedAt: latest },
    });
  }
}
