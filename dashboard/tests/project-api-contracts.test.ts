import { describe, expect, it, vi } from "vitest";

import { parseProjectBody } from "../lib/api/contracts";
import { POST as postProjects } from "../app/api/projects/route";
import { GET as getProject } from "../app/api/projects/[projectId]/route";
import { POST as postProjectMessage } from "../app/api/projects/[projectId]/messages/route";

const runtime = vi.hoisted(() => ({
  matrix: {
    sendMessage: vi.fn(),
    whoAmI: vi.fn(),
    joinedRooms: vi.fn(),
    roomMembers: vi.fn(),
    createRoom: vi.fn(),
  },
  store: {
    snapshot: vi.fn(),
    createProject: vi.fn(),
    updateProject: vi.fn(),
  },
  controller: {
    getManagers: vi.fn(),
    getWorkers: vi.fn(),
    getTeams: vi.fn(),
  },
  hub: { publish: vi.fn() },
}));

vi.mock("../lib/runtime", () => ({
  ensureDashboardRuntime: vi.fn(async () => runtime),
}));

const project = {
  id: "dashboard-project:receipt",
  kind: "project" as const,
  name: "材料核验",
  status: "active" as const,
  managerUserId: "@manager:matrix.local",
  managerRoomId: "!manager:matrix.local",
  rooms: [],
  createdAt: "2026-09-03T10:00:00.000Z",
  updatedAt: "2026-09-03T10:00:00.000Z",
};

const snapshotFor = (projects: unknown[]) => ({
  version: 1 as const,
  events: [],
  projects,
  sync: { state: "live" as const },
});

describe("project API contracts", () => {
  it("parses the two supported project creation shapes", () => {
    expect(parseProjectBody({ kind: "manager-dm" })).toEqual({ kind: "manager-dm" });
    expect(parseProjectBody({
      kind: "project",
      name: " 材料核验 ",
      roomNames: [" 主讨论 ", "交付"],
      inviteUserIds: [" @worker:matrix.local "],
      managerUserId: " @manager:matrix.local ",
    })).toEqual({
      kind: "project",
      name: "材料核验",
      roomNames: ["主讨论", "交付"],
      inviteUserIds: ["@worker:matrix.local"],
      managerUserId: "@manager:matrix.local",
    });
  });

  it("rejects missing project names and room names", () => {
    expect(() => parseProjectBody({ kind: "project", name: "", roomNames: ["主讨论"] }))
      .toThrow("project name");
    expect(() => parseProjectBody({ kind: "project", name: "P", roomNames: [] }))
      .toThrow("at least one room");
  });

  it("rejects malformed project participant fields and duplicate room names", () => {
    expect(() => parseProjectBody({ kind: "project", name: "P", roomNames: ["A", " a "] }))
      .toThrow("unique");
    expect(() => parseProjectBody({ kind: "project", name: "P", roomNames: ["A"], inviteUserIds: "@worker" }))
      .toThrow("inviteUserIds");
    expect(() => parseProjectBody({ kind: "manager-dm", managerUserId: 42 }))
      .toThrow("managerUserId");
  });

  it("returns 404 for an unknown project detail", async () => {
    runtime.store.snapshot.mockResolvedValueOnce(snapshotFor([]));

    const response = await getProject(new Request("http://dashboard.test/api/projects/missing"), {
      params: Promise.resolve({ projectId: "missing" }),
    });

    expect(response.status).toBe(404);
  });

  it("rejects messages for a project that is not active", async () => {
    runtime.store.snapshot.mockResolvedValueOnce(snapshotFor([{ ...project, status: "provisioning" }]));

    const response = await postProjectMessage(new Request("http://dashboard.test/api/projects/dashboard-project%3Areceipt/messages", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text: "继续" }),
    }), {
      params: Promise.resolve({ projectId: "dashboard-project%3Areceipt" }),
    });

    expect(response.status).toBe(409);
    expect(runtime.matrix.sendMessage).not.toHaveBeenCalled();
  });

  it("sends a project message to its real Manager room", async () => {
    runtime.store.snapshot.mockResolvedValueOnce(snapshotFor([project]));
    runtime.matrix.sendMessage.mockResolvedValueOnce({ eventId: "$sent", txnId: "txn-1" });

    const response = await postProjectMessage(new Request("http://dashboard.test/api/projects/dashboard-project%3Areceipt/messages", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text: "继续", threadRootEventId: "$root" }),
    }), {
      params: Promise.resolve({ projectId: "dashboard-project%3Areceipt" }),
    });

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({
      accepted: true,
      eventId: "$sent",
      txnId: "txn-1",
    });
    expect(runtime.matrix.sendMessage).toHaveBeenCalledWith("!manager:matrix.local", "继续", {
      threadRootEventId: "$root",
    });
  });

  it("creates projects from fresh Controller participants and returns the real room records", async () => {
    const projects: Record<string, unknown>[] = [];
    runtime.store.snapshot.mockResolvedValueOnce(snapshotFor([]));
    runtime.controller.getManagers.mockResolvedValueOnce({
      data: { managers: [{ name: "default", matrixUserID: "@manager:matrix.local" }] },
      source: "controller",
      endpoint: "/api/v1/managers",
      receivedAt: "2026-09-03T10:00:00.000Z",
    });
    runtime.controller.getWorkers.mockResolvedValueOnce({
      data: { workers: [{ name: "worker", matrixUserID: "@worker:matrix.local", role: "worker" }] },
      source: "controller",
      endpoint: "/api/v1/workers",
      receivedAt: "2026-09-03T10:00:00.000Z",
    });
    runtime.controller.getTeams.mockResolvedValueOnce({
      data: { teams: [] },
      source: "controller",
      endpoint: "/api/v1/teams",
      receivedAt: "2026-09-03T10:00:00.000Z",
    });
    runtime.matrix.whoAmI.mockResolvedValueOnce("@admin:matrix.local");
    runtime.matrix.createRoom
      .mockResolvedValueOnce({ roomId: "!manager:matrix.local" })
      .mockResolvedValueOnce({ roomId: "!project:matrix.local" });
    runtime.store.createProject.mockImplementationOnce(async (created) => {
      projects.push(created);
    });
    runtime.store.updateProject.mockImplementation(async (projectId, patch) => {
      const existing = projects.find((candidate) => candidate.id === projectId);
      if (!existing) {
        throw new Error(`project ${projectId} not found`);
      }
      const updated = { ...existing, ...patch, id: projectId };
      projects.splice(projects.indexOf(existing), 1, updated);
      return updated;
    });

    const response = await postProjects(new Request("http://dashboard.test/api/projects", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        kind: "project",
        name: "材料核验",
        roomNames: ["主讨论"],
        inviteUserIds: ["@worker:matrix.local"],
      }),
    }));

    expect(response.status).toBe(201);
    const body = await response.json();
    expect(body.project).toMatchObject({
      name: "材料核验",
      status: "active",
      managerRoomId: "!manager:matrix.local",
    });
    expect(body.project.rooms.map((room: { roomId: string }) => room.roomId)).toEqual([
      "!manager:matrix.local",
      "!project:matrix.local",
    ]);
    expect(runtime.controller.getManagers).toHaveBeenCalledOnce();
    expect(runtime.matrix.createRoom).toHaveBeenCalledTimes(2);
    expect(runtime.hub.publish).toHaveBeenCalled();
  });
});
