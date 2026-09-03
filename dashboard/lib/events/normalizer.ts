import type { AgentTeamsEvent, ActorRole, JsonObject } from "../types";
import type { MatrixEvent } from "../matrix/types";

const MAX_TEXT_LENGTH = 4_000;
const MAX_NESTED_ITEMS = 24;
const SENSITIVE_KEY = /(token|password|secret|api.?key|credential|authorization|cookie|private.?key)/i;

const isObject = (value: unknown): value is JsonObject =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const stringValue = (value: unknown): string =>
  typeof value === "string" ? value.trim() : "";

const boundedText = (value: string, limit = MAX_TEXT_LENGTH): string => {
  if (value.length <= limit) {
    return value;
  }
  return `${value.slice(0, limit - 1).trimEnd()}…`;
};

const sanitizeValue = (value: unknown, depth = 0): unknown => {
  if (depth > 3) {
    return "[nested value omitted]";
  }

  if (typeof value === "string") {
    return boundedText(value, 1_200);
  }

  if (typeof value === "number" || typeof value === "boolean" || value === null) {
    return value;
  }

  if (Array.isArray(value)) {
    return value.slice(0, MAX_NESTED_ITEMS).map((item) => sanitizeValue(item, depth + 1));
  }

  if (isObject(value)) {
    const result: JsonObject = {};
    Object.entries(value)
      .slice(0, MAX_NESTED_ITEMS)
      .forEach(([key, nested]) => {
        result[key] = SENSITIVE_KEY.test(key)
          ? "[redacted]"
          : sanitizeValue(nested, depth + 1);
      });
    return result;
  }

  return String(value);
};

const effectiveContent = (event: MatrixEvent): JsonObject => {
  const relation = event.content["m.relates_to"];
  const newContent = isObject(event.content["m.new_content"])
    ? event.content["m.new_content"]
    : undefined;

  if (isObject(relation) && relation.rel_type === "m.replace" && newContent) {
    return { ...event.content, ...newContent };
  }
  return event.content;
};

const actorRole = (sender: string): ActorRole => {
  const localpart = sender.replace(/^@/, "").split(":", 1)[0].toLowerCase();
  if (localpart === "manager" || localpart.includes("manager")) {
    return "manager";
  }
  if (localpart.includes("worker") || localpart.includes("team-lead")) {
    return "worker";
  }
  if (localpart === "system" || localpart.includes("controller")) {
    return "system";
  }
  if (localpart) {
    return "human";
  }
  return "unknown";
};

const actorLabel = (sender: string): string => {
  const localpart = sender.replace(/^@/, "").split(":", 1)[0];
  return localpart || sender || "Unknown actor";
};

export const matrixMemberKey = (roomId: string, userId: string): string => `${roomId}\u0000${userId}`;

const findStructuredObject = (content: JsonObject, keys: string[]): JsonObject | undefined => {
  for (const key of keys) {
    const value = content[key];
    if (isObject(value)) {
      return value;
    }
  }
  return undefined;
};

const textFromContent = (content: JsonObject): string => {
  const body = stringValue(content.body);
  if (body) {
    return boundedText(body);
  }

  const formattedBody = stringValue(content.formatted_body);
  return boundedText(formattedBody.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim());
};

const relationDetails = (content: JsonObject): JsonObject => {
  const relation = content["m.relates_to"];
  if (!isObject(relation)) {
    return {};
  }
  const eventId = stringValue(relation.event_id);
  const inReplyTo = isObject(relation["m.in_reply_to"])
    ? stringValue(relation["m.in_reply_to"].event_id)
    : "";
  const detail: JsonObject = {};
  if (relation.rel_type === "m.thread" && eventId) {
    detail.threadRootEventId = eventId;
  }
  if (inReplyTo) {
    detail.relatedEventId = inReplyTo;
  } else if (relation.rel_type !== "m.replace" && eventId) {
    detail.relatedEventId = eventId;
  }
  if (relation.rel_type === "m.replace" && eventId) {
    detail.editedEventId = eventId;
  }
  return detail;
};

const baseEvent = (
  event: MatrixEvent,
  kind: AgentTeamsEvent["kind"],
  summary: string,
  displayNames?: ReadonlyMap<string, string>,
): AgentTeamsEvent => {
  const displayName = displayNames?.get(matrixMemberKey(event.room_id, event.sender))?.trim();
  return {
    id: `matrix:${event.event_id}`,
    source: "matrix",
    kind,
    occurredAt: new Date(event.origin_server_ts).toISOString(),
    roomId: event.room_id,
    actor: {
      id: event.sender,
      label: actorLabel(event.sender),
      ...(displayName ? { displayName } : {}),
      role: actorRole(event.sender),
    },
    summary: boundedText(summary || event.type),
    sourceRef: { eventId: event.event_id },
  };
};

