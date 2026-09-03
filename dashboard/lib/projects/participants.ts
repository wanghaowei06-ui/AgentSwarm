import type { AgentTeamsEvent, JsonObject } from "../types";

export type MatrixParticipantRole = "manager" | "leader" | "worker";

export type MatrixParticipant = {
  userId: string;
  name: string;
  role: MatrixParticipantRole;
  displayName?: string;
};

type ControllerRecord = JsonObject;

const isObject = (value: unknown): value is JsonObject =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const stringValue = (value: unknown): string =>
  typeof value === "string" ? value.trim() : "";

const recordsAt = (controllerData: JsonObject | undefined, endpoint: string, key: string): ControllerRecord[] => {
  const response = controllerData?.[endpoint];
  if (!isObject(response) || !Array.isArray(response[key])) {
    return [];
  }
  return response[key].filter(isObject);
};

const firstString = (record: ControllerRecord, keys: string[]): string => {
  for (const key of keys) {
    const value = stringValue(record[key]);
    if (value) {
      return value;
    }
  }
  return "";
};

const userIdOf = (record: ControllerRecord): string => firstString(record, [
  "matrixUserID",
  "matrixUserId",
  "matrix_user_id",
  "userId",
  "userID",
]);

const leaderUserIdOf = (record: ControllerRecord): string => firstString(record, [
  "leaderMatrixUserID",
  "leaderMatrixUserId",
  "leaderUserID",
  "leaderUserId",
  "leader_matrix_user_id",
  "leader_user_id",
]);

const roleOf = (record: ControllerRecord, fallback: MatrixParticipantRole): MatrixParticipantRole => {
  const role = firstString(record, ["role", "memberRole"]).toLowerCase();
  return role.includes("leader") ? "leader" : fallback;
};

const participantNameOf = (record: ControllerRecord, fallback: string): string =>
  firstString(record, ["name", "workerName", "runtimeName", "displayName", "displayname"]) || fallback;

const observedDisplayNames = (events: AgentTeamsEvent[]): ReadonlyMap<string, string> => {
  const result = new Map<string, string>();
  for (const event of [...events].sort((left, right) => right.occurredAt.localeCompare(left.occurredAt))) {
    const userId = stringValue(event.actor?.id).toLowerCase();
    const displayName = stringValue(event.actor?.displayName);
    if (userId && displayName && !result.has(userId)) {
      result.set(userId, displayName);
    }
  }
  return result;
};

const roleRank: Record<MatrixParticipantRole, number> = {
  worker: 1,
  leader: 2,
  manager: 3,
};

export const projectParticipants = (
  controllerData: JsonObject | undefined,
  events: AgentTeamsEvent[] = [],
): MatrixParticipant[] => {
  const managers = recordsAt(controllerData, "/api/v1/managers", "managers");
  const teams = recordsAt(controllerData, "/api/v1/teams", "teams");
  const workers = recordsAt(controllerData, "/api/v1/workers", "workers");
  const displayNames = observedDisplayNames(events);
  const participants = new Map<string, MatrixParticipant>();

  const add = (
    userId: string,
    name: string,
    role: MatrixParticipantRole,
  ): void => {
    const normalizedUserId = userId.trim();
    if (!normalizedUserId) {
      return;
    }
    const key = normalizedUserId.toLowerCase();
    const existing = participants.get(key);
    const displayName = displayNames.get(key);
    if (existing && roleRank[existing.role] >= roleRank[role]) {
      if (!existing.displayName && displayName) {
        participants.set(key, { ...existing, displayName });
      }
      return;
    }
    participants.set(key, {
      userId: normalizedUserId,
      name: name.trim() || existing?.name || normalizedUserId,
      role,
      ...(displayName ? { displayName } : existing?.displayName ? { displayName: existing.displayName } : {}),
    });
  };

  for (const manager of managers) {
    add(userIdOf(manager), participantNameOf(manager, "Manager"), "manager");
  }

  for (const team of teams) {
    const teamName = firstString(team, ["teamName", "name"]) || "Team";
    const leaderUserId = leaderUserIdOf(team);
    const leaderName = firstString(team, ["leaderName", "leaderRuntimeName"]) || teamName;
    add(leaderUserId, leaderName, "leader");

    const members = [
      ...(Array.isArray(team.members) ? team.members : []),
      ...(Array.isArray(team.workerMembers) ? team.workerMembers : []),
    ];
    for (const member of members) {
      if (!isObject(member)) {
        continue;
      }
      const memberRole = roleOf(member, "worker");
      add(
        userIdOf(member),
        participantNameOf(member, teamName),
        memberRole,
      );
    }
  }

  const leaderNames = new Set(
    teams.flatMap((team) => [
      firstString(team, ["leaderName", "leaderRuntimeName"]).toLowerCase(),
    ]).filter(Boolean),
  );
  for (const worker of workers) {
    const workerName = participantNameOf(worker, "Worker");
    const role = roleOf(worker, leaderNames.has(workerName.toLowerCase()) ? "leader" : "worker");
    add(userIdOf(worker), workerName, role);
  }

  return [...participants.values()].sort((left, right) =>
    roleRank[right.role] - roleRank[left.role] || left.name.localeCompare(right.name),
  );
};
