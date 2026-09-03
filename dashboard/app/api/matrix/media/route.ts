import { parseMxcUri } from "../../../../lib/api/contracts";
import { errorResponse, jsonResponse } from "../../../../lib/http";
import { ensureDashboardRuntime } from "../../../../lib/runtime";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const mxc = new URL(request.url).searchParams.get("mxc") || "";
  try {
    parseMxcUri(mxc);
  } catch (error) {
    return jsonResponse({ error: "invalid_media_uri", message: error instanceof Error ? error.message : "invalid mxc URI" }, 400);
  }
  try {
    const runtime = await ensureDashboardRuntime();
    const upstream = await runtime.matrix.downloadMedia(mxc);
    const headers = new Headers();
    const contentType = upstream.headers.get("content-type");
    const contentLength = upstream.headers.get("content-length");
    if (contentType) {
      headers.set("content-type", contentType);
    }
    if (contentLength) {
      headers.set("content-length", contentLength);
    }
    headers.set("cache-control", "private, max-age=60");
    return new Response(upstream.body, { status: upstream.status, headers });
  } catch (error) {
    return errorResponse(error);
  }
}
