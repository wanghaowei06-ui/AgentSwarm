import { ControllerClient } from "./controller/client";
import { readDashboardConfig, type DashboardConfig } from "./config";
import { EventHub } from "./events/hub";
import { DashboardSyncLoop } from "./events/sync-loop";
import { EventStore } from "./events/store";
import { MatrixClient } from "./matrix/client";

export type DashboardRuntime = {
  config: DashboardConfig;
  controller: ControllerClient;
  matrix: MatrixClient;
  store: EventStore;
  hub: EventHub;
  syncLoop: DashboardSyncLoop;
  start(): Promise<void>;
};

export const createDashboardRuntime = (config: DashboardConfig): DashboardRuntime => {
  const controller = new ControllerClient({
    baseUrl: config.controllerUrl,
    authToken: config.controllerAuthToken,
  });
  const matrix = new MatrixClient({
    homeserverUrl: config.matrixUrl,
    accessToken: config.matrixToken,
    username: config.adminUser,
    password: config.adminPassword,
  });
  const store = new EventStore({ dataDir: config.dataDir });
  const hub = new EventHub();
  const syncLoop = new DashboardSyncLoop({
    matrix,
    controller,
    store,
    hub,
    matrixSyncTimeoutMs: config.matrixSyncTimeoutMs,
    controllerPollIntervalMs: config.controllerPollIntervalMs,
  });
  return {
    config,
    controller,
    matrix,
    store,
    hub,
    syncLoop,
    start: () => syncLoop.start(),
  };
};

type DashboardGlobal = typeof globalThis & {
  __agentTeamsDashboardRuntime?: DashboardRuntime;
};

export const getDashboardRuntime = (): DashboardRuntime => {
  const globalRuntime = globalThis as DashboardGlobal;
  if (!globalRuntime.__agentTeamsDashboardRuntime) {
    globalRuntime.__agentTeamsDashboardRuntime = createDashboardRuntime(readDashboardConfig());
  }
  return globalRuntime.__agentTeamsDashboardRuntime;
};

export const ensureDashboardRuntime = async (): Promise<DashboardRuntime> => {
  const runtime = getDashboardRuntime();
  await runtime.start();
  return runtime;
};
