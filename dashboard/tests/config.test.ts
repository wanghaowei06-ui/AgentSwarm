import { describe, expect, it } from "vitest";

import { DashboardConfigError, readDashboardConfig } from "../lib/config";

describe("readDashboardConfig", () => {
  it("requires the real controller, Matrix and server credentials", () => {
    expect(() => readDashboardConfig({})).toThrow(DashboardConfigError);
    expect(() => readDashboardConfig({
      AGENTTEAMS_CONTROLLER_URL: "http://controller",
      AGENTTEAMS_AUTH_TOKEN: "controller-token",
      NEXT_PUBLIC_MATRIX_API_URL: "http://matrix",
    })).toThrow(/Matrix access token or admin credentials/);
  });

  it("prefers a fixed server-side Matrix token when one is configured", () => {
    const config = readDashboardConfig({
      AGENTTEAMS_CONTROLLER_URL: "http://controller/",
      AGENTTEAMS_AUTH_TOKEN: "controller-token",
      NEXT_PUBLIC_MATRIX_API_URL: "http://matrix/",
      AGENTTEAMS_MATRIX_TOKEN: "matrix-token",
      AGENTTEAMS_DASHBOARD_DATA_DIR: "/tmp/dashboard-data",
    });

    expect(config).toMatchObject({
      controllerUrl: "http://controller",
      matrixUrl: "http://matrix",
      matrixToken: "matrix-token",
      dataDir: "/tmp/dashboard-data",
    });
    expect(config.adminPassword).toBeUndefined();
  });
});
