import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { afterEach, describe, expect, it } from "vitest";

import { MatrixClient } from "../lib/matrix/client";

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

describe("MatrixClient", () => {
  it("logs in once and uses the returned token for joined rooms and sync", async () => {
    const requests: { method: string; url: string; body: string; authorization?: string }[] = [];
    const baseUrl = await startServer((request, response) => {
      let body = "";
      request.on("data", (chunk) => {
        body += String(chunk);
      });
      request.on("end", () => {
        requests.push({
          method: request.method ?? "",
          url: request.url ?? "",
          body,
          authorization: request.headers.authorization,
        });
        response.setHeader("content-type", "application/json");
        if (request.url === "/_matrix/client/v3/login") {
          response.end(JSON.stringify({ access_token: "matrix-token", user_id: "@admin:matrix.local" }));
          return;
        }
        if (request.url?.startsWith("/_matrix/client/v3/joined_rooms")) {
          response.end(JSON.stringify({ joined_rooms: ["!room:matrix.local"] }));
          return;
        }
        if (request.url?.startsWith("/_matrix/client/v3/sync")) {
          response.end(JSON.stringify({ next_batch: "s-2", rooms: { join: {} } }));
          return;
        }
        response.statusCode = 404;
        response.end(JSON.stringify({ error: "not found" }));
      });
    });

    const client = new MatrixClient({
      homeserverUrl: baseUrl,
      username: "admin",
      password: "admin-password",
    });
    await expect(client.joinedRooms()).resolves.toEqual(["!room:matrix.local"]);
    await expect(client.sync({ since: "s-1", timeoutMs: 0 })).resolves.toMatchObject({ next_batch: "s-2" });

    expect(requests[0]).toMatchObject({
      method: "POST",
      url: "/_matrix/client/v3/login",
    });
    expect(JSON.parse(requests[0].body)).toMatchObject({
      type: "m.login.password",
      identifier: { type: "m.id.user", user: "admin" },
      password: "admin-password",
    });
    expect(requests[1].authorization).toBe("Bearer matrix-token");
    expect(requests[2].authorization).toBe("Bearer matrix-token");
  });

  it("sends text to the explicitly encoded Matrix room and returns the real event id", async () => {
    const baseUrl = await startServer((request, response) => {
      let body = "";
      request.on("data", (chunk) => {
        body += String(chunk);
      });
      request.on("end", () => {
        expect(request.method).toBe("PUT");
        expect(request.url).toMatch(/^\/_matrix\/client\/v3\/rooms\/%21room%3Amatrix\.local\/send\/m\.room\.message\/at-/);
        expect(request.headers.authorization).toBe("Bearer fixed-token");
        expect(JSON.parse(body)).toMatchObject({ msgtype: "m.text", body: "Continue" });
        response.setHeader("content-type", "application/json");
        response.end(JSON.stringify({ event_id: "$sent-event" }));
      });
    });

    const result = await new MatrixClient({
      homeserverUrl: baseUrl,
      accessToken: "fixed-token",
    }).sendMessage("!room:matrix.local", "Continue");

    expect(result.eventId).toBe("$sent-event");
    expect(result.txnId).toMatch(/^at-/);
  });

  it("reads real member display names from a Matrix room state", async () => {
    const baseUrl = await startServer((request, response) => {
      response.setHeader("content-type", "application/json");
      if (request.url === "/_matrix/client/v3/rooms/%21room%3Amatrix.local/state") {
        response.end(JSON.stringify([
          {
            type: "m.room.member",
            state_key: "@manager:matrix.local",
            content: { membership: "join", displayname: "总控协调者" },
          },
        ]));
        return;
      }
      response.statusCode = 404;
      response.end(JSON.stringify({ error: "not found" }));
    });

    const client = new MatrixClient({
      homeserverUrl: baseUrl,
      accessToken: "fixed-token",
    });

    await expect(client.roomState("!room:matrix.local")).resolves.toMatchObject([
      {
        type: "m.room.member",
        state_key: "@manager:matrix.local",
        content: { displayname: "总控协调者" },
      },
    ]);
  });

  it("creates a real private Matrix room with the requested invite", async () => {
    const requests: { method: string; url: string; body: string }[] = [];
    const baseUrl = await startServer((request, response) => {
      let body = "";
      request.on("data", (chunk) => {
        body += String(chunk);
      });
      request.on("end", () => {
        requests.push({
          method: request.method ?? "",
          url: request.url ?? "",
          body,
        });
        response.setHeader("content-type", "application/json");
        response.end(JSON.stringify({ room_id: "!created:matrix.local" }));
      });
    });

    const result = await new MatrixClient({
      homeserverUrl: baseUrl,
      accessToken: "fixed-token",
    }).createRoom({
      name: "主讨论",
      invite: ["@manager:matrix.local"],
    });

    expect(result.roomId).toBe("!created:matrix.local");
    expect(requests[0]).toMatchObject({
      method: "POST",
      url: "/_matrix/client/v3/createRoom",
    });
    expect(JSON.parse(requests[0].body)).toMatchObject({
      name: "主讨论",
      invite: ["@manager:matrix.local"],
      preset: "trusted_private_chat",
      is_direct: false,
    });
  });

  it("reads and caches the real Matrix user id", async () => {
    let requestCount = 0;
    const baseUrl = await startServer((request, response) => {
      expect(request.url).toBe("/_matrix/client/v3/account/whoami");
      requestCount += 1;
      response.setHeader("content-type", "application/json");
      response.end(JSON.stringify({ user_id: "@admin:matrix.local" }));
    });

    const client = new MatrixClient({
      homeserverUrl: baseUrl,
      accessToken: "fixed-token",
    });

    await expect(client.whoAmI()).resolves.toBe("@admin:matrix.local");
    await expect(client.whoAmI()).resolves.toBe("@admin:matrix.local");
    expect(requestCount).toBe(1);
  });

  it("parses joined and invited members from Matrix room state", async () => {
    const baseUrl = await startServer((request, response) => {
      expect(request.url).toBe("/_matrix/client/v3/rooms/%21room%3Amatrix.local/state");
      response.setHeader("content-type", "application/json");
      response.end(JSON.stringify([
        {
          type: "m.room.member",
          state_key: "@manager:matrix.local",
          content: { membership: "join", displayname: "总控协调者" },
        },
        {
          type: "m.room.member",
          state_key: "@worker:matrix.local",
          content: { membership: "invite" },
        },
      ]));
    });

    const members = await new MatrixClient({
      homeserverUrl: baseUrl,
      accessToken: "fixed-token",
    }).roomMembers("!room:matrix.local");

    expect(members).toEqual([
      {
        userId: "@manager:matrix.local",
        membership: "join",
        displayName: "总控协调者",
      },
      {
        userId: "@worker:matrix.local",
        membership: "invite",
      },
    ]);
  });
});
