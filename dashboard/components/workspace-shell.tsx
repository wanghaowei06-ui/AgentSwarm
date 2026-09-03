"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  Bot,
  CircleDot,
  ChevronDown,
  Inbox,
  MoreHorizontal,
  RefreshCw,
  Search,
  Settings2,
  Sparkles,
} from "lucide-react";
import type { ConversationDetail, ConversationSummary, WorkspaceSnapshot } from "../lib/types";
import { feedFilterLabels, workspaceNavigationItems, type FeedFilter } from "../lib/ui/navigation";
import { ActivityRail } from "./activity-rail";
import { ConversationThread } from "./conversation-thread";

type Selection = {
  type: "conversation";
  id: string;
};

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const responseMessage = async (response: Response): Promise<string> => {
  try {
    const body: unknown = await response.json();
    if (isObject(body) && typeof body.message === "string" && body.message.trim()) {
      return body.message.trim();
    }
  } catch {
    // The upstream may return an empty or non-JSON error body.
  }
  return `${response.status} ${response.statusText || "Request failed"}`;
};

const fetchJson = async <T,>(url: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(url, { cache: "no-store", ...init });
  if (!response.ok) {
    throw new Error(await responseMessage(response));
  }
  return response.json() as Promise<T>;
};

const formatRunTime = (value: string): string => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
};

const syncLabel: Record<WorkspaceSnapshot["sync"]["state"], string> = {
  connecting: "连接中",
  live: "实时同步",
  degraded: "同步降级",
  stopped: "已停止",
};

const conversationCountLabel = (conversations: ConversationSummary[]): string =>
  `${conversations.length} ${conversations.length === 1 ? "active conversation" : "active conversations"}`;

function ConversationList({
  snapshot,
  selection,
  onSelect,
}: {
  snapshot: WorkspaceSnapshot;
  selection?: Selection;
  onSelect: (selection: Selection) => void;
}) {
  return (
    <aside className="sidebar" aria-label="Manager conversations">
      <div className="sidebar-heading">
        <p className="eyebrow">Manager inbox</p>
        <h2 className="page-title">与 Manager 的对话</h2>
        <p className="sidebar-copy">一次对话承载主任务，关联的 Team、Leader 和 Worker room 作为协作证据。</p>
      </div>
      <div className="conversation-list">
        <p className="run-list-label">Conversations · {conversationCountLabel(snapshot.conversations)}</p>
        {snapshot.conversations.length > 0 ? snapshot.conversations.map((conversation) => {
          const active = selection?.type === "conversation" && conversation.id === selection.id;
          return (
            <div className={`conversation-entry ${active ? "active" : ""}`} key={conversation.id}>
              <button
                className="conversation-item"
                type="button"
                onClick={() => onSelect({ type: "conversation", id: conversation.id })}
              >
                <span className={`run-item-indicator ${conversation.status}`} aria-hidden="true" />
                <span className="run-item-body">
                  <span className="run-item-title">
                    <span><Bot size={13} />{conversation.title}</span>
                    <span className="run-item-time">{formatRunTime(conversation.latestAt)}</span>
                  </span>
                  <span className="run-item-meta">
                    <span>{conversation.agentCount} agents</span>
                    <span>·</span>
                    <span>{conversation.roomCount} rooms</span>
                    {conversation.exceptionCount > 0 && <span className="run-badge attention">· {conversation.exceptionCount} alert</span>}
                  </span>
                  <span className="run-item-summary">{conversation.summary}</span>
                </span>
              </button>
              {active && conversation.rooms.length > 0 && (
                <div className="conversation-room-scope">
                  <span className="scope-label">linked evidence</span>
                  {conversation.rooms.slice(0, 4).map((room) => (
                    <span className="scope-room" key={room.roomId} title={room.roomId}>
                      <CircleDot size={10} />
                      <span>{room.label}</span>
                    </span>
                  ))}
                  {conversation.rooms.length > 4 && <span className="scope-more">+{conversation.rooms.length - 4} rooms</span>}
                </div>
              )}
            </div>
          );
        }) : (
          <div className="empty-state compact-empty">
            <Inbox size={20} />
            <p className="empty-state-title">等待 Manager 会话</p>
            <p className="empty-state-copy">Controller 暴露 Manager room 后，真实对话会出现在这里。</p>
          </div>
        )}
        <div className="unassigned-summary">
          <span><CircleDot size={11} /> 未归类证据 room</span>
          <strong>{snapshot.unassignedRooms.length}</strong>
        </div>
      </div>
      <div className="sidebar-footer">
        <span><Settings2 size={13} /> server-side adapters</span>
        <span className="mono-label">no mock data</span>
      </div>
    </aside>
  );
}

function EmptyConversationPane({ onRefresh, refreshing }: { onRefresh: () => void; refreshing: boolean }) {
  return (
    <section className="thread-pane" aria-label="Current Manager conversation">
      <div className="empty-state">
        <div className="empty-state-icon"><Sparkles size={20} /></div>
        <p className="empty-state-title">还没有可展示的 Manager 会话</p>
        <p className="empty-state-copy">Dashboard 不会生成演示数据。请确认 Controller 返回 Manager room，或等待真实同步完成。</p>
        <button className="empty-state-action" type="button" onClick={onRefresh} disabled={refreshing}>
          <RefreshCw size={13} className={refreshing ? "spin-icon" : undefined} />
          重新读取真实数据
        </button>
      </div>
    </section>
  );
}

