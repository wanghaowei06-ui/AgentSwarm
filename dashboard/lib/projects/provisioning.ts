import { randomUUID } from "node:crypto";

import type { AgentTeamsEvent, DashboardProject, DashboardProjectRoom, JsonObject } from "../types";
import type { EventStore } from "../events/store";
import type { MatrixCreateRoomOptions } from "../matrix/client";
import type { MatrixRoomMember } from "../matrix/types";
import { projectParticipants, type MatrixParticipant } from "./participants";

export type ProjectCreateInput =
  | {
    kind: "manager-dm";
    managerUserId?: string;
  }
  | {
    kind: "project";
    name: string;
    roomNames: string[];
    inviteUserIds?: string[];
    managerUserId?: string;
  };

export type ProjectMatrixClient = {
  whoAmI(): Promise<string>;
  joinedRooms(): Promise<string[]>;
  roomMembers(roomId: string): Promise<MatrixRoomMember[]>;
  createRoom(options: MatrixCreateRoomOptions): Promise<{ roomId: string }>;
};

type ProjectStore = Pick<EventStore, "snapshot" | "createProject" | "updateProject">;

export type DashboardProjectProvisionerOptions = {
  matrix: ProjectMatrixClient;
  store: ProjectStore;
  controllerData?: JsonObject;
  events?: AgentTeamsEvent[];
};

export type ProjectCreateResult = {
  project: DashboardProject;
  reused: boolean;
};

export class ProjectProvisioningError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(message: string, options: { status: number; code: string }) {
    super(message);
    this.name = "ProjectProvisioningError";
    this.status = options.status;
    this.code = options.code;
  }
}

const normalizedId = (value: string): string => value.trim().toLowerCase();

const uniqueUserIds = (userIds: string[]): string[] => {
  const seen = new Set<string>();
  return userIds.flatMap((userId) => {
    const trimmed = userId.trim();
    const key = normalizedId(trimmed);
    if (!key || seen.has(key)) {
      return [];
    }
    seen.add(key);
    return [trimmed];
  });
};

const errorMessage = (error: unknown): string =>
  error instanceof Error && error.message.trim() ? error.message.trim() : "Matrix room provisioning failed";

const roomRecord = (
  roomId: string,
  name: string,
  kind: DashboardProjectRoom["kind"],
  inviteUserIds: string[],
): DashboardProjectRoom => ({
  roomId,
  name,
  kind,
  inviteUserIds,
  createdAt: new Date().toISOString(),
});

const exactTwoMemberDm = (
  members: MatrixRoomMember[],
  currentUserId: string,
  managerUserId: string,
): boolean => {
  const joined = new Set(
    members
      .filter((member) => member.membership === "join")
      .map((member) => normalizedId(member.userId))
      .filter(Boolean),
  );
  return joined.size === 2
    && joined.has(normalizedId(currentUserId))
    && joined.has(normalizedId(managerUserId));
};

export class DashboardProjectProvisioner {
  private readonly matrix: ProjectMatrixClient;
  private readonly store: ProjectStore;
  private readonly controllerData?: JsonObject;
  private readonly events: AgentTeamsEvent[];

  constructor(options: DashboardProjectProvisionerOptions) {
    this.matrix = options.matrix;
    this.store = options.store;
    this.controllerData = options.controllerData;
    this.events = options.events || [];
  }

  async create(input: ProjectCreateInput): Promise<ProjectCreateResult> {
    const participants = projectParticipants(this.controllerData, this.events);
    const manager = this.selectManager(input.managerUserId, participants);
    if (input.kind === "project") {
      this.validateProjectInput(input, participants);
    }
    const currentUserId = await this.matrix.whoAmI();
    if (normalizedId(currentUserId) === normalizedId(manager.userId)) {
      throw new ProjectProvisioningError("Dashboard account cannot open a Manager DM with itself", {
        status: 409,
        code: "manager_dm_unavailable",
      });
    }

    if (input.kind === "manager-dm") {
      return this.createManagerDm(manager, currentUserId);
    }
    return this.createProject(input, manager);
  }

  private selectManager(requestedUserId: string | undefined, participants: MatrixParticipant[]): MatrixParticipant {
    const managers = participants.filter((participant) => participant.role === "manager");
    if (!managers.length) {
      throw new ProjectProvisioningError("no current Manager with a Matrix user ID is available", {
        status: 409,
        code: "manager_unavailable",
      });
    }
    if (!requestedUserId?.trim()) {
      return managers[0];
    }
    const manager = managers.find((candidate) => normalizedId(candidate.userId) === normalizedId(requestedUserId));
    if (!manager) {
      throw new ProjectProvisioningError("selected Manager is not a current Controller participant", {
        status: 400,
        code: "invalid_manager",
      });
    }
    return manager;
  }

