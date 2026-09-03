import type { ActorRole, AgentTeamsEvent } from "../types";

export const actorDisplayName = (event: AgentTeamsEvent): string =>
  event.actor?.displayName || event.actor?.label || "unknown actor";

export const actorRoleLabel: Record<ActorRole, string> = {
  human: "用户",
  manager: "管理者",
  worker: "工作者",
  system: "系统",
  unknown: "未知",
};
