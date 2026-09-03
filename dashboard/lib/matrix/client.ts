import { randomUUID } from "node:crypto";

import type { JsonObject } from "../types";
import type { MatrixEvent, MatrixRoomMember, MatrixStateEvent } from "./types";

export type MatrixSyncResponse = JsonObject & {
  next_batch: string;
  rooms?: JsonObject;
};

export type MatrixHistoryResponse = JsonObject & {
  chunk?: MatrixEvent[];
  start?: string;
  end?: string;
};

export class MatrixUpstreamError extends Error {
  readonly source = "matrix" as const;
  readonly status: number;
  readonly path: string;
  readonly retryable: boolean;

  constructor(message: string, options: { status: number; path: string; retryable?: boolean }) {
    super(message);
    this.name = "MatrixUpstreamError";
    this.status = options.status;
    this.path = options.path;
    this.retryable = options.retryable ?? options.status >= 500;
  }
}

type FetchLike = typeof fetch;

export type MatrixClientOptions = {
  homeserverUrl: string;
  accessToken?: string;
  username?: string;
  password?: string;
  fetchImpl?: FetchLike;
  timeoutMs?: number;
};

type MatrixSendOptions = {
  threadRootEventId?: string;
  txnId?: string;
};

export type MatrixCreateRoomOptions = {
  name: string;
  invite: string[];
  preset?: string;
  isDirect?: boolean;
};

const trimTrailingSlash = (value: string): string => value.replace(/\/+$/, "");

const boundedErrorBody = (value: string): string => value.replace(/\s+/g, " ").trim().slice(0, 240);

const encodePathSegment = (value: string): string =>
  encodeURIComponent(value).replace(/[!'()*]/g, (character) =>
    `%${character.charCodeAt(0).toString(16).toUpperCase()}`,
  );

const jsonObject = (value: unknown): JsonObject => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new MatrixUpstreamError("Matrix returned an invalid JSON object", {
      status: 502,
      path: "unknown",
      retryable: true,
    });
  }
  return value as JsonObject;
};

export class MatrixClient {
  private readonly homeserverUrl: string;
  private readonly fixedAccessToken?: string;
  private readonly username?: string;
  private readonly password?: string;
  private readonly fetchImpl: FetchLike;
  private readonly timeoutMs: number;
  private accessToken?: string;
  private loginPromise?: Promise<string>;
  private currentUserId?: string;
  private whoAmIPromise?: Promise<string>;

  constructor(options: MatrixClientOptions) {
    if (!options.homeserverUrl.trim()) {
      throw new Error("Matrix homeserver URL is required");
    }
    this.homeserverUrl = trimTrailingSlash(options.homeserverUrl.trim());
    this.fixedAccessToken = options.accessToken?.trim() || undefined;
    this.username = options.username?.trim() || undefined;
    this.password = options.password;
    this.fetchImpl = options.fetchImpl ?? fetch;
    this.timeoutMs = options.timeoutMs ?? 10_000;
    this.accessToken = this.fixedAccessToken;
  }

  async joinedRooms(): Promise<string[]> {
    const data = await this.requestJson("/_matrix/client/v3/joined_rooms");
    return Array.isArray(data.joined_rooms)
      ? data.joined_rooms.filter((room): room is string => typeof room === "string")
      : [];
  }

  async whoAmI(): Promise<string> {
    if (this.currentUserId) {
      return this.currentUserId;
    }
    if (this.whoAmIPromise) {
      return this.whoAmIPromise;
    }
    const path = "/_matrix/client/v3/account/whoami";
    this.whoAmIPromise = this.requestJson(path).then((data) => {
      const userId = typeof data.user_id === "string" ? data.user_id.trim() : "";
      if (!userId) {
        throw new MatrixUpstreamError("Matrix whoami response has no user_id", {
          status: 502,
          path,
          retryable: false,
        });
      }
      this.currentUserId = userId;
      return userId;
    });
    try {
      return await this.whoAmIPromise;
    } finally {
      this.whoAmIPromise = undefined;
    }
  }

