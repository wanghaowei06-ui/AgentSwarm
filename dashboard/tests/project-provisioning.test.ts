import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { EventStore } from "../lib/events/store";
import type { MatrixCreateRoomOptions } from "../lib/matrix/client";
import type { MatrixRoomMember } from "../lib/matrix/types";
import {
  projectParticipants,
  type MatrixParticipant,
} from "../lib/projects/participants";
import {
  DashboardProjectProvisioner,
  type ProjectCreateInput,
} from "../lib/projects/provisioning";
import type { AgentTeamsEvent, JsonObject } from "../lib/types";

const controllerData: JsonObject = {
  "/api/v1/managers": {
    managers: [{ name: "default", matrixUserID: "@manager:matrix.local" }],
  },
  "/api/v1/teams": {
    teams: [{
      name: "research-team",
      leaderName: "research-lead",
      leaderMatrixUserID: "@leader:matrix.local",
      leaderDMRoomID: "!leader-dm:matrix.local",
    }],
  },
  "/api/v1/workers": {
    workers: [
      {
        name: "research-lead",
        matrixUserID: "@leader:matrix.local",
        role: "team_leader",
      },
      {
        name: "research-worker",
        matrixUserID: "@worker:matrix.local",
        role: "worker",
      },
    ],
  },
};

const event = (overrides: Partial<AgentTeamsEvent>): AgentTeamsEvent => ({
  id: "matrix:$display-name",
  source: "matrix",
  kind: "message",
  occurredAt: "2026-09-03T10:00:00.000Z",
  roomId: "!worker:matrix.local",
  actor: {
    id: "@worker:matrix.local",
    label: "research-worker",
    displayName: "证据分析员",
    role: "worker",
  },
  summary: "worker update",
  sourceRef: { eventId: "$display-name" },
  ...overrides,
});

class FakeMatrix {
  readonly createdRoomNames: string[] = [];
  readonly createRoomCalls: MatrixCreateRoomOptions[] = [];
  private readonly roomStates = new Map<string, MatrixRoomMember[]>();
  private createCount = 0;

  constructor(
    private readonly options: {
      joinedRooms?: string[];
      currentUserId?: string;
      failAtCreate?: number;
      existingMembers?: Record<string, MatrixRoomMember[]>;
    } = {},
  ) {
    for (const [roomId, members] of Object.entries(options.existingMembers || {})) {
      this.roomStates.set(roomId, members);
    }
  }

  async whoAmI(): Promise<string> {
    return this.options.currentUserId || "@admin:matrix.local";
  }

  async joinedRooms(): Promise<string[]> {
    return this.options.joinedRooms || [];
  }

  async roomMembers(roomId: string): Promise<MatrixRoomMember[]> {
    return this.roomStates.get(roomId) || [];
  }

  async createRoom(options: MatrixCreateRoomOptions): Promise<{ roomId: string }> {
    if (this.options.failAtCreate === this.createCount) {
      throw new Error("Matrix createRoom failed after the first room");
    }
    this.createCount += 1;
    this.createdRoomNames.push(options.name);
    this.createRoomCalls.push(options);
    const roomId = `!created-${this.createCount}:matrix.local`;
    this.roomStates.set(roomId, [
      { userId: "@admin:matrix.local", membership: "join" },
      ...options.invite.map((userId) => ({ userId, membership: "invite" })),
    ]);
    return { roomId };
  }
}

const createProvisioner = async (
  matrix: FakeMatrix,
): Promise<DashboardProjectProvisioner> => {
  const dataDir = await mkdtemp(join(tmpdir(), "agentteams-dashboard-project-"));
  return new DashboardProjectProvisioner({
    matrix,
    store: new EventStore({ dataDir }),
    controllerData,
    events: [event({})],
  });
};

describe("projectParticipants", () => {
  it("deduplicates Controller participants and enriches observed display names", () => {
    const participants = projectParticipants(controllerData, [
      event({
        id: "matrix:$leader-display-name",
        actor: {
          id: "@leader:matrix.local",
          label: "research-lead",
          displayName: "研究组长",
          role: "worker",
        },
      }),
      event({}),
    ]);

    expect(participants).toEqual<MatrixParticipant[]>([
      {
        userId: "@manager:matrix.local",
        name: "default",
        role: "manager",
      },
      {
        userId: "@leader:matrix.local",
        name: "research-lead",
        role: "leader",
        displayName: "研究组长",
      },
      {
        userId: "@worker:matrix.local",
        name: "research-worker",
        role: "worker",
        displayName: "证据分析员",
      },
    ]);
  });
});

describe("DashboardProjectProvisioner", () => {
  it("creates one Manager DM and each requested project room", async () => {
    const matrix = new FakeMatrix();
    const provisioner = await createProvisioner(matrix);
    const input: ProjectCreateInput = {
      kind: "project",
      name: "材料核验",
      roomNames: ["主讨论", "交付"],
      inviteUserIds: ["@worker:matrix.local"],
    };

    const result = await provisioner.create(input);

    expect(result.project.status).toBe("active");
    expect(result.project.rooms.map((room) => room.name)).toEqual([
      "Manager 私聊",
      "主讨论",
      "交付",
    ]);
    expect(matrix.createdRoomNames).toEqual(["Manager 私聊", "主讨论", "交付"]);
    expect(matrix.createRoomCalls[0]).toMatchObject({
      invite: ["@manager:matrix.local"],
      isDirect: true,
    });
    expect(matrix.createRoomCalls[1]).toMatchObject({
      invite: ["@manager:matrix.local", "@worker:matrix.local"],
      isDirect: false,
    });
  });

  it("reuses an existing two-member Manager DM", async () => {
    const matrix = new FakeMatrix({
      joinedRooms: ["!existing-dm:matrix.local"],
      existingMembers: {
        "!existing-dm:matrix.local": [
          { userId: "@admin:matrix.local", membership: "join" },
          { userId: "@manager:matrix.local", membership: "join" },
        ],
      },
    });
    const provisioner = await createProvisioner(matrix);

    const result = await provisioner.create({ kind: "manager-dm" });

    expect(result.reused).toBe(true);
    expect(matrix.createRoomCalls).toHaveLength(0);
    expect(result.project.managerRoomId).toBe("!existing-dm:matrix.local");
  });

  it("rejects an invite that is not in the current Controller participants", async () => {
    const matrix = new FakeMatrix();
    const provisioner = await createProvisioner(matrix);

    await expect(provisioner.create({
      kind: "project",
      name: "材料核验",
      roomNames: ["主讨论"],
      inviteUserIds: ["@unknown:matrix.local"],
    })).rejects.toMatchObject({ status: 400 });
    expect(matrix.createRoomCalls).toHaveLength(0);
  });

  it("persists a failed project with the first real room when a later room fails", async () => {
    const matrix = new FakeMatrix({ failAtCreate: 1 });
    const provisioner = await createProvisioner(matrix);

    const result = await provisioner.create({
      kind: "project",
      name: "材料核验",
      roomNames: ["主讨论", "交付"],
    });

    expect(result.project.status).toBe("failed");
    expect(result.project.rooms.map((room) => room.roomId)).toEqual([
      "!created-1:matrix.local",
    ]);
    expect(result.project.error).toContain("after the first room");
  });
});