const normalizeWorkflow = (
  event: MatrixEvent,
  content: JsonObject,
  workflow: JsonObject,
  displayNames?: ReadonlyMap<string, string>,
): AgentTeamsEvent => {
  const runId = stringValue(workflow.runId);
  const summary = stringValue(workflow.summary) || stringValue(workflow.title) || textFromContent(content);
  const detail: JsonObject = relationDetails(event.content);
  for (const key of [
    "type",
    "status",
    "title",
    "summary",
    "ownerRole",
    "ownerAgentId",
    "coordinator",
    "sharedPath",
    "subagents",
    "steps",
    "eventId",
  ]) {
    if (workflow[key] !== undefined) {
      detail[key] = sanitizeValue(workflow[key]);
    }
  }

  const normalized = baseEvent(event, "workflow", summary || "WorkerFlow update", displayNames);
  normalized.detail = detail;
  if (runId) {
    normalized.runId = runId;
  }
  return normalized;
};

const normalizeTool = (
  event: MatrixEvent,
  tool: JsonObject,
  displayNames?: ReadonlyMap<string, string>,
): AgentTeamsEvent => {
  const name = stringValue(tool.name) || stringValue(tool.tool) || "tool";
  const status = stringValue(tool.status) || "observed";
  const detail: JsonObject = {
    ...relationDetails(event.content),
    name,
    status,
  };
  for (const key of ["callId", "runId", "phase", "args", "arguments", "result", "output", "error"]) {
    if (tool[key] !== undefined) {
      detail[key] = sanitizeValue(tool[key]);
    }
  }

  const normalized = baseEvent(event, "tool", `${name} · ${status}`, displayNames);
  normalized.detail = detail;
  const runId = stringValue(tool.runId);
  if (runId) {
    normalized.runId = runId;
  }
  return normalized;
};

const normalizeSkill = (
  event: MatrixEvent,
  skill: JsonObject,
  displayNames?: ReadonlyMap<string, string>,
): AgentTeamsEvent => {
  const name = stringValue(skill.name) || stringValue(skill.skillName) || stringValue(skill.skill) || "skill";
  const status = stringValue(skill.status) || "observed";
  const detail: JsonObject = {
    ...relationDetails(event.content),
    name,
    status,
  };
  for (const key of ["skill", "skillName", "callId", "runId", "phase", "args", "arguments", "result", "output", "error"]) {
    if (skill[key] !== undefined) {
      detail[key] = sanitizeValue(skill[key]);
    }
  }

  const normalized = baseEvent(event, "skill", `${name} · ${status}`, displayNames);
  normalized.detail = detail;
  const runId = stringValue(skill.runId);
  if (runId) {
    normalized.runId = runId;
  }
  return normalized;
};

const normalizeArtifact = (
  event: MatrixEvent,
  content: JsonObject,
  displayNames?: ReadonlyMap<string, string>,
): AgentTeamsEvent => {
  const msgtype = stringValue(content.msgtype) || "m.file";
  const filename = stringValue(content.body) || "Attachment";
  const info = isObject(content.info) ? content.info : {};
  const normalized = baseEvent(event, "artifact", filename, displayNames);
  normalized.detail = {
    ...relationDetails(event.content),
    msgtype,
    filename,
    mxc: stringValue(content.url),
    mimetype: stringValue(info.mimetype),
    size: typeof info.size === "number" ? info.size : undefined,
    relatesTo: sanitizeValue(content["m.relates_to"]),
  };
  return normalized;
};

export const normalizeMatrixEvent = (
  event: MatrixEvent,
  displayNames?: ReadonlyMap<string, string>,
): AgentTeamsEvent => {
  const content = effectiveContent(event);
  const workflow = findStructuredObject(content, ["agentteams.workflow"]);
  if (workflow) {
    return normalizeWorkflow(event, content, workflow, displayNames);
  }

  const tool = findStructuredObject(content, [
    "agentteams.tool",
    "agentteams.tool_call",
    "agentteams.toolCall",
  ]);
  if (tool) {
    return normalizeTool(event, tool, displayNames);
  }

  const skill = findStructuredObject(content, [
    "agentteams.skill",
    "agentteams.skill_call",
    "agentteams.skillCall",
  ]);
  if (skill) {
    return normalizeSkill(event, skill, displayNames);
  }

  const msgtype = stringValue(content.msgtype);
  if (["m.image", "m.file", "m.audio", "m.video"].includes(msgtype)) {
    return normalizeArtifact(event, content, displayNames);
  }

  if (event.type === "m.room.message") {
    const normalized = baseEvent(event, "message", textFromContent(content) || "Message", displayNames);
    normalized.detail = {
      ...relationDetails(event.content),
      msgtype: msgtype || "m.text",
      formatted: typeof content.formatted_body === "string",
    };
    return normalized;
  }

  const normalized = baseEvent(event, "system", `${event.type} event`, displayNames);
  normalized.detail = relationDetails(event.content);
  return normalized;
};

export const sanitizeObservationValue = sanitizeValue;
