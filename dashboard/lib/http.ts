import { ControllerUpstreamError } from "./controller/client";
import { DashboardConfigError } from "./config";
import { MatrixUpstreamError } from "./matrix/client";

export const jsonResponse = (data: unknown, status = 200): Response =>
  Response.json(data, {
    status,
    headers: { "cache-control": "no-store" },
  });

export const errorResponse = (error: unknown): Response => {
  if (error instanceof DashboardConfigError) {
    return jsonResponse({ error: "dashboard_not_configured", message: error.message }, 503);
  }
  if (error instanceof ControllerUpstreamError || error instanceof MatrixUpstreamError) {
    const status = error.status === 401 || error.status === 403
      ? error.status
      : error.status >= 500
        ? 502
        : error.status;
    return jsonResponse({
      error: `${error.source}_upstream_error`,
      message: error.message,
      source: error.source,
      retryable: error.retryable,
    }, status);
  }
  if (error instanceof Error && /required|invalid|not found/i.test(error.message)) {
    return jsonResponse({ error: "invalid_request", message: error.message }, 400);
  }
  return jsonResponse({ error: "dashboard_unavailable", message: "Dashboard upstream is unavailable" }, 503);
};
