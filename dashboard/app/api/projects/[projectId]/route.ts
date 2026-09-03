import { projectConversation } from "../../../../lib/projects/projection";
import { errorResponse, jsonResponse } from "../../../../lib/http";
import { ensureDashboardRuntime } from "../../../../lib/runtime";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ projectId: string }> },
): Promise<Response> {
  try {
    const { projectId: rawProjectId } = await context.params;
    const projectId = decodeURIComponent(rawProjectId);
    const runtime = await ensureDashboardRuntime();
    const snapshot = await runtime.store.snapshot();
    const project = snapshot.projects.find((candidate) => candidate.id === projectId);
    if (!project) {
      return jsonResponse({ error: "project_not_found", message: `project ${projectId} was not found` }, 404);
    }
    return jsonResponse({
      ...projectConversation(project, snapshot.events, snapshot.controller?.data),
      sync: snapshot.sync,
    });
  } catch (error) {
    return errorResponse(error);
  }
}