function ErrorPane({ message, onRetry, retrying }: { message: string; onRetry: () => void; retrying: boolean }) {
  return (
    <main className="empty-screen">
      <div className="empty-state-icon"><AlertTriangle size={20} /></div>
      <p className="empty-state-title">Dashboard 尚未连上上游</p>
      <p className="empty-state-copy">{message}</p>
      <button className="empty-state-action" type="button" onClick={onRetry} disabled={retrying}>
        <RefreshCw size={13} className={retrying ? "spin-icon" : undefined} />
        再试一次
      </button>
    </main>
  );
}

function WorkspaceHeader({
  syncState,
  streamState,
  onRefresh,
  refreshing,
  filter,
  query,
  onFilterChange,
  onQueryChange,
}: {
  syncState: WorkspaceSnapshot["sync"]["state"];
  streamState: "connecting" | "live" | "degraded";
  onRefresh: () => void;
  refreshing: boolean;
  filter: FeedFilter;
  query: string;
  onFilterChange: (filter: FeedFilter) => void;
  onQueryChange: (query: string) => void;
}) {
  const displayState = syncState === "stopped" ? streamState : syncState;
  return (
    <header className="topbar">
      <div className="brand-lockup">
        <div className="brand-mark" aria-hidden="true">AT</div>
        <div>
          <div className="brand-name">AgentTeams Workspace</div>
          <div className="brand-subtitle">MATRIX / CONTROL PLANE / LIVE</div>
        </div>
      </div>
      <nav className="workspace-nav" aria-label="Workspace navigation">
        <div className="workspace-nav-menu">
          <button className="workspace-nav-trigger" type="button" aria-haspopup="menu">
            <span>Workspace</span>
            <ChevronDown size={15} aria-hidden="true" />
          </button>
          <div className="workspace-nav-dropdown" role="menu" aria-label="Workspace views and filters">
            <span className="workspace-menu-label">Workspace</span>
            <div className="workspace-view-list">
              {workspaceNavigationItems.map((item) => (
                <span
                  className={`workspace-nav-option ${item.active ? "active" : ""}`}
                  key={item.id}
                  role="menuitem"
                  aria-current={item.active ? "page" : undefined}
                >
                  {item.label}
                </span>
              ))}
            </div>
            <div className="workspace-menu-divider" />
            <span className="workspace-menu-label">当前会话</span>
            <div className="workspace-filter-list" role="group" aria-label="Conversation filters">
              {(Object.keys(feedFilterLabels) as FeedFilter[]).map((option) => (
                <button
                  className={`workspace-filter-option ${filter === option ? "active" : ""}`}
                  key={option}
                  type="button"
                  role="menuitemradio"
                  aria-checked={filter === option}
                  onClick={() => onFilterChange(option)}
                >
                  <span>{feedFilterLabels[option]}</span>
                  <span className="workspace-filter-mark" aria-hidden="true" />
                </button>
              ))}
            </div>
            <label className="workspace-filter-search">
              <Search size={13} aria-hidden="true" />
              <span className="sr-only">筛选当前会话事件</span>
              <input
                value={query}
                onChange={(event) => onQueryChange(event.target.value)}
                placeholder="筛选事件…"
                type="search"
              />
            </label>
          </div>
        </div>
      </nav>
      <div className="topbar-actions">
        <button className="topbar-menu-trigger" type="button" aria-label="展开工作区控制" title="移入以展开工作区控制">
          <MoreHorizontal size={16} />
        </button>
        <div className="topbar-control-panel">
          <span className={`status-inline ${displayState}`}>
            <i className="status-dot" aria-hidden="true" />
            {syncLabel[displayState] || "连接中"}
          </span>
          <button className="topbar-action" type="button" onClick={onRefresh} disabled={refreshing}>
            <RefreshCw size={13} className={refreshing ? "spin-icon" : undefined} />
            <span>Refresh</span>
          </button>
          <button className="topbar-action" type="button" title="The dashboard reads server-side configuration" aria-label="Configuration is server-side only">
            <ArrowUpRight size={13} />
            <span>Live sources</span>
          </button>
        </div>
      </div>
    </header>
  );
}

