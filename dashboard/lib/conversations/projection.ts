import type {
  AgentTeamsEvent,
  AttentionItem,
  ConversationDetail,
  ConversationRoom,
  ConversationRoomRole,
  ConversationStatus,
  ConversationSummary,
  JsonObject,
  RoomSummary,
} from "../types";
import { approvalState, eventEvidenceCategory, isPriorityEvidence, isStructuralRoomEvent } from "../events/evidence";
import { compactInboxPreview } from "../inbox/preview";
import { correlateTasks, taskRunIdFor } from "./task-correlation";

export type ConversationProjection = {
  conversations: ConversationSummary[];
  unassignedRooms: RoomSummary[];
};

type ControllerRecord = JsonObject;

const isObject = (value: unknown): value is JsonObject =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const stringValue = (value: unknown): string =>
  typeof value === "string" ? value.trim() : "";

const actorDisplayNameFor = (
  events: AgentTeamsEvent[],
  userId: string,
  fallback: string,
  roomId?: string,
): string => {
  const normalizedUserId = userId.trim().toLowerCase();
  const normalizedFallback = fallback.trim().toLowerCase();
  return events.find((event) =>
    (normalizedUserId
      ? event.actor?.id.toLowerCase() === normalizedUserId
      : event.actor?.label.toLowerCase() === normalizedFallback)
      && (!roomId || event.roomId === roomId)
      && event.actor?.displayName,
  )?.actor?.displayName || fallback;
};

const recordsAt = (controllerData: JsonObject | undefined, endpoint: string, key: string): ControllerRecord[] => {
  const response = controllerData?.[endpoint];
  if (!isObject(response) || !Array.isArray(response[key])) {
    return [];
  }
  return response[key].filter(isObject);
};

const roomIdOf = (record: ControllerRecord): string =>
  stringValue(record.roomID) || stringValue(record.roomId);

