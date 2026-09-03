import { errorResponse, jsonResponse } from "../../../../lib/http";
import { ensureDashboardRuntime } from "../../../../lib/runtime";
import { projectRun } from "../../../../lib/runs/projection";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ runId: string }> },
): Promise<Response> {
  try {
    const { runId } = await context.params;
    const runtime = await ensureDashboardRuntime();
    const snapshot = await runtime.store.snapshot();
    const run = projectRun(decodeURIComponent(runId), snapshot.events);
    return jsonResponse({ ...run, sync: snapshot.sync });
  } catch (error) {
    if (error instanceof Error && /was not found/.test(error.message)) {
      return jsonResponse({ error: "run_not_found", message: error.message }, 404);
    }
    return errorResponse(error);
  }
}
