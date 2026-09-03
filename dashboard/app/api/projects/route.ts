import { parseProjectBody } from "../../../lib/api/contracts";
import { ProjectProvisioningError, DashboardProjectProvisioner } from "../../../lib/projects/provisioning";
import { errorResponse, jsonResponse } from "../../../lib/http";
import { ensureDashboardRuntime } from "../../../lib/runtime";
import type { JsonObject } from "../../../lib/types";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return jsonResponse({ error: "invalid_json", message: "request body must be valid JSON" }, 400);
  }

  let input;
  try {
    input = parseProjectBody(payload);
  } catch (error) {
    return jsonResponse({
      error: "invalid_request",
      message: error instanceof Error ? error.message : "invalid project request",
    }, 400);
  }

  try {
    const runtime = await ensureDashboardRuntime();
    const snapshot = await runtime.store.snapshot();
    const [managers, workers, teams] = await Promise.all([
      runtime.controller.getManagers<JsonObject>(),
      runtime.controller.getWorkers<JsonObject>(),
      runtime.controller.getTeams<JsonObject>(),
    ]);
    const controllerData: JsonObject = {
      ...snapshot.controller?.data,
      [managers.endpoint]: managers.data,
      [workers.endpoint]: workers.data,
      [teams.endpoint]: teams.data,
    };
    const result = await new DashboardProjectProvisioner({
      matrix: runtime.matrix,
      store: runtime.store,
      controllerData,
      events: snapshot.events,
    }).create(input);
    runtime.hub.publish({
      id: `project:${result.project.id}:${result.project.updatedAt}`,
      type: "project.updated",
      data: {
        projectId: result.project.id,
        status: result.project.status,
      },
    });
    if (result.project.status === "failed") {
      return jsonResponse({
        ...result,
        error: "project_provisioning_failed",
        message: result.project.error || "project provisioning failed",
      }, 502);
    }
    return jsonResponse(result, result.reused ? 200 : 201);
  } catch (error) {
    if (error instanceof ProjectProvisioningError) {
      return jsonResponse({ error: error.code, message: error.message }, error.status);
    }
    return errorResponse(error);
  }
}
