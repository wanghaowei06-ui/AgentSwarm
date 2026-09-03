export type FeedFilter = "key" | "messages" | "collaboration" | "skill" | "exceptions" | "all";

export const feedFilterLabels: Record<FeedFilter, string> = {
  key: "关键链路",
  messages: "聊天消息",
  collaboration: "Agent 协作",
  skill: "Skill 调用",
  exceptions: "异常证据",
  all: "全部事件",
};

export const workspaceNavigationItems = [
  { id: "workspace", label: "Workspace", active: true },
  { id: "observability", label: "Observability", active: false },
  { id: "artifacts", label: "Artifacts", active: false },
] as const;
