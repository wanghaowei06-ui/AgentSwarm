import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { afterEach, describe, expect, it } from "vitest";

import { ControllerClient, ControllerUpstreamError } from "../lib/controller/client";

const servers: ReturnType<typeof createServer>[] = [];

const startServer = async (
  handler: (request: IncomingMessage, response: ServerResponse) => void,
): Promise<string> => {
  const server = createServer(handler);
  servers.push(server);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("test server did not expose a TCP address");
  }
  return `http://127.0.0.1:${address.port}`;
};

afterEach(async () => {
  await Promise.all(
    servers.splice(0).map(
      (server) =>
        new Promise<void>((resolve, reject) => {
          server.close((error) => (error ? reject(error) : resolve()));
        }),
    ),
  );
});

describe("ControllerClient", () => {
  it("reads a real controller resource with the server-side bearer token", async () => {
    const baseUrl = await startServer((request, response) => {
      expect(request.method).toBe("GET");
      expect(request.url).toBe("/api/v1/workers");
      expect(request.headers.authorization).toBe("Bearer controller-token");
      response.setHeader("content-type", "application/json");
      response.end(JSON.stringify({
        workers: [{ name: "worker-a", phase: "Ready", roomID: "!room:matrix.local" }],
        total: 1,
      }));
    });

    const result = await new ControllerClient({
      baseUrl,
      authToken: "controller-token",
    }).getWorkers();

    expect(result.data).toEqual({
      workers: [{ name: "worker-a", phase: "Ready", roomID: "!room:matrix.local" }],
      total: 1,
    });
    expect(result.endpoint).toBe("/api/v1/workers");
    expect(result.source).toBe("controller");
  });

  it("surfaces controller authorization failures without exposing the token", async () => {
    const baseUrl = await startServer((_request, response) => {
      response.statusCode = 401;
      response.setHeader("content-type", "application/json");
      response.end(JSON.stringify({ error: "unauthorized" }));
    });

    await expect(
      new ControllerClient({
        baseUrl,
        authToken: "controller-token",
      }).getStatus(),
    ).rejects.toBeInstanceOf(ControllerUpstreamError);

    try {
      await new ControllerClient({ baseUrl, authToken: "controller-token" }).getStatus();
    } catch (error) {
      expect(String(error)).not.toContain("controller-token");
      expect((error as ControllerUpstreamError).status).toBe(401);
    }
  });
});
