import { describe, expect, it } from "vitest";

import { workspaceNavigationItems } from "../lib/ui/navigation";

describe("Workspace navigation", () => {
  it("keeps the existing navigation choices in Workspace order", () => {
    expect(workspaceNavigationItems).toEqual([
      { id: "workspace", label: "Workspace", active: true },
      { id: "observability", label: "Observability", active: false },
      { id: "artifacts", label: "Artifacts", active: false },
    ]);
  });
});
