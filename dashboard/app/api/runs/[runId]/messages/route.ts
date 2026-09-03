import { parseMessageBody } from "../../../../../lib/api/contracts";
import { errorResponse, jsonResponse } from "../../../../../lib/http";
import { ensureDashboardRuntime } from "../../../../../lib/runtime";
import { projectRun } from "../../../../../lib/runs/projection";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ runId: string }> },
): Promise<Response> {
  try {
    const { runId: rawRunId } = await context.params;
    let payload: unknown;
    try {
      payload = await request.json();
    } catch {
      return jsonResponse({ error: "invalid_json", message: "request body must be valid JSON" }, 400);
    }
    const { text, threadRootEventId } = parseMessageBody(payload);
    const runtime = await ensureDashboardRuntime();
    const snapshot = await runtime.store.snapshot();
    const run = projectRun(decodeURIComponent(rawRunId), snapshot.events);
    if (!run.run.roomId) {
      return jsonResponse({ error: "run_room_missing", message: "run has no explicit Matrix room" }, 409);
    }
    const sent = await runtime.matrix.sendMessage(run.run.roomId, text, { threadRootEventId });
    return jsonResponse({ accepted: true, eventId: sent.eventId, txnId: sent.txnId });
  } catch (error) {
    if (error instanceof Error && /was not found/.test(error.message)) {
      return jsonResponse({ error: "run_not_found", message: error.message }, 404);
    }
    if (error instanceof Error && /request body|message text|at most/.test(error.message)) {
      return jsonResponse({ error: "invalid_request", message: error.message }, 400);
    }
    return errorResponse(error);
  }
}
