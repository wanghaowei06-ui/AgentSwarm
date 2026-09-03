import type { JsonObject } from "../types";

export type ControllerRead<T> = {
  data: T;
  source: "controller";
  endpoint: string;
  receivedAt: string;
};

export class ControllerUpstreamError extends Error {
  readonly source = "controller" as const;
  readonly status: number;
  readonly endpoint: string;
  readonly retryable: boolean;

  constructor(message: string, options: { status: number; endpoint: string; retryable?: boolean }) {
    super(message);
    this.name = "ControllerUpstreamError";
    this.status = options.status;
    this.endpoint = options.endpoint;
    this.retryable = options.retryable ?? options.status >= 500;
  }
}

type FetchLike = typeof fetch;

type ControllerClientOptions = {
  baseUrl: string;
  authToken: string;
  fetchImpl?: FetchLike;
  timeoutMs?: number;
};

const trimTrailingSlash = (value: string): string => value.replace(/\/+$/, "");

const boundedErrorBody = (value: string): string => value.replace(/\s+/g, " ").trim().slice(0, 240);

export class ControllerClient {
  private readonly baseUrl: string;
  private readonly authToken: string;
  private readonly fetchImpl: FetchLike;
  private readonly timeoutMs: number;

  constructor(options: ControllerClientOptions) {
    if (!options.baseUrl.trim()) {
      throw new Error("AGENTTEAMS_CONTROLLER_URL is required");
    }
    if (!options.authToken.trim()) {
      throw new Error("AGENTTEAMS_AUTH_TOKEN is required");
    }
    this.baseUrl = trimTrailingSlash(options.baseUrl.trim());
    this.authToken = options.authToken;
    this.fetchImpl = options.fetchImpl ?? fetch;
    this.timeoutMs = options.timeoutMs ?? 8_000;
  }

  async getHealth(): Promise<ControllerRead<string>> {
    return this.requestText("/healthz");
  }

  async getStatus<T extends JsonObject = JsonObject>(): Promise<ControllerRead<T>> {
    return this.requestJson<T>("/api/v1/status");
  }

  async getWorkers<T extends JsonObject = JsonObject>(): Promise<ControllerRead<T>> {
    return this.requestJson<T>("/api/v1/workers");
  }

  async getTeams<T extends JsonObject = JsonObject>(): Promise<ControllerRead<T>> {
    return this.requestJson<T>("/api/v1/teams");
  }

  async getManagers<T extends JsonObject = JsonObject>(): Promise<ControllerRead<T>> {
    return this.requestJson<T>("/api/v1/managers");
  }

  async getWorkerStatus<T extends JsonObject = JsonObject>(name: string): Promise<ControllerRead<T>> {
    const encodedName = encodeURIComponent(name.trim());
    if (!encodedName) {
      throw new Error("worker name is required");
    }
    return this.requestJson<T>(`/api/v1/workers/${encodedName}/status`);
  }

  private async requestText(path: string): Promise<ControllerRead<string>> {
    const response = await this.request(path);
    const data = await response.text();
    return {
      data,
      source: "controller",
      endpoint: path,
      receivedAt: new Date().toISOString(),
    };
  }

  private async requestJson<T>(path: string): Promise<ControllerRead<T>> {
    const response = await this.request(path);
    try {
      const data = (await response.json()) as T;
      return {
        data,
        source: "controller",
        endpoint: path,
        receivedAt: new Date().toISOString(),
      };
    } catch {
      throw new ControllerUpstreamError(`Controller returned invalid JSON for ${path}`, {
        status: 502,
        endpoint: path,
        retryable: true,
      });
    }
  }

  private async request(path: string): Promise<Response> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method: "GET",
        headers: {
          accept: "application/json, text/plain",
          authorization: `Bearer ${this.authToken}`,
        },
        signal: controller.signal,
      });
    } catch {
      throw new ControllerUpstreamError(`Controller is unavailable at ${path}`, {
        status: 503,
        endpoint: path,
        retryable: true,
      });
    } finally {
      clearTimeout(timeout);
    }

    if (!response.ok) {
      const body = boundedErrorBody(await response.text());
      const suffix = body ? `: ${body}` : "";
      throw new ControllerUpstreamError(`Controller request failed (${response.status})${suffix}`, {
        status: response.status,
        endpoint: path,
      });
    }
    return response;
  }
}
