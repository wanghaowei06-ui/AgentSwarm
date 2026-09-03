import { describe, expect, it } from "vitest";
import { workflowGraphData } from "../lib/ui/workflow-graph-data";

describe("workflowGraphData", () => {
  it("creates stable nodes and only draws declared dependencies", () => {
    const graph = workflowGraphData({
      steps: [
        { id: "research", title: "Research", status: "done" },
        { id: "review", label: "Review", status: "running", dependsOn: ["research"] },
        { id: "publish", title: "Publish", status: "queued", dependsOn: ["review", "missing"] },
      ],
    });

    expect(graph.nodes).toEqual([
      { id: "research", label: "Research", status: "done", x: 0, y: 0 },
      { id: "review", label: "Review", status: "running", x: 280, y: 0 },
      { id: "publish", label: "Publish", status: "queued", x: 560, y: 0 },
    ]);
    expect(graph.edges).toEqual([
      { id: "research->review", source: "research", target: "review" },
      { id: "review->publish", source: "review", target: "publish" },
    ]);
  });

  it("falls back to a readable step label and handles absent steps", () => {
    expect(workflowGraphData({ steps: [{ id: "step-1", status: "waiting" }] })).toEqual({
      nodes: [{ id: "step-1", label: "Step 1", status: "waiting", x: 0, y: 0 }],
      edges: [],
    });
    expect(workflowGraphData({})).toEqual({ nodes: [], edges: [] });
  });
});
