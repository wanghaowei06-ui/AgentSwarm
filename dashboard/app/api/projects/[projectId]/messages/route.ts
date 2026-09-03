import { parseMessageBody } from "../../../../../lib/api/contracts";
import { errorResponse, jsonResponse } from "../../../../../lib/http";
import { ensureDashboardRuntime } from "../../../../../lib/runtime";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ projectId: string }> },
): Promise<Response> {
  try {
    const { projectId: rawProjectId } = await context.params;
    const projectId = decodeURIComponent(rawProjectId);
    let payload: unknown;
    try {
      payload = await request.json();
    } catch {
      return jsonResponse({ error: "invalid_json", message: "request body must be valid JSON" }, 400);
    }
    const { text, threadRootEventId } = parseMessageBody(payload);
    const runtime = await ensureDashboardRuntime();
    const snapshot = await runtime.store.snapshot();
    const project = snapshot.projects.find((candidate) => candidate.id === projectId);
    if (!project) {
      return jsonResponse({ error: "project_not_found", message: `project ${projectId} was not found` }, 404);
    }
    if (project.status !== "active") {
      return jsonResponse({
        error: "project_not_active",
        message: `project ${projectId} is ${project.status}`,
      }, 409);
    }
    if (!project.managerRoomId) {
      return jsonResponse({
        error: "project_manager_room_missing",
        message: "project has no Manager room",
      }, 409);
    }
    const sent = await runtime.matrix.sendMessage(project.managerRoomId, text, { threadRootEventId });
    return jsonResponse({ accepted: true, eventId: sent.eventId, txnId: sent.txnId });
  } catch (error) {
    if (error instanceof Error && /request body|message text|at most/.test(error.message)) {
      return jsonResponse({ error: "invalid_request", message: error.message }, 400);
    }
    return errorResponse(error);
  }
}
