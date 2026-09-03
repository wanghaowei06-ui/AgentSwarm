"use client";

import { useMemo } from "react";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { JsonObject } from "../lib/types";
import { workflowGraphData } from "../lib/ui/workflow-graph-data";

type WorkflowNodeData = {
  label: string;
  status: string;
};

type WorkflowNode = Node<WorkflowNodeData, "workflowStep">;

const statusClass = (value: string): string => value.toLowerCase().replace(/[^a-z0-9_-]/g, "-");

function WorkflowStepNode({ data }: NodeProps<WorkflowNode>) {
  const state = statusClass(data.status);
  return (
    <div className={`flow-node ${state}`}>
      <Handle type="target" position={Position.Left} />
      <span className="flow-node-title">{data.label}</span>
      <span className="flow-node-status">{data.status}</span>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const nodeTypes = { workflowStep: WorkflowStepNode };

export function WorkflowGraph({ workflow }: { workflow?: JsonObject }) {
  const graph = useMemo(() => workflowGraphData(workflow), [workflow]);
  const nodes = useMemo<WorkflowNode[]>(
    () => graph.nodes.map((node) => ({
      id: node.id,
      type: "workflowStep",
      position: { x: node.x, y: node.y },
      data: { label: node.label, status: node.status },
      draggable: false,
    })),
    [graph.nodes],
  );
  const edges = useMemo<Edge[]>(
    () => graph.edges.map((edge) => ({
      ...edge,
      type: "smoothstep",
      animated: nodes.some((node) => node.id === edge.target && node.data.status === "running"),
    })),
    [graph.edges, nodes],
  );

  if (!nodes.length) {
    return (
      <div className="empty-state compact-empty">
        <div className="empty-state-icon" aria-hidden="true">—</div>
        <p className="empty-state-title">暂无工作流节点</p>
        <p className="empty-state-copy">等待 AgentTeams 发出带有 steps 的 workflow 事件。</p>
      </div>
    );
  }

  return (
    <div className="flow-shell" aria-label="Workflow dependency graph">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.35 }}
        nodesConnectable={false}
        nodesDraggable={false}
        zoomOnDoubleClick={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#263636" gap={18} size={1} />
        <Controls showInteractive={false} />
        <MiniMap
          pannable
          zoomable
          nodeColor={(node) => node.data?.status === "running" ? "#70d3c6" : "#344143"}
        />
      </ReactFlow>
    </div>
  );
}
