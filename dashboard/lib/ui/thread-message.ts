import type { ThreadMessageLike } from "@assistant-ui/react";
import type { AgentTeamsEvent } from "../types";
import { actorDisplayName } from "./actor";

const assistantRoles = new Set(["manager", "worker", "system", "unknown"]);

export const toThreadMessageLike = (
  event: AgentTeamsEvent,
): ThreadMessageLike | null => {
  if (event.kind !== "message") {
    return null;
  }

  const actorRole = event.actor?.role || "unknown";
  return {
    id: event.id,
    role: actorRole === "human" ? "user" : assistantRoles.has(actorRole) ? "assistant" : "system",
    content: [{ type: "text", text: event.summary }],
    createdAt: new Date(event.occurredAt),
    metadata: {
      custom: {
        actorId: event.actor?.id,
        actorLabel: actorDisplayName(event),
        actorDisplayName: event.actor?.displayName,
        actorRole,
        roomId: event.roomId,
        runId: event.runId,
        sourceEventId: event.sourceRef.eventId,
      },
    },
  };
};