  private validateProjectInput(
    input: Extract<ProjectCreateInput, { kind: "project" }>,
    participants: MatrixParticipant[],
  ): void {
    if (!input.name.trim()) {
      throw new ProjectProvisioningError("project name is required", {
        status: 400,
        code: "invalid_project",
      });
    }
    const roomNames = input.roomNames.map((name) => name.trim()).filter(Boolean);
    if (!roomNames.length) {
      throw new ProjectProvisioningError("at least one project room is required", {
        status: 400,
        code: "invalid_project",
      });
    }
    const participantIds = new Set(participants.map((participant) => normalizedId(participant.userId)));
    for (const userId of uniqueUserIds(input.inviteUserIds || [])) {
      if (!participantIds.has(normalizedId(userId))) {
        throw new ProjectProvisioningError(`invite participant ${userId} is not a current Controller participant`, {
          status: 400,
          code: "invalid_participant",
        });
      }
    }
  }

  private async findReusableManagerRoom(currentUserId: string, managerUserId: string): Promise<string | undefined> {
    const roomIds = await this.matrix.joinedRooms();
    const checks = await Promise.allSettled(roomIds.map(async (roomId) => ({
      roomId,
      members: await this.matrix.roomMembers(roomId),
    })));
    for (const result of checks) {
      if (result.status === "fulfilled" && exactTwoMemberDm(result.value.members, currentUserId, managerUserId)) {
        return result.value.roomId;
      }
    }
    return undefined;
  }

  private newProject(
    kind: DashboardProject["kind"],
    name: string,
    managerUserId: string,
  ): DashboardProject {
    const timestamp = new Date().toISOString();
    return {
      id: `dashboard-project:${randomUUID()}`,
      kind,
      name,
      status: "provisioning",
      managerUserId,
      rooms: [],
      createdAt: timestamp,
      updatedAt: timestamp,
    };
  }

  private async createManagerDm(
    manager: MatrixParticipant,
    currentUserId: string,
  ): Promise<ProjectCreateResult> {
    const reusableRoomId = await this.findReusableManagerRoom(currentUserId, manager.userId);
    if (reusableRoomId) {
      const existing = (await this.store.snapshot()).projects.find((project) =>
        project.kind === "manager-dm"
        && project.status === "active"
        && project.managerRoomId === reusableRoomId,
      );
      if (existing) {
        return { project: existing, reused: true };
      }
      const project = this.newProject("manager-dm", "Manager 私聊", manager.userId);
      const room = roomRecord(reusableRoomId, "Manager 私聊", "manager", [manager.userId]);
      const activeProject: DashboardProject = {
        ...project,
        status: "active",
        managerRoomId: reusableRoomId,
        rooms: [room],
      };
      await this.store.createProject(activeProject);
      return { project: activeProject, reused: true };
    }

    const project = this.newProject("manager-dm", "Manager 私聊", manager.userId);
    await this.store.createProject(project);
    return this.createRooms(project, manager.userId, [
      { name: "Manager 私聊", kind: "manager", inviteUserIds: [manager.userId], isDirect: true },
    ], false);
  }

  private async createProject(
    input: Extract<ProjectCreateInput, { kind: "project" }>,
    manager: MatrixParticipant,
  ): Promise<ProjectCreateResult> {
    const managerInvite = manager.userId;
    const inviteUserIds = uniqueUserIds([managerInvite, ...(input.inviteUserIds || [])]);
    const project = this.newProject("project", input.name.trim(), manager.userId);
    const rooms = [
      { name: "Manager 私聊", kind: "manager" as const, inviteUserIds: [managerInvite], isDirect: true },
      ...input.roomNames.map((name) => ({
        name: name.trim(),
        kind: "project" as const,
        inviteUserIds,
        isDirect: false,
      })),
    ];
    await this.store.createProject(project);
    return this.createRooms(project, manager.userId, rooms, false);
  }

  private async createRooms(
    initialProject: DashboardProject,
    managerUserId: string,
    rooms: Array<{
      name: string;
      kind: DashboardProjectRoom["kind"];
      inviteUserIds: string[];
      isDirect: boolean;
    }>,
    reused: boolean,
  ): Promise<ProjectCreateResult> {
    let project = initialProject;
    try {
      for (const room of rooms) {
        const createOptions: MatrixCreateRoomOptions = {
          name: room.name,
          invite: uniqueUserIds(room.inviteUserIds),
          isDirect: room.isDirect,
        };
        const created = await this.matrix.createRoom(createOptions);
        project = await this.store.updateProject(project.id, {
          managerRoomId: room.kind === "manager" ? created.roomId : project.managerRoomId,
          rooms: [...project.rooms, roomRecord(created.roomId, room.name, room.kind, createOptions.invite)],
        });
      }
      project = await this.store.updateProject(project.id, {
        status: "active",
        managerRoomId: project.managerRoomId || project.rooms.find((room) => room.kind === "manager")?.roomId,
      });
      return { project, reused };
    } catch (error) {
      project = await this.store.updateProject(project.id, {
        status: "failed",
        error: errorMessage(error),
        managerUserId,
      });
      return { project, reused: false };
    }
  }
}
