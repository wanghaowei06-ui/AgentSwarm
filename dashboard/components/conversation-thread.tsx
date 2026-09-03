"use client";

import { useMemo } from "react";
import {
  AlertTriangle,
  CircleDot,
  LoaderCircle,
  MessageSquare,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  useExternalStoreRuntime,
  type AppendMessage,
  type ExternalStoreAdapter,
} from "@assistant-ui/react";
import type {
  AgentTeamsEvent,
  ConversationDetail,
  ConversationSummary,
  EvidenceCategory,
} from "../lib/types";
import {
  eventEvidenceCategory,
  isCentralConversationEvent,
  isPhaseReport,
  isPriorityEvidence,
  isStructuralRoomEvent,
} from "../lib/events/evidence";
import { EventItem, extractText } from "./run-thread";
import { actorDisplayName } from "../lib/ui/actor";
import type { FeedFilter } from "../lib/ui/navigation";
import { toThreadMessageLike } from "../lib/ui/thread-message";

type ConversationThreadProps = {
  conversation: ConversationSummary;
  detail: ConversationDetail | null;
  loading: boolean;
  sending: boolean;
  sendError?: string;
  filter: FeedFilter;
  query: string;
  onSend: (text: string) => Promise<void>;
};

type ChatEvent = AgentTeamsEvent & { kind: "message" };

const categoryLabels: Record<EvidenceCategory, string> = {
  collaboration: "协作",
  skill: "Skill",
  tool: "工具",
  exception: "异常",
  approval: "人工审批",
  artifact: "产物",
  message: "消息",
  system: "系统",
};

const formatDate = (value: string): string => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
};

const statusClass = (value: string): string =>
  value.toLowerCase().replace(/[^a-z0-9_-]/g, "-");

const matchesFilter = (event: AgentTeamsEvent, filter: FeedFilter): boolean => {
  const category = eventEvidenceCategory(event);
  if (filter === "all") {
    return true;
  }
  if (filter === "key") {
    return event.kind === "message" || isPriorityEvidence(event);
  }
  if (filter === "messages") {
    return event.kind === "message";
  }
  if (filter === "collaboration") {
    return category === "collaboration";
  }
  if (filter === "skill") {
    return category === "skill";
  }
  if (filter === "approval") {
    return category === "approval";
  }
  return category === "exception";
};

const roomRoleLabels: Record<ConversationDetail["rooms"][number]["role"], string> = {
  manager: "Manager",
  team: "Team",
  leader: "Leader DM",
  worker: "Worker",
  project: "项目房间",
};

const roomLabel = (
  roomId: string | undefined,
  rooms: ConversationDetail["rooms"],
): string => rooms.find((room) => room.roomId === roomId)?.label || "未命名 room";

function ConversationEvidence({
  event,
  rooms,
}: {
  event: AgentTeamsEvent;
  rooms: ConversationDetail["rooms"];
}) {
  const category = eventEvidenceCategory(event);
  return (
    <article className={`conversation-evidence ${isPriorityEvidence(event) ? "priority" : "context"}`}>
      <div className="evidence-context">
        <span className={`evidence-category ${statusClass(category)}`}>
          {category === "exception"
            ? <AlertTriangle size={11} />
            : category === "approval"
              ? <ShieldCheck size={11} />
              : category === "skill"
                ? <Sparkles size={11} />
                : <CircleDot size={11} />}
          {categoryLabels[category]}
        </span>
        <span className="evidence-room">{roomLabel(event.roomId, rooms)}</span>
        <span className="evidence-actor">{actorDisplayName(event)}</span>
        <span className="evidence-time">{formatDate(event.occurredAt)}</span>
      </div>
      <EventItem event={event} />
    </article>
  );
}

