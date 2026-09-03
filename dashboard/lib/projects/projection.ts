import type {
  AgentTeamsEvent,
  AttentionItem,
  ConversationDetail,
  ConversationRoom,
  ConversationStatus,
  ConversationSummary,
  DashboardProject,
  JsonObject,
  RoomSummary,
} from "../types";
import { eventEvidenceCategory, isPriorityEvidence } from "../events/evidence";
import { compactInboxPreview } from "../inbox/preview";

const stringValue = (value: unknown): string =>
  typeof value === "string" ? value.trim() : "";

const isObject = (value: unknown): value is JsonObject =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const activeEvents = (events: AgentTeamsEvent[]): AgentTeamsEvent[] => {
  const supersededIds = new Set(
    events.flatMap((event) => {
      const editedEventId = stringValue(event.detail?.editedEventId);
      return editedEventId ? [editedEventId] : [];
    }),
  );
  return events.filter((event) => {
    const sourceEventId = event.sourceRef.eventId || "";
    return !supersededIds.has(event.id) && !supersededIds.has(sourceEventId);
  });
};

const roomSummary = (roomId: string, events: AgentTeamsEvent[], label: string): RoomSummary => {
  const scoped = events.filter((event) => event.roomId === roomId);
  const latest = [...scoped].sort((left, right) => right.occurredAt.localeCompare(left.occurredAt))[0];
  return {
    roomId,
    label,
    latestAt: latest?.occurredAt || "",
    eventCount: scoped.length,
    messageCount: scoped.filter((event) => event.kind === "message").length,
  };
};

const attentionFor = (event: AgentTeamsEvent): AttentionItem[] => {
  const status = stringValue(event.detail?.status).toLowerCase();
  if (event.kind === "workflow" && ["failed", "error", "waiting", "blocked"].includes(status)) {
    return [{
      id: `attention:${event.id}`,
      severity: status === "waiting" || status === "blocked" ? "warning" : "error",
      summary: event.summary,
      runId: event.runId,
      sourceEventId: event.sourceRef.eventId,
    }];
  }
  if ((event.kind === "tool" || event.kind === "skill") && ["failed", "error"].includes(status)) {
    return [{
      id: `attention:${event.id}`,
      severity: "error",
      summary: `${event.summary} · requires review`,
      runId: event.runId,
      sourceEventId: event.sourceRef.eventId,
    }];
  }
  if (event.kind === "system" && /degraded|unavailable|error|failed/i.test(event.summary)) {
    return [{
      id: `attention:${event.id}`,
      severity: "warning",
      summary: event.summary,
      runId: event.runId,
      sourceEventId: event.sourceRef.eventId,
    }];
  }
  return [];
};

const managerNameFor = (
  project: DashboardProject,
  events: AgentTeamsEvent[],
  controllerData?: JsonObject,
): string => {
  const managerUserId = project.managerUserId.toLowerCase();
  const observed = events.find((event) =>
    event.actor?.id.toLowerCase() === managerUserId && event.actor.displayName,
  )?.actor?.displayName;
  if (observed) {
    return observed;
  }
  const managers = controllerData?.["/api/v1/managers"];
  if (isObject(managers) && Array.isArray(managers.managers)) {
    const manager = managers.managers.find((candidate) => isObject(candidate)
      && (stringValue(candidate.matrixUserID) || stringValue(candidate.matrixUserId)).toLowerCase() === managerUserId);
    if (isObject(manager)) {
      return stringValue(manager.displayName)
        || stringValue(manager.displayname)
        || stringValue(manager.name)
        || "Manager";
    }
  }
  return "Manager";
};

const projectRooms = (project: DashboardProject, events: AgentTeamsEvent[]): ConversationRoom[] =>
  project.rooms.map((projectRoom) => ({
    ...roomSummary(projectRoom.roomId, events, projectRoom.name),
    role: projectRoom.kind === "manager" ? "manager" : "project",
  }));

const projectStatus = (project: DashboardProject, events: AgentTeamsEvent[]): ConversationStatus => {
  if (project.status === "failed") {
    return "attention";
  }
  return events.length ? "active" : "quiet";
};

const projectFallback = (project: DashboardProject): string => {
  if (project.status === "provisioning") {
    return "正在创建房间…";
  }
  if (project.status === "failed") {
    return `创建失败：${project.error || "请查看详情"}`;
  }
  return "等待新的 Manager 消息";
};

export const projectConversationSummary = (
  project: DashboardProject,
  events: AgentTeamsEvent[],
  controllerData?: JsonObject,
): ConversationSummary => {
  const current = activeEvents(events);
  const rooms = projectRooms(project, current);
  const managerRoomId = project.managerRoomId
    || project.rooms.find((room) => room.kind === "manager")?.roomId
    || "";
  const latest = [...current].sort((left, right) => right.occurredAt.localeCompare(left.occurredAt))[0];
  const managerName = managerNameFor(project, current, controllerData);
  const participants = new Set([
    project.managerUserId,
    ...project.rooms.flatMap((room) => room.inviteUserIds),
    ...current.map((event) => event.actor?.id || ""),
  ].filter(Boolean).map((userId) => userId.toLowerCase()));
  return {
    id: project.id,
    source: "dashboard-project",
    projectId: project.id,
    projectKind: project.kind,
    projectStatus: project.status,
    title: project.name,
    managerName,
    managerUserId: project.managerUserId,
    managerRoomId,
    summary: compactInboxPreview(current, projectFallback(project)),
    status: projectStatus(project, current),
    latestAt: latest?.occurredAt || project.updatedAt,
    eventCount: current.length,
    messageCount: current.filter((event) => event.kind === "message").length,
    roomCount: rooms.length,
    agentCount: participants.size,
    collaborationCount: current.filter((event) => eventEvidenceCategory(event) === "collaboration").length,
    skillCount: current.filter((event) => eventEvidenceCategory(event) === "skill").length,
    toolCount: current.filter((event) => eventEvidenceCategory(event) === "tool").length,
    exceptionCount: current.filter((event) => eventEvidenceCategory(event) === "exception").length,
    rooms,
  };
};

export const projectConversation = (
  project: DashboardProject,
  events: AgentTeamsEvent[],
  controllerData?: JsonObject,
): ConversationDetail & { project: DashboardProject } => {
  const roomIds = new Set(project.rooms.map((room) => room.roomId));
  const observations = activeEvents(events)
    .filter((event) => Boolean(event.roomId) && roomIds.has(event.roomId || ""))
    .sort((left, right) => left.occurredAt.localeCompare(right.occurredAt));
  const rooms = projectRooms(project, observations);
  return {
    project,
    conversation: projectConversationSummary(project, observations, controllerData),
    rooms,
    messages: observations.filter((event) => event.kind === "message"),
    observations,
    evidence: observations.filter(isPriorityEvidence),
    artifacts: observations.filter((event) => event.kind === "artifact"),
    attention: observations.flatMap(attentionFor),
  };
};
