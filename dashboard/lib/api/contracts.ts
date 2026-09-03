import { projectWorkspace } from "../runs/projection";
import { projectParticipants } from "../projects/participants";
import { projectConversationSummary } from "../projects/projection";
import type { EventStoreSnapshot } from "../events/store";
import type { ProjectCreateInput } from "../projects/provisioning";
import type { WorkspaceSnapshot } from "../types";

export const MAX_MESSAGE_LENGTH = 12_000;

export const buildWorkspaceSnapshot = (snapshot: EventStoreSnapshot): WorkspaceSnapshot => {
  const projection = projectWorkspace(snapshot.events, snapshot.controller?.data);
  const projects = snapshot.projects
    .map((project) => projectConversationSummary(project, snapshot.events, snapshot.controller?.data))
    .sort((left, right) => right.latestAt.localeCompare(left.latestAt));
  return {
    ...projection,
    projects,
    participants: projectParticipants(snapshot.controller?.data, snapshot.events),
    generatedAt: new Date().toISOString(),
    controller: snapshot.controller
      ? {
          state: "live",
          data: snapshot.controller.data,
          receivedAt: snapshot.controller.receivedAt,
        }
      : { state: "unavailable", error: snapshot.sync.lastError },
    sync: {
      state: snapshot.sync.state,
      cursor: snapshot.cursor,
      updatedAt: snapshot.sync.updatedAt,
      lastEventAt: snapshot.sync.lastEventAt,
      lastError: snapshot.sync.lastError,
    },
    capabilities: { liveSync: true, traceQuery: false },
  };
};

const projectRequestObject = (payload: unknown): Record<string, unknown> => {
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
    throw new Error("request body must be an object");
  }
  return payload as Record<string, unknown>;
};

const optionalProjectUserId = (payload: Record<string, unknown>): string | undefined => {
  if (payload.managerUserId === undefined) {
    return undefined;
  }
  if (typeof payload.managerUserId !== "string" || !payload.managerUserId.trim()) {
    throw new Error("managerUserId must be a non-empty string");
  }
  return payload.managerUserId.trim();
};

const projectInviteUserIds = (payload: Record<string, unknown>): string[] | undefined => {
  if (payload.inviteUserIds === undefined) {
    return undefined;
  }
  if (!Array.isArray(payload.inviteUserIds) || payload.inviteUserIds.some((userId) => typeof userId !== "string" || !userId.trim())) {
    throw new Error("inviteUserIds must be an array of non-empty strings");
  }
  const seen = new Set<string>();
  return payload.inviteUserIds.flatMap((userId) => {
    const trimmed = userId.trim();
    const key = trimmed.toLowerCase();
    if (seen.has(key)) {
      return [];
    }
    seen.add(key);
    return [trimmed];
  });
};

export const parseProjectBody = (payload: unknown): ProjectCreateInput => {
  const candidate = projectRequestObject(payload);
  if (candidate.kind === "manager-dm") {
    const managerUserId = optionalProjectUserId(candidate);
    return managerUserId ? { kind: "manager-dm", managerUserId } : { kind: "manager-dm" };
  }
  if (candidate.kind !== "project") {
    throw new Error("project kind must be project or manager-dm");
  }
  if (typeof candidate.name !== "string" || !candidate.name.trim()) {
    throw new Error("project name is required");
  }
  const name = candidate.name.trim();
  if (name.length > 120) {
    throw new Error("project name must be at most 120 characters");
  }
  if (!Array.isArray(candidate.roomNames) || candidate.roomNames.length < 1) {
    throw new Error("at least one room is required");
  }
  if (candidate.roomNames.length > 12) {
    throw new Error("project may contain at most 12 rooms");
  }
  const roomNames = candidate.roomNames.map((roomName) => {
    if (typeof roomName !== "string" || !roomName.trim()) {
      throw new Error("project room names must be non-empty strings");
    }
    const trimmed = roomName.trim();
    if (trimmed.length > 80) {
      throw new Error("project room names must be at most 80 characters");
    }
    return trimmed;
  });
  if (new Set(roomNames.map((roomName) => roomName.toLowerCase())).size !== roomNames.length) {
    throw new Error("project room names must be unique");
  }
  const managerUserId = optionalProjectUserId(candidate);
  const inviteUserIds = projectInviteUserIds(candidate);
  return {
    kind: "project",
    name,
    roomNames,
    ...(inviteUserIds ? { inviteUserIds } : {}),
    ...(managerUserId ? { managerUserId } : {}),
  };
};

export const parseMessageBody = (payload: unknown): { text: string; threadRootEventId?: string } => {
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
    throw new Error("request body must be an object");
  }
  const candidate = payload as Record<string, unknown>;
  const text = typeof candidate.text === "string" ? candidate.text.trim() : "";
  if (!text) {
    throw new Error("message text is required");
  }
  if (text.length > MAX_MESSAGE_LENGTH) {
    throw new Error(`message must be at most ${MAX_MESSAGE_LENGTH} characters`);
  }
  const threadRootEventId = typeof candidate.threadRootEventId === "string"
    ? candidate.threadRootEventId.trim() || undefined
    : undefined;
  return { text, threadRootEventId };
};

export const formatSseFrame = (event: { id: string; type: string; data: unknown }): string =>
  `id: ${event.id}\nevent: ${event.type}\ndata: ${JSON.stringify(event.data)}\n\n`;

export const parseMxcUri = (value: string): { serverName: string; mediaId: string } => {
  const match = /^mxc:\/\/([^/]+)\/(.+)$/.exec(value.trim());
  if (!match) {
    throw new Error("a valid mxc:// URI is required");
  }
  return { serverName: match[1], mediaId: match[2] };
};