  async roomState(roomId: string): Promise<MatrixStateEvent[]> {
    const room = roomId.trim();
    if (!room) {
      throw new Error("Matrix room id is required");
    }
    const path = `/_matrix/client/v3/rooms/${encodePathSegment(room)}/state`;
    const response = await this.request(path);
    let data: unknown;
    try {
      data = await response.json();
    } catch {
      throw new MatrixUpstreamError(`Matrix returned invalid JSON for ${path}`, {
        status: 502,
        path,
        retryable: true,
      });
    }
    if (!Array.isArray(data)) {
      throw new MatrixUpstreamError(`Matrix returned invalid room state for ${path}`, {
        status: 502,
        path,
        retryable: true,
      });
    }
    return data.filter((event): event is MatrixStateEvent =>
      typeof event === "object"
      && event !== null
      && !Array.isArray(event)
      && typeof (event as { type?: unknown }).type === "string"
      && typeof (event as { content?: unknown }).content === "object"
      && (event as { content?: unknown }).content !== null
      && !Array.isArray((event as { content?: unknown }).content),
    ).map((event) => ({
      type: event.type,
      ...(typeof event.state_key === "string" ? { state_key: event.state_key } : {}),
      content: event.content,
    }));
  }

  async roomMembers(roomId: string): Promise<MatrixRoomMember[]> {
    const state = await this.roomState(roomId);
    return state.flatMap((event) => {
      if (event.type !== "m.room.member" || !event.state_key?.trim()) {
        return [];
      }
      const membership = typeof event.content.membership === "string"
        ? event.content.membership.trim()
        : "";
      if (!membership) {
        return [];
      }
      const displayName = typeof event.content.displayname === "string"
        ? event.content.displayname.trim()
        : "";
      return [{
        userId: event.state_key.trim(),
        membership,
        ...(displayName ? { displayName } : {}),
      }];
    });
  }

  async sync(options: { since?: string; timeoutMs?: number; filter?: string } = {}): Promise<MatrixSyncResponse> {
    const params = new URLSearchParams();
    if (options.since) {
      params.set("since", options.since);
    }
    params.set("timeout", String(options.timeoutMs ?? 25_000));
    if (options.filter) {
      params.set("filter", options.filter);
    }
    const path = `/_matrix/client/v3/sync?${params.toString()}`;
    const data = await this.requestJson(path, {
      timeoutMs: Math.max(this.timeoutMs, (options.timeoutMs ?? 25_000) + 1_000),
    });
    if (typeof data.next_batch !== "string" || !data.next_batch) {
      throw new MatrixUpstreamError("Matrix sync response has no next_batch", {
        status: 502,
        path,
        retryable: true,
      });
    }
    return data as MatrixSyncResponse;
  }

  async history(
    roomId: string,
    options: { limit?: number; from?: string; to?: string } = {},
  ): Promise<MatrixHistoryResponse> {
    const room = roomId.trim();
    if (!room) {
      throw new Error("Matrix room id is required");
    }
    const params = new URLSearchParams({
      dir: "b",
      limit: String(options.limit ?? 50),
    });
    if (options.from) {
      params.set("from", options.from);
    }
    if (options.to) {
      params.set("to", options.to);
    }
    const path = `/_matrix/client/v3/rooms/${encodePathSegment(room)}/messages?${params.toString()}`;
    return (await this.requestJson(path)) as MatrixHistoryResponse;
  }

  async sendMessage(roomId: string, text: string, options: MatrixSendOptions = {}): Promise<{ eventId: string; txnId: string }> {
    const room = roomId.trim();
    const bodyText = text.trim();
    if (!room) {
      throw new Error("Matrix room id is required");
    }
    if (!bodyText) {
      throw new Error("message text is required");
    }
    const txnId = options.txnId?.trim() || `at-${Date.now().toString(36)}-${randomUUID().slice(0, 12)}`;
    const path = `/_matrix/client/v3/rooms/${encodePathSegment(room)}/send/m.room.message/${encodePathSegment(txnId)}`;
    const content: JsonObject = { msgtype: "m.text", body: bodyText };
    if (options.threadRootEventId?.trim()) {
      content["m.relates_to"] = {
        rel_type: "m.thread",
        event_id: options.threadRootEventId.trim(),
        is_falling_back: false,
      };
    }
    const data = await this.requestJson(path, {
      method: "PUT",
      body: JSON.stringify(content),
    });
    if (typeof data.event_id !== "string" || !data.event_id) {
      throw new MatrixUpstreamError("Matrix send response has no event_id", {
        status: 502,
        path,
        retryable: true,
      });
    }
    return { eventId: data.event_id, txnId };
  }

