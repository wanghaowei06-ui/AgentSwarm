import { formatSseFrame } from "../../../lib/api/contracts";
import { errorResponse, jsonResponse } from "../../../lib/http";
import { ensureDashboardRuntime } from "../../../lib/runtime";

export const dynamic = "force-dynamic";

const encoder = new TextEncoder();

export async function GET(request: Request): Promise<Response> {
  try {
    const runtime = await ensureDashboardRuntime();
    const lastEventId = request.headers.get("last-event-id") || undefined;
    const replay = lastEventId ? await runtime.store.since(lastEventId) : [];
    const snapshot = await runtime.store.snapshot();
    const subscription = runtime.hub.subscribe();
    let heartbeat: ReturnType<typeof setInterval> | undefined;
    let closed = false;

    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        const close = () => {
          if (closed) {
            return;
          }
          closed = true;
          if (heartbeat) {
            clearInterval(heartbeat);
          }
          runtime.hub.remove(subscription);
          try {
            controller.close();
          } catch {
            // The client may have cancelled the stream already.
          }
        };

        for (const event of replay) {
          controller.enqueue(encoder.encode(formatSseFrame({
            id: event.id,
            type: "observation",
            data: event,
          })));
        }
        controller.enqueue(encoder.encode(formatSseFrame({
          id: `sync:initial:${snapshot.sync.updatedAt || Date.now()}`,
          type: "sync.status",
          data: snapshot.sync,
        })));
        heartbeat = setInterval(() => {
          if (!closed) {
            controller.enqueue(encoder.encode(": heartbeat\n\n"));
          }
        }, 15_000);
        request.signal.addEventListener("abort", close, { once: true });

        const pump = async () => {
          while (!closed) {
            const event = await subscription.next();
            if (!event) {
              close();
              return;
            }
            controller.enqueue(encoder.encode(formatSseFrame(event)));
          }
        };
        void pump();
      },
      cancel() {
        closed = true;
        if (heartbeat) {
          clearInterval(heartbeat);
        }
        runtime.hub.remove(subscription);
      },
    });
    return new Response(stream, {
      headers: {
        "cache-control": "no-cache, no-transform",
        connection: "keep-alive",
        "content-type": "text/event-stream; charset=utf-8",
        "x-accel-buffering": "no",
      },
    });
  } catch (error) {
    return error instanceof Error && /required|configured/i.test(error.message)
      ? errorResponse(error)
      : jsonResponse({ error: "event_stream_unavailable", message: "live event stream is unavailable" }, 503);
  }
}