export function WorkspaceShell() {
  const [snapshot, setSnapshot] = useState<WorkspaceSnapshot | null>(null);
  const [selection, setSelection] = useState<Selection>();
  const [conversationDetail, setConversationDetail] = useState<ConversationDetail | null>(null);
  const [refreshing, setRefreshing] = useState(true);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState<string>();
  const [conversationError, setConversationError] = useState<{ type: Selection["type"]; id: string; message: string } | null>(null);
  const [sendError, setSendError] = useState<string>();
  const [sending, setSending] = useState(false);
  const [feedFilter, setFeedFilter] = useState<FeedFilter>("key");
  const [eventQuery, setEventQuery] = useState("");
  const [streamState, setStreamState] = useState<"connecting" | "live" | "degraded">("connecting");
  const hasSnapshot = snapshot !== null;

  const refreshWorkspace = useCallback(async () => {
    setRefreshing(true);
    try {
      const next = await fetchJson<WorkspaceSnapshot>("/api/workspace");
      setSnapshot(next);
      setError(undefined);
      setStreamState(next.sync.state === "degraded" ? "degraded" : "live");
      setSelection((current) => {
        if (current?.type === "conversation" && next.conversations.some((conversation) => conversation.id === current.id)) {
          return current;
        }
        return next.conversations[0] ? { type: "conversation", id: next.conversations[0].id } : undefined;
      });
      setRevision((value) => value + 1);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法读取 workspace");
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void Promise.resolve().then(refreshWorkspace);
  }, [refreshWorkspace]);

  useEffect(() => {
    if (!selection) {
      return;
    }
    let cancelled = false;
    const endpoint = `/api/conversations/${encodeURIComponent(selection.id)}`;
    void fetchJson<ConversationDetail>(endpoint)
      .then((next) => {
        if (cancelled) {
          return;
        }
        setConversationDetail(next);
        setConversationError(null);
      })
      .catch((caught) => {
        if (!cancelled) {
          setConversationError({
            type: selection.type,
            id: selection.id,
            message: caught instanceof Error ? caught.message : "无法读取会话",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [revision, selection]);

  useEffect(() => {
    if (!hasSnapshot) {
      return;
    }
    const eventSource = new EventSource("/api/events");
    const refreshFromEvent = () => {
      setStreamState("live");
      void refreshWorkspace();
    };
    eventSource.onopen = () => setStreamState("live");
    eventSource.onerror = () => setStreamState("degraded");
    eventSource.addEventListener("observation", refreshFromEvent);
    eventSource.addEventListener("run.updated", refreshFromEvent);
    eventSource.addEventListener("controller.updated", refreshFromEvent);
    eventSource.addEventListener("sync.status", refreshFromEvent);
    return () => eventSource.close();
  }, [refreshWorkspace, hasSnapshot]);

  const activeConversation = useMemo(
    () => selection?.type === "conversation" ? snapshot?.conversations.find((conversation) => conversation.id === selection.id) || null : null,
    [selection, snapshot],
  );

  const sendMessage = useCallback(async (text: string) => {
    if (!selection) {
      return;
    }
    setSending(true);
    setSendError(undefined);
    try {
      const endpoint = `/api/conversations/${encodeURIComponent(selection.id)}/messages`;
      await fetchJson(endpoint, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text }),
      });
      await refreshWorkspace();
    } catch (caught) {
      setSendError(caught instanceof Error ? caught.message : "无法发送消息");
    } finally {
      setSending(false);
    }
  }, [refreshWorkspace, selection]);

  if (!snapshot && error) {
    return <ErrorPane message={error} onRetry={() => void refreshWorkspace()} retrying={refreshing} />;
  }

  if (!snapshot) {
    return (
      <main className="loading-screen">
        <div className="loading-mark" aria-hidden="true">AT</div>
        <p>正在连接 AgentTeams workspace…</p>
      </main>
    );
  }

  const activeDetail = selection?.type === "conversation" && conversationDetail?.conversation.id === selection.id
    ? conversationDetail
    : null;
  const activeError = conversationError && conversationError.type === selection?.type && conversationError.id === selection?.id
    ? conversationError.message
    : undefined;
  const conversationLoading = Boolean(selection && !activeDetail && !activeError);
  const syncState = snapshot.sync.state;

  return (
    <div className="workspace-app">
      <WorkspaceHeader
        syncState={syncState}
        streamState={streamState}
        onRefresh={() => void refreshWorkspace()}
        refreshing={refreshing}
        filter={feedFilter}
        query={eventQuery}
        onFilterChange={setFeedFilter}
        onQueryChange={setEventQuery}
      />
      {syncState === "degraded" && (
        <div className="sync-banner"><AlertTriangle size={13} /> Matrix/Controller 实时同步处于降级状态，页面继续展示已持久化的真实观测。</div>
      )}
      <div className="workspace-layout">
        <ConversationList snapshot={snapshot} selection={selection} onSelect={(next) => {
          setSelection(next);
          setSendError(undefined);
          setFeedFilter("key");
          setEventQuery("");
        }} />
        {activeConversation ? (
          <ConversationThread
            key={`conversation:${selection?.id || activeConversation.id}`}
            conversation={activeConversation}
            detail={activeDetail}
            loading={conversationLoading}
            sending={sending}
            sendError={sendError || activeError}
            filter={feedFilter}
            query={eventQuery}
            onSend={sendMessage}
          />
        ) : (
          <EmptyConversationPane
            onRefresh={() => void refreshWorkspace()}
            refreshing={refreshing}
          />
        )}
        <ActivityRail
          snapshot={snapshot}
          conversation={activeConversation}
          detail={activeDetail}
          refreshing={refreshing}
          onRefresh={() => void refreshWorkspace()}
        />
      </div>
    </div>
  );
}
