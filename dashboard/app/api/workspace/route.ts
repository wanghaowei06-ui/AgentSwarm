import { buildWorkspaceSnapshot } from "../../../lib/api/contracts";
import { errorResponse, jsonResponse } from "../../../lib/http";
import { ensureDashboardRuntime } from "../../../lib/runtime";

export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  try {
    const runtime = await ensureDashboardRuntime();
    return jsonResponse(buildWorkspaceSnapshot(await runtime.store.snapshot()));
  } catch (error) {
    return errorResponse(error);
  }
}
