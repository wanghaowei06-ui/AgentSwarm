import type {
  AgentTeamsEvent,
  AttentionItem,
  JsonObject,
  RoomSummary,
  RunDetail,
  RunStatus,
  RunSummary,
  RoomDetail,
  WorkspaceProjection,
} from "../types";
import { projectConversations } from "../conversations/projection";

const isObject = (value: unknown): value is JsonObject =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const stringValue = (value: unknown): string =>
  typeof value === "string" ? value.trim() : "";

const normalizedStatus = (value: unknown): RunStatus => {
  const status = stringValue(value).toLowerCase().replace(/[- ]/g, "_");
  if (["done", "completed", "complete", "finished", "success", "succeeded"].includes(status)) {
    return "done";
  }
  if (["failed", "failure", "error", "cancelled", "canceled"].includes(status)) {
    return "failed";
  }
  if (["waiting", "blocked", "paused"].includes(status)) {
    return "waiting";
  }
  if (["running", "in_progress", "inprogress", "active"].includes(status)) {
    return "running";
  }
  if (["queued", "pending", "created"].includes(status)) {
    return "queued";
  }
  return "unknown";
};

const detailRelationId = (event: AgentTeamsEvent): string => {
  const detail = event.detail || {};
  return stringValue(detail.threadRootEventId)
    || stringValue(detail.relatedEventId)
    || stringValue(detail.editedEventId);
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

const workflowRootId = (event: AgentTeamsEvent): string => {
  const detail = event.detail || {};
  return stringValue(detail.relatedEventId)
    || stringValue(detail.eventId)
    || event.sourceRef.eventId || "";
};

const correlate = (events: AgentTeamsEvent[]): Map<string, string> => {
  const runByEventId = new Map<string, string>();
  for (const event of events) {
    if (event.runId) {
      const eventId = event.sourceRef.eventId || event.id;
      runByEventId.set(eventId, event.runId);
      if (event.kind === "workflow") {
        const rootId = workflowRootId(event);
        if (rootId) {
          runByEventId.set(rootId, event.runId);
        }
      }
    }
  }

  const result = new Map<string, string>();
  for (const event of events) {
    if (event.runId) {
      result.set(event.id, event.runId);
      continue;
    }
    const relationId = detailRelationId(event);
    const relatedRun = relationId ? runByEventId.get(relationId) : undefined;
    if (relatedRun) {
      result.set(event.id, relatedRun);
    }
  }
  return result;
};

const eventRunId = (event: AgentTeamsEvent, correlated: Map<string, string>): string | undefined =>
  event.runId || correlated.get(event.id);

const workflowDetails = (event: AgentTeamsEvent): JsonObject => event.detail || {};

const workflowSteps = (event: AgentTeamsEvent): JsonObject[] => {
  const steps = workflowDetails(event).steps;
  return Array.isArray(steps) ? steps.filter(isObject) : [];
};

const attentionFor = (event: AgentTeamsEvent, runId?: string): AttentionItem[] => {
  const detail = event.detail || {};
  const status = normalizedStatus(detail.status);
  const items: AttentionItem[] = [];
  if (event.kind === "workflow" && status === "failed") {
    items.push({
      id: `attention:${event.id}`,
      severity: "error",
      summary: event.summary,
      runId,
      sourceEventId: event.sourceRef.eventId,
    });
  }
  if (event.kind === "workflow" && status === "waiting") {
    items.push({
      id: `attention:${event.id}`,
      severity: "warning",
      summary: event.summary,
      runId,
      sourceEventId: event.sourceRef.eventId,
    });
  }
  if ((event.kind === "tool" || event.kind === "skill") && ["failed", "error"].includes(stringValue(detail.status).toLowerCase())) {
    items.push({
      id: `attention:${event.id}`,
      severity: "error",
      summary: `${event.summary} · requires review`,
      runId,
      sourceEventId: event.sourceRef.eventId,
    });
  }
  if (event.kind === "system" && /degraded|unavailable|error|failed/i.test(event.summary)) {
    items.push({
      id: `attention:${event.id}`,
      severity: "warning",
      summary: event.summary,
      runId,
      sourceEventId: event.sourceRef.eventId,
    });
  }
  return items;
};

const latestByRun = (runEvents: AgentTeamsEvent[]): AgentTeamsEvent | undefined =>
  [...runEvents].filter((event) => event.kind === "workflow").sort((left, right) => right.occurredAt.localeCompare(left.occurredAt))[0];

const makeRunSummary = (runId: string, runEvents: AgentTeamsEvent[]): RunSummary => {
  const latestWorkflow = latestByRun(runEvents);
  const latest = [...runEvents].sort((left, right) => right.occurredAt.localeCompare(left.occurredAt))[0];
  const detail = latestWorkflow ? workflowDetails(latestWorkflow) : {};
  const steps = latestWorkflow ? workflowSteps(latestWorkflow) : [];
  const completedStepCount = steps.filter((step) => normalizedStatus(step.status) === "done").length;
  return {
    id: runId,
    title: stringValue(detail.title) || latestWorkflow?.summary || `Run ${runId}`,
    status: normalizedStatus(detail.status),
    roomId: latestWorkflow?.roomId || latest?.roomId || "",
    summary: stringValue(detail.summary) || latestWorkflow?.summary || latest?.summary || "",
    updatedAt: latest?.occurredAt || "",
    stepCount: steps.length,
    completedStepCount,
    attentionCount: runEvents.flatMap((event) => attentionFor(event, runId)).length,
  };
};

export const projectWorkspace = (events: AgentTeamsEvent[], controllerData?: JsonObject): WorkspaceProjection => {
  const correlated = correlate(events);
  const currentEvents = activeEvents(events);
  const runGroups = new Map<string, AgentTeamsEvent[]>();
  for (const event of currentEvents) {
    const runId = eventRunId(event, correlated);
    if (!runId) {
      continue;
    }
    const group = runGroups.get(runId) || [];
    group.push(event);
    runGroups.set(runId, group);
  }

  const runs = [...runGroups.entries()]
    .filter(([runId, group]) => group.some((event) => event.kind === "workflow" && eventRunId(event, correlated) === runId))
    .map(([runId, group]) => makeRunSummary(runId, group))
    .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));

  const roomGroups = new Map<string, AgentTeamsEvent[]>();
  for (const event of events) {
    if (!event.roomId) {
      continue;
    }
    const group = roomGroups.get(event.roomId) || [];
    group.push(event);
    roomGroups.set(event.roomId, group);
  }
  const rooms: RoomSummary[] = [...roomGroups.entries()]
    .map(([roomId, group]) => {
      const latest = [...group].sort((left, right) => right.occurredAt.localeCompare(left.occurredAt))[0];
      const relatedRun = runs.find((run) => run.roomId === roomId);
      return {
        roomId,
        label: relatedRun?.title || roomId,
        latestAt: latest?.occurredAt || "",
        eventCount: group.length,
        messageCount: group.filter((event) => event.kind === "message").length,
      };
    })
    .sort((left, right) => right.latestAt.localeCompare(left.latestAt));

  const attention = currentEvents.flatMap((event) => attentionFor(event, eventRunId(event, correlated)));
  const conversationProjection = projectConversations(events, controllerData, rooms);
  return {
    rooms,
    runs,
    conversations: conversationProjection.conversations,
    unassignedRooms: conversationProjection.unassignedRooms,
    attention,
  };
};

