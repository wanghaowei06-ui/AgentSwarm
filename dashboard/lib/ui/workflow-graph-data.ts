import type { JsonObject } from "../types";

export type WorkflowGraphNode = {
  id: string;
  label: string;
  status: string;
  x: number;
  y: number;
};

export type WorkflowGraphEdge = {
  id: string;
  source: string;
  target: string;
};

export type WorkflowGraphData = {
  nodes: WorkflowGraphNode[];
  edges: WorkflowGraphEdge[];
};

const objectValue = (value: unknown): JsonObject | undefined =>
  typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as JsonObject
    : undefined;

const textValue = (value: unknown): string =>
  typeof value === "string" && value.trim() ? value.trim() : "";

const dependencies = (value: unknown): string[] => {
  if (typeof value === "string" && value.trim()) {
    return [value.trim()];
  }
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0).map((item) => item.trim())
    : [];
};

export const workflowGraphData = (workflow: JsonObject | undefined): WorkflowGraphData => {
  const rawSteps = workflow?.steps;
  const steps = Array.isArray(rawSteps)
    ? rawSteps.map(objectValue).filter((step): step is JsonObject => Boolean(step))
    : [];
  const ids = new Set<string>();
  const nodes = steps.map((step, index) => {
    const id = textValue(step.id) || `step-${index + 1}`;
    ids.add(id);
    return {
      id,
      label: textValue(step.title) || textValue(step.label) || textValue(step.name) || textValue(step.summary) || `Step ${index + 1}`,
      status: textValue(step.status) || "unknown",
      x: index * 280,
      y: 0,
    };
  });
  const edges: WorkflowGraphEdge[] = [];
  steps.forEach((step, index) => {
    const target = nodes[index]?.id;
    if (!target) {
      return;
    }
    for (const source of dependencies(step.dependsOn ?? step.dependencies)) {
      if (ids.has(source) && source !== target) {
        edges.push({ id: `${source}->${target}`, source, target });
      }
    }
  });
  return { nodes, edges };
};
