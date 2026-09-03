import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { join } from "node:path";

import type { AgentTeamsEvent, DashboardProject, JsonObject } from "../types";
import { matrixMemberKey, reclassifyStoredEvent } from "./normalizer";

export type SyncState = "connecting" | "live" | "degraded" | "stopped";

export type EventStoreSnapshot = {
  version: 1;
  cursor?: string;
  events: AgentTeamsEvent[];
  projects: DashboardProject[];
  controller?: {
    data: JsonObject;
    receivedAt: string;
    endpoint: string;
  };
  sync: {
    state: SyncState;
    updatedAt?: string;
    lastEventAt?: string;
    lastError?: string;
  };
};

type EventStoreOptions = {
  dataDir?: string;
  maxEvents?: number;
};

const emptySnapshot = (): EventStoreSnapshot => ({
  version: 1,
  events: [],
  projects: [],
  sync: { state: "stopped" },
});

const cloneSnapshot = (snapshot: EventStoreSnapshot): EventStoreSnapshot =>
  JSON.parse(JSON.stringify(snapshot)) as EventStoreSnapshot;

export class EventStore {
  private readonly dataDir: string;
  private readonly statePath: string;
  private readonly maxEvents: number;
  private state: EventStoreSnapshot = emptySnapshot();
  private initialized = false;
  private writeChain: Promise<void> = Promise.resolve();

  constructor(options: EventStoreOptions = {}) {
    this.dataDir = options.dataDir || process.env.AGENTTEAMS_DASHBOARD_DATA_DIR || "/app/db";
    this.statePath = join(this.dataDir, "state.json");
    this.maxEvents = Math.max(100, options.maxEvents ?? 5_000);
  }

  async init(): Promise<void> {
    if (this.initialized) {
      return;
    }
    await mkdir(this.dataDir, { recursive: true });
    try {
      const raw = await readFile(this.statePath, "utf8");
      const loaded = JSON.parse(raw) as Partial<EventStoreSnapshot>;
      const loadedEvents = Array.isArray(loaded.events) ? loaded.events as AgentTeamsEvent[] : [];
      const migratedEvents = loadedEvents.map(reclassifyStoredEvent);
      const migrated = migratedEvents.some((event, index) => JSON.stringify(event) !== JSON.stringify(loadedEvents[index]));
      this.state = {
        ...emptySnapshot(),
        ...loaded,
        events: migratedEvents,
        projects: Array.isArray(loaded.projects) ? loaded.projects : [],
        sync: { ...emptySnapshot().sync, ...(loaded.sync || {}) },
      };
      this.initialized = true;
      if (migrated) {
        await this.persist();
      }
      return;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        throw new Error("Dashboard event store is not readable");
      }
      this.state = emptySnapshot();
    }
    this.initialized = true;
  }

  async snapshot(): Promise<EventStoreSnapshot> {
    await this.init();
    return cloneSnapshot(this.state);
  }

  async getProject(projectId: string): Promise<DashboardProject | undefined> {
    await this.init();
    return this.state.projects.find((project) => project.id === projectId);
  }

  async createProject(project: DashboardProject): Promise<void> {
    await this.init();
    if (this.state.projects.some((existing) => existing.id === project.id)) {
      throw new Error(`project ${project.id} already exists`);
    }
    this.state.projects = [...this.state.projects, project];
    await this.persist();
  }

  async updateProject(
    projectId: string,
    patch: Partial<Omit<DashboardProject, "id" | "createdAt">>,
  ): Promise<DashboardProject> {
    await this.init();
    const existing = this.state.projects.find((project) => project.id === projectId);
    if (!existing) {
      throw new Error(`project ${projectId} was not found`);
    }
    const updated: DashboardProject = {
      ...existing,
      ...patch,
      id: existing.id,
      createdAt: existing.createdAt,
      updatedAt: new Date().toISOString(),
    };
    this.state.projects = this.state.projects.map((project) => project.id === projectId ? updated : project);
    await this.persist();
    return updated;
  }

  async append(events: AgentTeamsEvent[]): Promise<AgentTeamsEvent[]> {
    await this.init();
    const known = new Set(this.state.events.map((event) => event.id));
    const fresh = events.filter((event) => {
      if (!event.id || known.has(event.id)) {
        return false;
      }
      known.add(event.id);
      return true;
    });
    if (!fresh.length) {
      return [];
    }
    this.state.events = [...this.state.events, ...fresh]
      .sort((left, right) => left.occurredAt.localeCompare(right.occurredAt) || left.id.localeCompare(right.id))
      .slice(-this.maxEvents);
    this.state.sync = {
      ...this.state.sync,
      lastEventAt: fresh[fresh.length - 1].occurredAt,
      updatedAt: new Date().toISOString(),
    };
    await this.persist();
    return fresh;
  }

  async enrichActorDisplayNames(displayNames: ReadonlyMap<string, string>): Promise<void> {
    await this.init();
    if (displayNames.size === 0) {
      return;
    }
    let changed = false;
    this.state.events = this.state.events.map((event) => {
      if (!event.actor || event.actor.displayName || !event.roomId) {
        return event;
      }
      const displayName = displayNames.get(matrixMemberKey(event.roomId, event.actor.id))?.trim();
      if (!displayName) {
        return event;
      }
      changed = true;
      return {
        ...event,
        actor: { ...event.actor, displayName },
      };
    });
    if (changed) {
      await this.persist();
    }
  }

  async setCursor(cursor: string): Promise<void> {
    await this.init();
    this.state.cursor = cursor;
    await this.persist();
  }

  async setControllerSnapshot(controller: EventStoreSnapshot["controller"]): Promise<void> {
    await this.init();
    this.state.controller = controller;
    await this.persist();
  }

  async setSyncState(
    state: SyncState,
    details: { error?: string } = {},
  ): Promise<void> {
    await this.init();
    const nextSync: EventStoreSnapshot["sync"] = {
      ...this.state.sync,
      state,
      updatedAt: new Date().toISOString(),
      ...(details.error ? { lastError: details.error } : {}),
    };
    if (state === "live" && !details.error) {
      delete nextSync.lastError;
    }
    this.state.sync = nextSync;
    await this.persist();
  }

  async since(eventId?: string): Promise<AgentTeamsEvent[]> {
    await this.init();
    if (!eventId) {
      return cloneSnapshot(this.state).events;
    }
    const index = this.state.events.findIndex((event) => event.id === eventId);
    return index < 0 ? cloneSnapshot(this.state).events : cloneSnapshot({ ...this.state, events: this.state.events.slice(index + 1) }).events;
  }

  private async persist(): Promise<void> {
    const snapshot = cloneSnapshot(this.state);
    this.writeChain = this.writeChain.then(async () => {
      const temporaryPath = join(this.dataDir, `.state.${randomUUID()}.tmp`);
      await writeFile(temporaryPath, `${JSON.stringify(snapshot, null, 2)}\n`, "utf8");
      await rename(temporaryPath, this.statePath);
    });
    return this.writeChain;
  }
}
