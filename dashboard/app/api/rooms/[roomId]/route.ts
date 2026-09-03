import { errorResponse, jsonResponse } from "../../../../lib/http";
import { ensureDashboardRuntime } from "../../../../lib/runtime";
import { projectRoom } from "../../../../lib/runs/projection";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ roomId: string }> },
): Promise<Response> {
  try {
    const { roomId: rawRoomId } = await context.params;
    const roomId = decodeURIComponent(rawRoomId);
    const runtime = await ensureDashboardRuntime();
    const snapshot = await runtime.store.snapshot();
    const room = projectRoom(roomId, snapshot.events);
    return jsonResponse({ ...room, sync: snapshot.sync });
  } catch (error) {
    if (error instanceof Error && /was not found/.test(error.message)) {
      return jsonResponse({ error: "room_not_found", message: error.message }, 404);
    }
    return errorResponse(error);
  }
}