export function ConversationThread({
  conversation,
  detail,
  loading,
  sending,
  sendError,
  filter,
  query,
  onSend,
}: ConversationThreadProps) {
  const rooms = detail?.rooms || conversation.rooms;
  const observations = useMemo(() => detail?.observations || [], [detail?.observations]);
  const visibleObservations = useMemo(
    () => observations.filter(isCentralConversationEvent),
    [observations],
  );
  const chatEvents = useMemo<ChatEvent[]>(
    () => (detail?.messages || []).filter((event): event is ChatEvent => event.kind === "message" && isCentralConversationEvent(event)),
    [detail?.messages],
  );
  const filteredEvents = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return visibleObservations.filter((event) => {
      if (!matchesFilter(event, filter)) {
        return false;
      }
      if (!normalizedQuery) {
        return true;
      }
      return [
        event.summary,
        event.actor?.displayName,
        event.actor?.label,
        event.sourceRef.eventId,
        event.sourceRef.endpoint,
        event.roomId,
        event.detail?.name,
        event.detail?.skillName,
        event.detail?.status,
      ].some((value) => typeof value === "string" && value.toLowerCase().includes(normalizedQuery));
    });
  }, [filter, query, visibleObservations]);
  const adapter = useMemo<ExternalStoreAdapter<ChatEvent>>(() => ({
    messages: chatEvents,
    isLoading: loading,
    isRunning: sending,
    isSendDisabled: sending || (conversation.source === "dashboard-project" && conversation.projectStatus !== "active"),
    onNew: async (message: AppendMessage) => {
      const text = extractText(message);
      if (text) {
        await onSend(text);
      }
    },
    convertMessage: (message) => {
      const converted = toThreadMessageLike(message);
      if (!converted) {
        throw new Error("Only message events can be converted to chat messages");
      }
      return converted;
    },
  }), [chatEvents, conversation.projectStatus, conversation.source, loading, onSend, sending]);
  const runtime = useExternalStoreRuntime(adapter);
  const hiddenProgressCount = observations.filter(isPhaseReport).length;
  const hiddenStructuralCount = observations.filter(isStructuralRoomEvent).length;

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <section className="thread-pane conversation-pane" aria-label="Conversation with AgentTeams Manager">
        <div className="event-scroll conversation-event-scroll">
          <div className="event-list conversation-event-list">
            {loading && (
              <div className="empty-state">
                <LoaderCircle className="spin-icon" size={24} />
                <p className="empty-state-title">正在读取真实协作证据</p>
                <p className="empty-state-copy">正在从 Manager、Team、Leader 和 Worker rooms 合并已观测事件。</p>
              </div>
            )}
            {!loading && observations.length === 0 && (
              <div className="empty-state">
                <MessageSquare size={24} className="empty-state-icon" />
                <p className="empty-state-title">还没有会话事件</p>
                <p className="empty-state-copy">当前 Manager 会话已建立，但真实 Matrix timeline 还没有可展示的内容。</p>
              </div>
            )}
            {!loading && observations.length > 0 && visibleObservations.length === 0 && (
              <div className="empty-state">
                <CircleDot size={24} className="empty-state-icon" />
                <p className="empty-state-title">中心暂时没有对话内容</p>
                <p className="empty-state-copy">
                  {hiddenProgressCount > 0
                    ? "当前会话只有阶段进度报告；完整报告已整理到右侧证据栏，中心保留 Manager 对话。"
                    : hiddenStructuralCount > 0
                      ? "当前会话只有 Matrix room 元数据，已从对话流隐藏。"
                      : "当前会话暂时没有可展示的消息或关键证据。"}
                </p>
              </div>
            )}
            {!loading && visibleObservations.length > 0 && filteredEvents.length === 0 && (
              <div className="empty-state">
                <Search size={24} className="empty-state-icon" />
                <p className="empty-state-title">没有匹配的证据</p>
                <p className="empty-state-copy">切换筛选或清空关键词，查看这个 Manager 会话的完整链路。</p>
              </div>
            )}
            {!loading && filteredEvents.map((event) => <ConversationEvidence event={event} rooms={rooms} key={event.id} />)}
          </div>
        </div>

        <div className="composer-wrap">
          <div className="composer-shell">
            <ComposerPrimitive.Root className="composer-form">
              <ComposerPrimitive.Input
                className="composer-input"
                placeholder="向 Manager 发送消息…"
                submitMode="ctrlEnter"
                aria-label="Message the AgentTeams Manager"
              />
              <div className="composer-footer">
                <div className="composer-hints"><kbd>⌘ / Ctrl</kbd><span>+ Enter 发送到 Manager room</span></div>
                <ComposerPrimitive.Send className="composer-send" aria-label="Send message to Manager">
                  {sending ? <LoaderCircle size={14} className="spin-icon" /> : <Send size={14} />}
                  <span>{sending ? "发送中" : "发送"}</span>
                </ComposerPrimitive.Send>
              </div>
            </ComposerPrimitive.Root>
            {sendError && <p className="composer-error">发送失败：{sendError}</p>}
          </div>
        </div>
      </section>
    </AssistantRuntimeProvider>
  );
}

export const conversationRoomRoleLabel = (role: ConversationDetail["rooms"][number]["role"]): string =>
  roomRoleLabels[role];
