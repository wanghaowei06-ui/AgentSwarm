import { projectWorkspace } from "../runs/projection";
import type { EventStoreSnapshot } from "../events/store";
import type { WorkspaceSnapshot } from "../types";

export const MAX_MESSAGE_LENGTH = 12_000;

export const buildWorkspaceSnapshot = (snapshot: EventStoreSnapshot): WorkspaceSnapshot => {
  const projection = projectWorkspace(snapshot.events, snapshot.controller?.data);
  return {
    ...projection,
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
