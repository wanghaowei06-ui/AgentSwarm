export class DashboardConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DashboardConfigError";
  }
}

export type DashboardConfig = {
  controllerUrl: string;
  controllerAuthToken: string;
  matrixUrl: string;
  matrixToken?: string;
  adminUser?: string;
  adminPassword?: string;
  dataDir: string;
  matrixSyncTimeoutMs: number;
  controllerPollIntervalMs: number;
};

type Environment = Record<string, string | undefined>;

const required = (environment: Environment, key: string): string => {
  const value = environment[key]?.trim();
  if (!value) {
    throw new DashboardConfigError(`${key} is required for the Dashboard`);
  }
  return value;
};

const positiveInteger = (environment: Environment, key: string, fallback: number): number => {
  const raw = environment[key]?.trim();
  if (!raw) {
    return fallback;
  }
  const parsed = Number(raw);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new DashboardConfigError(`${key} must be a positive integer`);
  }
  return parsed;
};

export const readDashboardConfig = (environment: Environment = process.env): DashboardConfig => {
  const matrixToken = environment.AGENTTEAMS_MATRIX_TOKEN?.trim() || undefined;
  const adminUser = environment.AGENTTEAMS_ADMIN_USER?.trim() || undefined;
  const adminPassword = environment.AGENTTEAMS_ADMIN_PASSWORD || undefined;
  if (!matrixToken && (!adminUser || !adminPassword)) {
    throw new DashboardConfigError(
      "Matrix access token or admin credentials are required for the Dashboard",
    );
  }

  return {
    controllerUrl: required(environment, "AGENTTEAMS_CONTROLLER_URL").replace(/\/+$/, ""),
    controllerAuthToken: required(environment, "AGENTTEAMS_AUTH_TOKEN"),
    matrixUrl: required(environment, "NEXT_PUBLIC_MATRIX_API_URL").replace(/\/+$/, ""),
    matrixToken,
    adminUser,
    adminPassword,
    dataDir: environment.AGENTTEAMS_DASHBOARD_DATA_DIR?.trim() || "/app/db",
    matrixSyncTimeoutMs: positiveInteger(environment, "AGENTTEAMS_DASHBOARD_MATRIX_SYNC_TIMEOUT_MS", 25_000),
    controllerPollIntervalMs: positiveInteger(environment, "AGENTTEAMS_DASHBOARD_CONTROLLER_POLL_MS", 10_000),
  };
};
