import type { AgentTeamsEvent, ActorRole, EvidenceCategory, JsonObject } from "../types";
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
  if (localpart.includes("leader") || localpart.includes("team-lead")) {
    return "leader";
  }
  if (localpart.includes("worker")) {
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

type MarkdownInvocation = {
  name: string;
  payload?: JsonObject;
};

type TextClassification = {
  evidenceCategory: Extract<EvidenceCategory, "collaboration" | "exception" | "approval">;
  status?: string;
  approvalState?: "pending" | "approved" | "rejected";
  approvalActor?: "human" | "agent";
};

const markdownInvocationHeader = /^\s*🔧\s*\*\*(?<name>[^*]+)\*\*/u;
const markdownCodeBlock = /```(?:json)?\s*([\s\S]*?)```/i;
const collaborationToolNames = new Set([
  "teamharness__message",
  "teamharness__communication",
  "teamharness__projectflow",
  "teamharness__roomflow",
  "teamharness__taskflow",
]);

const jsonPayload = (text: string): JsonObject | undefined => {
  const block = markdownCodeBlock.exec(text)?.[1]?.trim();
  if (!block) {
    return undefined;
  }
  try {
    const parsed: unknown = JSON.parse(block);
    return isObject(parsed) ? parsed : undefined;
  } catch {
    return undefined;
  }
};

const markdownInvocation = (text: string): MarkdownInvocation | undefined => {
  const header = markdownInvocationHeader.exec(text);
  const name = header?.groups?.name?.trim();
  return name ? { name, payload: jsonPayload(text) } : undefined;
};

const statusFromPayload = (payload?: JsonObject): string => {
  const status = stringValue(payload?.status) || stringValue(payload?.state);
  if (status) {
    return status;
  }
  if (payload && (payload.error !== undefined || payload.errors !== undefined)) {
    return "failed";
  }
  return "observed";
};

const firstString = (value: JsonObject | undefined, keys: string[]): string => {
  for (const key of keys) {
    const result = stringValue(value?.[key]);
    if (result) {
      return result;
    }
  }
  return "";
};

const textStatus = (text: string): string | undefined => {
  if (/(?:waiting|pending|awaiting|等待)/i.test(text)) {
    return "waiting";
  }
  if (/(?:blocked|not[_ -]?available|unavailable|timeout|timed out|阻断|不可用|超时)/i.test(text)) {
    return "blocked";
  }
  if (/(?:failed|failure|error|exception|失败|错误|异常)/i.test(text)) {
    return "failed";
  }
  return undefined;
};

const hasExplicitApprovalDecision = (text: string, actor?: AgentTeamsEvent["actor"]): boolean =>
  (actor?.role === "human" && /(?:我\s*(?:仅)?授权|我\s*(?:批准|同意)|一次性\s*Human\s*审批|\/approve\b)/i.test(text))
  || /(?:human|人工)\s*(?:approval\s*)?(?:was\s*)?(?:approved|granted|批准|同意|denied|rejected|拒绝)/i.test(text)
  || /(?:approval|审批)\s*(?:was\s*)?(?:approved|granted|批准|同意|denied|rejected|拒绝)/i.test(text)
  || /approved by human/i.test(text);

const classifyApproval = (text: string, actor?: AgentTeamsEvent["actor"]): TextClassification | undefined => {
  const normalized = text.replace(/\s+/g, " ").trim();
  const rejected = /(?:human|人工)\s*(?:approval\s*)?(?:was\s*)?(?:denied|rejected|拒绝)/i.test(normalized)
    || /(?:approval|审批)\s*(?:was\s*)?(?:denied|rejected|拒绝)/i.test(normalized)
    || (actor?.role === "human" && /\/deny\b/i.test(normalized));
  if (hasExplicitApprovalDecision(normalized, actor)) {
    return {
      evidenceCategory: "approval",
      approvalState: rejected ? "rejected" : "approved",
      approvalActor: actor?.role === "human" ? "human" : "agent",
    };
  }

  const pending = /\b(?:awaiting|waiting for|requires?|needs?)\s+(?:a\s+)?(?:human|manual)\s+approval\b/i.test(normalized)
    || /\b(?:human|manual)\s+approval\s+(?:is\s+)?(?:pending|required|needed)\b/i.test(normalized)
    || /\bpending\s+(?:a\s+)?approval(?:\s+from\s+(?:a\s+)?human)?\b/i.test(normalized)
    || /(?:需要|等待|暂停(?:等待)?|待)\s*(?:人工|人类)?\s*(?:审批|批准|决定)/.test(normalized);
  const conditional = /\b(?:if|when)\b/i.test(normalized)
    || /(?:若|如果|假如|一旦)/.test(normalized);
  if (pending && !conditional) {
    return {
      evidenceCategory: "approval",
      approvalState: "pending",
      approvalActor: "agent",
      status: "waiting",
    };
  }
  return undefined;
};

const classifyException = (text: string): TextClassification | undefined => {
  const explicit = /⚠️|❌|billing error|command failed|provider returned .*error|not[_ -]?available|unavailable|timed out|timeout|exception|\bblocked\b|\bfailed\b|失败|错误|异常|阻断|不可用|超时/i.test(text);
  if (!explicit) {
    return undefined;
  }
  return {
    evidenceCategory: "exception",
    status: textStatus(text) || "failed",
  };
};

const classifyCollaboration = (text: string, actor?: AgentTeamsEvent["actor"]): TextClassification | undefined => {
  const explicit = /teamharness__(?:message|communication|projectflow|roomflow|taskflow)|delegate_task|ack_task|submit_task|handoff|task assigned|assigned to|delegat(?:e|ed|ion)|phase[- ]?report|leader.{0,36}worker|worker.{0,36}leader|已委派|委派完成|已派发|已验收|验收报告|交付物|跨房间|协作/i.test(text);
  const agentMention = (actor?.role === "leader" || actor?.role === "worker") && /@[\w.-]+(?::[^\s]+)?/.test(text);
  if (!explicit && !agentMention) {
    return undefined;
  }
  return { evidenceCategory: "collaboration" };
};

export const classifyMatrixMessage = (
  text: string,
  actor?: AgentTeamsEvent["actor"],
): TextClassification | undefined =>
  classifyApproval(text, actor) || classifyException(text) || classifyCollaboration(text, actor);

const classificationDetail = (classification: TextClassification): JsonObject => ({
  evidenceCategory: classification.evidenceCategory,
  ...(classification.status ? { status: classification.status } : {}),
  ...(classification.approvalState ? { approvalState: classification.approvalState } : {}),
  ...(classification.approvalActor ? { approvalActor: classification.approvalActor } : {}),
});

const invocationDetails = (
  content: JsonObject,
  invocation: MarkdownInvocation,
  kind: "tool" | "skill",
): { detail: JsonObject; summary: string; runId?: string } => {
  const payload = invocation.payload;
  const status = statusFromPayload(payload);
  const rawName = invocation.name.trim();
  const skillName = kind === "skill"
    ? firstString(payload, ["skill", "skillName", "name"]) || "skill"
    : rawName;
  const detail: JsonObject = {
    ...relationDetails(content),
    name: skillName,
    ...(kind === "skill" ? { skillName } : {}),
    status,
    invocationFormat: "matrix-markdown",
    ...(payload ? { arguments: sanitizeValue(payload) } : {}),
  };
  const callId = firstString(payload, ["callId", "call_id"]);
  const runId = firstString(payload, ["runId", "run_id", "projectId", "project_id"]);
  const projectId = firstString(payload, ["projectId", "project_id"]);
  const taskId = firstString(payload, ["taskId", "task_id"]);
  if (callId) {
    detail.callId = callId;
  }
  if (runId) {
    detail.runId = runId;
  }
  if (projectId) {
    detail.projectId = projectId;
  }
  if (taskId) {
    detail.taskId = taskId;
  }
  if (kind === "tool" && collaborationToolNames.has(rawName.toLowerCase())) {
    detail.evidenceCategory = "collaboration";
  }
  return {
    detail,
    summary: `${skillName} · ${status}`,
    ...(runId ? { runId } : {}),
  };
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

const normalizeMarkdownInvocation = (
  event: MatrixEvent,
  content: JsonObject,
  invocation: MarkdownInvocation,
  displayNames?: ReadonlyMap<string, string>,
): AgentTeamsEvent => {
  const kind = invocation.name.trim().toLowerCase() === "skill" ? "skill" : "tool";
  const details = invocationDetails(content, invocation, kind);
  const normalized = baseEvent(event, kind, details.summary, displayNames);
  normalized.detail = details.detail;
  if (details.runId) {
    normalized.runId = details.runId;
  }
  return normalized;
};

const normalizeMessage = (
  event: MatrixEvent,
  content: JsonObject,
  displayNames?: ReadonlyMap<string, string>,
): AgentTeamsEvent => {
  const normalized = baseEvent(event, "message", textFromContent(content) || "Message", displayNames);
  normalized.detail = {
    ...relationDetails(event.content),
    msgtype: stringValue(content.msgtype) || "m.text",
    formatted: typeof content.formatted_body === "string",
  };
  const classification = classifyMatrixMessage(normalized.summary, normalized.actor);
  if (classification) {
    normalized.detail = {
      ...normalized.detail,
      ...classificationDetail(classification),
    };
  }
  return normalized;
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
    ...(collaborationToolNames.has(name.toLowerCase()) ? { evidenceCategory: "collaboration" } : {}),
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

  const invocation = markdownInvocation(textFromContent(content));
  if (invocation) {
    return normalizeMarkdownInvocation(event, content, invocation, displayNames);
  }

  const msgtype = stringValue(content.msgtype);
  if (["m.image", "m.file", "m.audio", "m.video"].includes(msgtype)) {
    return normalizeArtifact(event, content, displayNames);
  }

  if (event.type === "m.room.message") {
    return normalizeMessage(event, content, displayNames);
  }

  const normalized = baseEvent(event, "system", `${event.type} event`, displayNames);
  normalized.detail = relationDetails(event.content);
  return normalized;
};

export const sanitizeObservationValue = sanitizeValue;

export const reclassifyStoredEvent = (event: AgentTeamsEvent): AgentTeamsEvent => {
  if (event.source !== "matrix" || event.kind !== "message") {
    return event;
  }

  const actor = event.actor
    ? { ...event.actor, role: actorRole(event.actor.id) }
    : event.actor;
  const invocation = markdownInvocation(event.summary);
  if (invocation) {
    const kind = invocation.name.trim().toLowerCase() === "skill" ? "skill" : "tool";
    const details = invocationDetails(event.detail || {}, invocation, kind);
    return {
      ...event,
      kind,
      actor,
      summary: details.summary,
      detail: { ...(event.detail || {}), ...details.detail },
      ...(details.runId ? { runId: details.runId } : {}),
    };
  }

  const classification = classifyMatrixMessage(event.summary, actor);
  const detail = { ...(event.detail || {}) };
  for (const key of ["evidenceCategory", "status", "approvalState", "approvalActor"]) {
    delete detail[key];
  }
  const detailChanged = JSON.stringify(detail) !== JSON.stringify(event.detail || {});
  if (!classification && actor?.role === event.actor?.role && !detailChanged) {
    return event;
  }
  return {
    ...event,
    actor,
    detail: classification ? { ...detail, ...classificationDetail(classification) } : detail,
  };
};
