export type JsonObject = Record<string, unknown>;

export type EventSource = "matrix" | "controller";

export type EventKind =
  | "message"
  | "workflow"
  | "skill"
  | "tool"
  | "artifact"
  | "room"
  | "system";

export type EvidenceCategory =
  | "collaboration"
  | "skill"
  | "tool"
  | "exception"
  | "artifact"
  | "message"
  | "system";

export type ActorRole =
  | "human"
  | "manager"
  | "worker"
  | "system"
  | "unknown";

export type AgentTeamsEvent = {
  id: string;
  source: EventSource;
  kind: EventKind;
  occurredAt: string;
  roomId?: string;
  runId?: string;
  actor?: {
    id: string;
    label: string;
    displayName?: string;
    role: ActorRole;
  };
  summary: string;
  detail?: JsonObject;
  sourceRef: {
    eventId?: string;
    endpoint?: string;
  };
};

export type RunStatus = "queued" | "running" | "waiting" | "done" | "failed" | "unknown";

export type RunSummary = {
  id: string;
  title: string;
  status: RunStatus;
  roomId: string;
  summary: string;
  updatedAt: string;
  stepCount: number;
  completedStepCount: number;
  attentionCount: number;
};

export type RoomSummary = {
  roomId: string;
  label: string;
  latestAt: string;
  eventCount: number;
  messageCount: number;
};

export type DashboardProjectStatus = "provisioning" | "active" | "failed";

export type DashboardProjectKind = "project" | "manager-dm";

export type DashboardProjectRoom = {
  roomId: string;
  name: string;
  kind: "manager" | "project";
  inviteUserIds: string[];
  createdAt: string;
};

export type DashboardProject = {
  id: string;
  kind: DashboardProjectKind;
  name: string;
  status: DashboardProjectStatus;
  managerUserId: string;
  managerRoomId?: string;
  rooms: DashboardProjectRoom[];
  createdAt: string;
  updatedAt: string;
  error?: string;
};

export type WorkspaceParticipant = {
  userId: string;
  name: string;
  role: "manager" | "leader" | "worker";
  displayName?: string;
};

export type ConversationSource = "controller" | "dashboard-project";

export type ConversationRoomRole = "manager" | "team" | "leader" | "worker" | "project";

export type ConversationRoom = RoomSummary & {
  role: ConversationRoomRole;
  agentName?: string;
  teamName?: string;
};

export type ConversationStatus = "active" | "attention" | "quiet";

export type ConversationSummary = {
  id: string;
  source: ConversationSource;
  projectId?: string;
  projectKind?: DashboardProjectKind;
  projectStatus?: DashboardProjectStatus;
  title: string;
  managerName: string;
  managerUserId?: string;
  managerRoomId: string;
  summary: string;
  status: ConversationStatus;
  latestAt: string;
  eventCount: number;
  messageCount: number;
  roomCount: number;
  agentCount: number;
  collaborationCount: number;
  skillCount: number;
  toolCount: number;
  exceptionCount: number;
  rooms: ConversationRoom[];
};

export type AttentionItem = {
  id: string;
  severity: "info" | "warning" | "error";
  summary: string;
  runId?: string;
  sourceEventId?: string;
};

export type RunDetail = {
  run: RunSummary;
  messages: AgentTeamsEvent[];
  observations: AgentTeamsEvent[];
  workflow?: JsonObject;
  artifacts: AgentTeamsEvent[];
  attention: AttentionItem[];
  traceLinks: string[];
};

export type ConversationDetail = {
  conversation: ConversationSummary;
  rooms: ConversationRoom[];
  messages: AgentTeamsEvent[];
  observations: AgentTeamsEvent[];
  evidence: AgentTeamsEvent[];
  artifacts: AgentTeamsEvent[];
  attention: AttentionItem[];
};

export type RoomDetail = {
  room: RoomSummary;
  messages: AgentTeamsEvent[];
  observations: AgentTeamsEvent[];
  artifacts: AgentTeamsEvent[];
  attention: AttentionItem[];
};

export type WorkspaceProjection = {
  rooms: RoomSummary[];
  runs: RunSummary[];
  conversations: ConversationSummary[];
  unassignedRooms: RoomSummary[];
  attention: AttentionItem[];
};

export type WorkspaceSnapshot = WorkspaceProjection & {
  projects: ConversationSummary[];
  participants: WorkspaceParticipant[];
  generatedAt: string;
  controller: {
    state: "live" | "unavailable";
    data?: JsonObject;
    receivedAt?: string;
    error?: string;
  };
  sync: {
    state: "connecting" | "live" | "degraded" | "stopped";
    cursor?: string;
    updatedAt?: string;
    lastEventAt?: string;
    lastError?: string;
  };
  capabilities: {
    liveSync: boolean;
    traceQuery: false;
  };
};