const roomSummary = (roomId: string, events: AgentTeamsEvent[], label = roomId): RoomSummary => {
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

const roomSummariesFromEvents = (events: AgentTeamsEvent[]): RoomSummary[] => {
  const roomIds = [...new Set(events.map((event) => event.roomId).filter((roomId): roomId is string => Boolean(roomId)))];
  return roomIds
    .map((roomId) => roomSummary(roomId, events))
    .sort((left, right) => right.latestAt.localeCompare(left.latestAt));
};

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

const attentionFor = (event: AgentTeamsEvent, runId = event.runId): AttentionItem[] => {
  const status = stringValue(event.detail?.status).toLowerCase();
  const category = eventEvidenceCategory(event);
  if (category === "exception") {
    return [{
      id: `attention:${event.id}`,
      severity: status === "waiting" || status === "blocked" ? "warning" : "error",
      summary: event.summary,
      runId,
      sourceEventId: event.sourceRef.eventId,
    }];
  }
  if (category === "approval" && ["pending", "rejected"].includes(approvalState(event))) {
    return [{
      id: `attention:${event.id}`,
      severity: approvalState(event) === "pending" ? "warning" : "error",
      summary: approvalState(event) === "pending" ? `待人工审批：${event.summary}` : `人工审批已拒绝：${event.summary}`,
      runId,
      sourceEventId: event.sourceRef.eventId,
    }];
  }
  return [];
};

const addRoom = (
  rooms: Map<string, ConversationRoom>,
  events: AgentTeamsEvent[],
  roomId: string,
  label: string,
  role: ConversationRoomRole,
  agentName?: string,
  teamName?: string,
  summaryEvents: AgentTeamsEvent[] = events,
): void => {
  if (!roomId) {
    return;
  }
  const existing = rooms.get(roomId);
  const summary = roomSummary(roomId, summaryEvents, label);
  rooms.set(roomId, {
    ...(existing || summary),
    ...summary,
    role: existing?.role || role,
    agentName: existing?.agentName || agentName,
    teamName: existing?.teamName || teamName,
  });
};

const managerPresentationName = (name: string): string =>
  name.toLowerCase() === "default" ? "Manager" : name;

const knownRoomsForManager = (
  manager: ControllerRecord,
  managers: ControllerRecord[],
  teams: ControllerRecord[],
  workers: ControllerRecord[],
  events: AgentTeamsEvent[],
): ConversationRoom[] => {
  const rooms = new Map<string, ConversationRoom>();
  const managerResourceName = stringValue(manager.name) || "Manager";
  const managerFallbackName = managerPresentationName(managerResourceName);
  const managerUserId = stringValue(manager.matrixUserID) || stringValue(manager.matrixUserId);
  const managerRoomId = roomIdOf(manager);
  const managerDisplayName = actorDisplayNameFor(events, managerUserId, managerFallbackName, managerRoomId);
  addRoom(
    rooms,
    events,
    managerRoomId,
    managerDisplayName === "Manager" ? managerDisplayName : `Manager · ${managerDisplayName}`,
    "manager",
    managerDisplayName,
  );

  // The current controller contract has no managerName on Team records. Only
  // aggregate Team/Worker rooms automatically when there is one Manager.
  if (managers.length !== 1) {
    return [...rooms.values()];
  }

  for (const team of teams) {
    const teamName = stringValue(team.name) || stringValue(team.teamName) || "Team";
    addRoom(rooms, events, stringValue(team.teamRoomID) || stringValue(team.teamRoomId), `Team · ${teamName}`, "team", undefined, teamName);
    const leaderName = stringValue(team.leaderName) || teamName;
    const leaderUserId = stringValue(team.leaderMatrixUserID)
      || stringValue(team.leaderMatrixUserId)
      || stringValue(team.leaderUserID)
      || stringValue(team.leaderUserId);
    const leaderRoomId = stringValue(team.leaderDMRoomID) || stringValue(team.leaderDmRoomId);
    const leaderDisplayName = actorDisplayNameFor(events, leaderUserId, leaderName, leaderRoomId);
    addRoom(
      rooms,
      events,
      leaderRoomId,
      `Leader · ${leaderDisplayName}`,
      "leader",
      leaderDisplayName,
      teamName,
    );
  }
  for (const worker of workers) {
    const workerName = stringValue(worker.name) || "Worker";
    const teamName = stringValue(worker.team) || undefined;
    const workerUserId = stringValue(worker.matrixUserID) || stringValue(worker.matrixUserId);
    const workerRoomId = roomIdOf(worker);
    const workerDisplayName = actorDisplayNameFor(events, workerUserId, workerName, workerRoomId);
    addRoom(rooms, events, workerRoomId, `Worker · ${workerDisplayName}`, "worker", workerDisplayName, teamName);
  }
  return [...rooms.values()];
};

const roomsForEvents = (rooms: ConversationRoom[], events: AgentTeamsEvent[]): ConversationRoom[] => {
  const roomIds = new Set(events.map((event) => event.roomId).filter((roomId): roomId is string => Boolean(roomId)));
  return rooms
    .filter((room) => room.role === "manager" || roomIds.has(room.roomId))
    .map((room) => ({
      ...room,
      ...roomSummary(room.roomId, events, room.label),
    }));
};

type ConversationScope = {
  runId?: string;
  taskIds?: string[];
};

const conversationSummary = (
  manager: ControllerRecord,
  rooms: ConversationRoom[],
  events: AgentTeamsEvent[],
  scope: ConversationScope = {},
): ConversationSummary => {
  const managerName = stringValue(manager.name) || "default";
  const managerDisplayName = rooms.find((room) => room.role === "manager")?.agentName || managerPresentationName(managerName);
  const managerRoomId = roomIdOf(manager);
  const latest = [...events].sort((left, right) => right.occurredAt.localeCompare(left.occurredAt))[0];
  const collaborationCount = events.filter((event) => eventEvidenceCategory(event) === "collaboration").length;
  const skillCount = events.filter((event) => eventEvidenceCategory(event) === "skill").length;
  const toolCount = events.filter((event) => eventEvidenceCategory(event) === "tool").length;
  const exceptionCount = events.filter((event) => eventEvidenceCategory(event) === "exception").length;
  const approvalCount = events.filter((event) => eventEvidenceCategory(event) === "approval").length;
  const pendingApprovalCount = events.filter((event) => eventEvidenceCategory(event) === "approval" && approvalState(event) === "pending").length;
  const status: ConversationStatus = exceptionCount > 0 || pendingApprovalCount > 0
    ? "attention"
    : events.length > 0
      ? "active"
      : "quiet";
  const agents = new Set(
    [managerDisplayName, ...rooms.map((room) => room.agentName || "")].filter(Boolean),
  );
  return {
    id: scope.runId ? `manager:${managerName}:run:${scope.runId}` : `manager:${managerName}`,
    source: "controller",
    runId: scope.runId,
    taskIds: scope.taskIds?.length ? scope.taskIds : undefined,
    title: scope.runId ? `任务 · ${scope.runId}` : "Manager 对话",
    managerName: managerDisplayName,
    managerUserId: stringValue(manager.matrixUserID) || stringValue(manager.matrixUserId) || undefined,
    managerRoomId,
    summary: compactInboxPreview(
      events,
      latest ? "最新执行进度已移到右侧证据栏" : "等待新的 Manager 会话事件",
    ),
    status,
    latestAt: latest?.occurredAt || "",
    eventCount: events.length,
    messageCount: events.filter((event) => event.kind === "message").length,
    roomCount: rooms.length,
    agentCount: agents.size,
    collaborationCount,
    skillCount,
    toolCount,
    exceptionCount,
    approvalCount,
    rooms,
  };
};

export const projectConversations = (
  events: AgentTeamsEvent[],
  controllerData?: JsonObject,
  existingRooms?: RoomSummary[],
): ConversationProjection => {
  const active = activeEvents(events).filter((event) => !isStructuralRoomEvent(event));
  const managers = recordsAt(controllerData, "/api/v1/managers", "managers");
  const teams = recordsAt(controllerData, "/api/v1/teams", "teams");
  const workers = recordsAt(controllerData, "/api/v1/workers", "workers");
  const sourceRooms = existingRooms || roomSummariesFromEvents(events);
  const managerScopes = managers.map((manager) => {
    const rooms = knownRoomsForManager(manager, managers, teams, workers, events);
    const roomIds = new Set(rooms.map((room) => room.roomId));
    const scoped = active.filter((event) => event.roomId && roomIds.has(event.roomId));
    const correlationEvents = events.filter((event) => event.roomId && roomIds.has(event.roomId));
    return { manager, rooms, roomIds, scoped, correlationEvents };
  });
  const conversations = managerScopes.flatMap(({ manager, rooms, scoped, correlationEvents }) => {
    const correlation = correlateTasks(correlationEvents);
    const taskGroups = new Map<string, AgentTeamsEvent[]>();
    const generalEvents: AgentTeamsEvent[] = [];
    for (const event of scoped) {
      const runId = taskRunIdFor(event, correlation);
      if (!runId) {
        generalEvents.push(event);
        continue;
      }
      const group = taskGroups.get(runId) || [];
      group.push(event);
      taskGroups.set(runId, group);
    }
    return [
      conversationSummary(manager, rooms, generalEvents),
      ...[...taskGroups.entries()].map(([runId, taskEvents]) => conversationSummary(
        manager,
        roomsForEvents(rooms, taskEvents),
        taskEvents,
        { runId, taskIds: correlation.taskIdsByRun.get(runId) },
      )),
    ];
  }).sort((left, right) => {
    if (Boolean(left.runId) !== Boolean(right.runId)) {
      return left.runId ? -1 : 1;
    }
    return right.latestAt.localeCompare(left.latestAt);
  });
  const assignedRoomIds = new Set(managerScopes.flatMap(({ roomIds }) => [...roomIds]));
  return {
    conversations,
    unassignedRooms: sourceRooms.filter((room) => !assignedRoomIds.has(room.roomId)),
  };
};

export const projectConversation = (
  conversationId: string,
  events: AgentTeamsEvent[],
  controllerData?: JsonObject,
  existingRooms?: RoomSummary[],
): ConversationDetail => {
  const projection = projectConversations(events, controllerData, existingRooms);
  const conversation = projection.conversations.find((item) => item.id === conversationId);
  if (!conversation) {
    throw new Error(`conversation ${conversationId} was not found in the event store`);
  }
  const managers = recordsAt(controllerData, "/api/v1/managers", "managers");
  const teams = recordsAt(controllerData, "/api/v1/teams", "teams");
  const workers = recordsAt(controllerData, "/api/v1/workers", "workers");
  const taskMarker = ":run:";
  const taskMarkerIndex = conversationId.indexOf(taskMarker);
  const managerConversationId = taskMarkerIndex === -1
    ? conversationId
    : conversationId.slice(0, taskMarkerIndex);
  const manager = managers.find((item) => `manager:${stringValue(item.name) || "default"}` === managerConversationId);
  const rooms = manager ? knownRoomsForManager(manager, managers, teams, workers, events) : [];
  const roomIds = new Set(rooms.map((room) => room.roomId));
  const scopedEvents = activeEvents(events)
    .filter((event) => !isStructuralRoomEvent(event))
    .filter((event) => event.roomId && roomIds.has(event.roomId));
  const correlation = correlateTasks(events.filter((event) => event.roomId && roomIds.has(event.roomId)));
  const runId = conversation.runId
    || (taskMarkerIndex === -1 ? undefined : conversationId.slice(taskMarkerIndex + taskMarker.length));
  const observations = scopedEvents
    .filter((event) => (runId ? taskRunIdFor(event, correlation) === runId : !taskRunIdFor(event, correlation)))
    .sort((left, right) => left.occurredAt.localeCompare(right.occurredAt));
  const detailRooms = runId ? roomsForEvents(rooms, observations) : rooms;
  return {
    conversation,
    rooms: detailRooms,
    messages: observations.filter((event) => event.kind === "message"),
    observations,
    evidence: observations.filter(isPriorityEvidence),
    artifacts: observations.filter((event) => event.kind === "artifact"),
    attention: observations.flatMap((event) => attentionFor(event, taskRunIdFor(event, correlation))),
  };
};

export { eventEvidenceCategory } from "../events/evidence";
