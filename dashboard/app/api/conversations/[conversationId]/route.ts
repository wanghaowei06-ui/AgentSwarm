import { projectConversation } from "../../../../lib/conversations/projection";
import { errorResponse, jsonResponse } from "../../../../lib/http";
import { ensureDashboardRuntime } from "../../../../lib/runtime";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ conversationId: string }> },
): Promise<Response> {
  try {
    const { conversationId: rawConversationId } = await context.params;
    const conversationId = decodeURIComponent(rawConversationId);
    const runtime = await ensureDashboardRuntime();
    const snapshot = await runtime.store.snapshot();
    const conversation = projectConversation(conversationId, snapshot.events, snapshot.controller?.data);
    return jsonResponse({ ...conversation, sync: snapshot.sync });
  } catch (error) {
    if (error instanceof Error && /was not found/.test(error.message)) {
      return jsonResponse({ error: "conversation_not_found", message: error.message }, 404);
    }
    return errorResponse(error);
  }
}