  async createRoom(options: MatrixCreateRoomOptions): Promise<{ roomId: string }> {
    const name = options.name.trim();
    if (!name) {
      throw new Error("Matrix room name is required");
    }
    const path = "/_matrix/client/v3/createRoom";
    const data = await this.requestJson(path, {
      method: "POST",
      body: JSON.stringify({
        name,
        invite: options.invite,
        preset: options.preset?.trim() || "trusted_private_chat",
        is_direct: options.isDirect === true,
      }),
    });
    const roomId = typeof data.room_id === "string" ? data.room_id.trim() : "";
    if (!roomId) {
      throw new MatrixUpstreamError("Matrix createRoom response has no room_id", {
        status: 502,
        path,
        retryable: false,
      });
    }
    return { roomId };
  }

  async downloadMedia(mxcUri: string): Promise<Response> {
    const match = /^mxc:\/\/([^/]+)\/(.+)$/.exec(mxcUri.trim());
    if (!match) {
      throw new Error("a valid mxc:// URI is required");
    }
    const path = `/_matrix/media/v3/download/${encodePathSegment(match[1])}/${encodePathSegment(match[2])}`;
    return this.request(path, { timeoutMs: 20_000 });
  }

  private async requestJson(path: string, options: { method?: string; body?: string; timeoutMs?: number } = {}): Promise<JsonObject> {
    const response = await this.request(path, options);
    try {
      return jsonObject(await response.json());
    } catch {
      throw new MatrixUpstreamError(`Matrix returned invalid JSON for ${path}`, {
        status: 502,
        path,
        retryable: true,
      });
    }
  }

  private async request(
    path: string,
    options: { method?: string; body?: string; timeoutMs?: number; skipAuth?: boolean } = {},
  ): Promise<Response> {
    const token = options.skipAuth ? undefined : await this.ensureAccessToken();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? this.timeoutMs);
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.homeserverUrl}${path}`, {
        method: options.method ?? "GET",
        headers: {
          accept: "application/json",
          ...(options.body ? { "content-type": "application/json" } : {}),
          ...(token ? { authorization: `Bearer ${token}` } : {}),
        },
        body: options.body,
        signal: controller.signal,
      });
    } catch {
      throw new MatrixUpstreamError(`Matrix is unavailable at ${path}`, {
        status: 503,
        path,
        retryable: true,
      });
    } finally {
      clearTimeout(timeout);
    }

    if (!response.ok) {
      const body = boundedErrorBody(await response.text());
      const suffix = body ? `: ${body}` : "";
      throw new MatrixUpstreamError(`Matrix request failed (${response.status})${suffix}`, {
        status: response.status,
        path,
      });
    }
    return response;
  }

  private async ensureAccessToken(): Promise<string> {
    if (this.accessToken) {
      return this.accessToken;
    }
    if (this.loginPromise) {
      return this.loginPromise;
    }
    if (!this.username || !this.password) {
      throw new MatrixUpstreamError("Matrix credentials are not configured", {
        status: 401,
        path: "/_matrix/client/v3/login",
        retryable: false,
      });
    }

    this.loginPromise = this.login();
    try {
      this.accessToken = await this.loginPromise;
      return this.accessToken;
    } finally {
      this.loginPromise = undefined;
    }
  }

  private async login(): Promise<string> {
    const path = "/_matrix/client/v3/login";
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.homeserverUrl}${path}`, {
        method: "POST",
        headers: { accept: "application/json", "content-type": "application/json" },
        body: JSON.stringify({
          type: "m.login.password",
          identifier: { type: "m.id.user", user: this.username },
          password: this.password,
        }),
        signal: controller.signal,
      });
    } catch {
      throw new MatrixUpstreamError("Matrix login is unavailable", {
        status: 503,
        path,
        retryable: true,
      });
    } finally {
      clearTimeout(timeout);
    }
    if (!response.ok) {
      throw new MatrixUpstreamError(`Matrix login failed (${response.status})`, {
        status: response.status,
        path,
        retryable: response.status >= 500,
      });
    }
    let data: JsonObject;
    try {
      data = jsonObject(await response.json());
    } catch {
      throw new MatrixUpstreamError("Matrix login returned invalid JSON", {
        status: 502,
        path,
        retryable: true,
      });
    }
    if (typeof data.access_token !== "string" || !data.access_token) {
      throw new MatrixUpstreamError("Matrix login returned no access token", {
        status: 502,
        path,
        retryable: false,
      });
    }
    return data.access_token;
  }
}
