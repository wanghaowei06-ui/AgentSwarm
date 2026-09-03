"use client";

import { useMemo, useState } from "react";
import { LoaderCircle, MessageSquare, Search, Send } from "lucide-react";
import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  useExternalStoreRuntime,
  type ExternalStoreAdapter,
} from "@assistant-ui/react";
import type { AgentTeamsEvent, RoomDetail, RoomSummary } from "../lib/types";
import { EventItem, extractText } from "./run-thread";
import { toThreadMessageLike } from "../lib/ui/thread-message";

type ChatEvent = AgentTeamsEvent & { kind: "message" };

type RoomThreadProps = {
  room: RoomSummary;
  detail: RoomDetail | null;
  loading: boolean;
  sending: boolean;
  sendError?: string;
  onSend: (text: string) => Promise<void>;
};

const formatDate = (value: string): string => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(date);
};

export function RoomThread({ room, detail, loading, sending, sendError, onSend }: RoomThreadProps) {
  const [query, setQuery] = useState("");
  const chatEvents = useMemo<ChatEvent[]>(
    () => (detail?.messages || []).filter((event): event is ChatEvent => event.kind === "message"),
    [detail?.messages],
  );
  const adapter = useMemo<ExternalStoreAdapter<ChatEvent>>(() => ({
    messages: chatEvents,
    isLoading: loading,
    isRunning: sending,
    isSendDisabled: sending,
    onNew: async (message) => {
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
  }), [chatEvents, loading, onSend, sending]);
  const runtime = useExternalStoreRuntime(adapter);
  const observations = useMemo(() => detail?.observations || [], [detail?.observations]);
  const filteredObservations = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    if (!normalizedQuery) {
      return observations;
    }
    return observations.filter((event) => [
      event.summary,
      event.actor?.displayName,
      event.actor?.label,
      event.sourceRef.eventId,
      event.kind,
    ].some((value) => typeof value === "string" && value.toLowerCase().includes(normalizedQuery)));
  }, [observations, query]);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <section className="thread-pane" aria-label="Unclassified Matrix room conversation">
        <header className="thread-header">
          <div>
            <div className="thread-title-line">
              <h1 className="thread-title">{room.label}</h1>
              <span className="status-badge">room timeline</span>
            </div>
            <p className="thread-subtitle">这个 room 还没有明确的 workflow run，先以真实消息时间线呈现。</p>
          </div>
          <div className="thread-header-meta">
            <span className="thread-room" title={room.roomId}>{room.roomId}</span>
            <span className="mono-label">last {formatDate(room.latestAt)}</span>
          </div>
        </header>

        <div className="thread-tools">
          <label className="thread-filter">
            <Search size={13} />
            <span className="sr-only">筛选当前 room 事件</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="筛选消息或事件 ID…"
              type="search"
            />
          </label>
          <span className="mono-label">{filteredObservations.length}/{observations.length} observed</span>
        </div>

        <div className="event-scroll">
          <div className="event-list">
            {loading && (
              <div className="empty-state">
                <LoaderCircle size={24} className="spin-icon" />
                <p className="empty-state-title">正在读取 room timeline</p>
              </div>
            )}
            {!loading && observations.length === 0 && (
              <div className="empty-state">
                <MessageSquare size={24} className="empty-state-icon" />
                <p className="empty-state-title">room 暂无消息</p>
                <p className="empty-state-copy">事件同步完成后，新的真实 Matrix 消息会出现在这里。</p>
              </div>
            )}
            {!loading && observations.length > 0 && filteredObservations.length === 0 && (
              <div className="empty-state">
                <Search size={24} className="empty-state-icon" />
                <p className="empty-state-title">没有匹配的事件</p>
              </div>
            )}
            {!loading && filteredObservations.map((event) => <EventItem event={event} key={event.id} />)}
          </div>
        </div>

        <div className="composer-wrap">
          <div className="composer-shell">
            <ComposerPrimitive.Root className="composer-form">
              <ComposerPrimitive.Input
                className="composer-input"
                placeholder="向这个 Matrix room 发送消息…"
                submitMode="ctrlEnter"
                aria-label="Message this Matrix room"
              />
              <div className="composer-footer">
                <div className="composer-hints"><kbd>⌘ / Ctrl</kbd><span>+ Enter 发送到 Matrix</span></div>
                <ComposerPrimitive.Send className="composer-send" aria-label="Send message">
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
