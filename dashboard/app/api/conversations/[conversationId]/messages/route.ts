import { projectConversation } from "../../../../../lib/conversations/projection";
import { parseMessageBody } from "../../../../../lib/api/contracts";
import { errorResponse, jsonResponse } from "../../../../../lib/http";
import { ensureDashboardRuntime } from "../../../../../lib/runtime";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ conversationId: string }> },
): Promise<Response> {
  try {
    const { conversationId: rawConversationId } = await context.params;
    const conversationId = decodeURIComponent(rawConversationId);
    let payload: unknown;
    try {
      payload = await request.json();
    } catch {
      return jsonResponse({ error: "invalid_json", message: "request body must be valid JSON" }, 400);
    }
    const { text, threadRootEventId } = parseMessageBody(payload);
    const runtime = await ensureDashboardRuntime();
    const snapshot = await runtime.store.snapshot();
    const conversation = projectConversation(conversationId, snapshot.events, snapshot.controller?.data);
    const taskThreadRoot = conversation.conversation.runId
      ? conversation.observations.find((event) =>
        event.roomId === conversation.conversation.managerRoomId
        && !event.detail?.threadRootEventId
        && event.sourceRef.eventId,
      )?.sourceRef.eventId
        || conversation.observations.find((event) =>
          event.roomId === conversation.conversation.managerRoomId && event.sourceRef.eventId,
        )?.sourceRef.eventId
      : undefined;
    const sent = await runtime.matrix.sendMessage(conversation.conversation.managerRoomId, text, {
      threadRootEventId: threadRootEventId || taskThreadRoot,
    });
    return jsonResponse({ accepted: true, eventId: sent.eventId, txnId: sent.txnId });
  } catch (error) {
    if (error instanceof Error && /was not found/.test(error.message)) {
      return jsonResponse({ error: "conversation_not_found", message: error.message }, 404);
    }
    if (error instanceof Error && /request body|message text|at most/.test(error.message)) {
      return jsonResponse({ error: "invalid_request", message: error.message }, 400);
    }
    return errorResponse(error);
  }
}