export const projectRun = (runId: string, events: AgentTeamsEvent[]): RunDetail => {
  const correlated = correlate(events);
  const scoped = events.filter((event) => eventRunId(event, correlated) === runId);
  const current = activeEvents(scoped);
  const workflowEvents = current.filter((event) => event.kind === "workflow" && eventRunId(event, correlated) === runId);
  if (!workflowEvents.length) {
    throw new Error(`run ${runId} was not found in the event store`);
  }
  const run = makeRunSummary(runId, current);
  const observations = [...current].sort((left, right) => left.occurredAt.localeCompare(right.occurredAt));
  const workflow = latestByRun(current)?.detail;
  const traceLinks = [...new Set(
    scoped.flatMap((event) => {
      const detail = event.detail || {};
      return [stringValue(detail.traceId), ...(Array.isArray(detail.traceIds) ? detail.traceIds.filter((value): value is string => typeof value === "string") : [])].filter(Boolean);
    }),
  )];
  return {
    run,
    messages: observations.filter((event) => event.kind === "message"),
    observations,
    workflow,
    artifacts: observations.filter((event) => event.kind === "artifact"),
    attention: observations.flatMap((event) => attentionFor(event, runId)),
    traceLinks,
  };
};

export const projectRoom = (roomId: string, events: AgentTeamsEvent[]): RoomDetail => {
  const normalizedRoomId = roomId.trim();
  const scoped = events.filter((event) => event.roomId === normalizedRoomId);
  if (!scoped.length) {
    throw new Error(`room ${normalizedRoomId} was not found in the event store`);
  }
  const room = projectWorkspace(events).rooms.find((candidate) => candidate.roomId === normalizedRoomId);
  if (!room) {
    throw new Error(`room ${normalizedRoomId} was not found in the event store`);
  }
  const observations = activeEvents(scoped).sort((left, right) => left.occurredAt.localeCompare(right.occurredAt));
  return {
    room,
    messages: observations.filter((event) => event.kind === "message"),
    observations,
    artifacts: observations.filter((event) => event.kind === "artifact"),
    attention: observations.flatMap((event) => attentionFor(event)),
  };
};
