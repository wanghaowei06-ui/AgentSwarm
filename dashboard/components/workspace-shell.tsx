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
import type { ConversationDetail, ConversationSummary, DashboardProject, WorkspaceSnapshot } from "../lib/types";
import { conversationSourceLabels, feedFilterLabels, workspaceNavigationItems, type FeedFilter } from "../lib/ui/navigation";
import { ActivityRail } from "./activity-rail";
import { ConversationThread } from "./conversation-thread";
import { ProjectCreateDialog, type ProjectCreateValues } from "./project-create-dialog";

type Selection = {
  type: "conversation" | "project";
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

const projectStatusLabels: Record<NonNullable<ConversationSummary["projectStatus"]>, string> = {
  provisioning: "创建中",
  active: "运行中",
  failed: "创建失败",
};

function ConversationEntry({
  item,
  selection,
  onSelect,
}: {
  item: ConversationSummary;
  selection?: Selection;
  onSelect: (selection: Selection) => void;
}) {
  const type = item.source === "dashboard-project" ? "project" : "conversation";
  const active = selection?.type === type && item.id === selection.id;
  const isProject = type === "project";
  const isTask = type === "conversation" && Boolean(item.runId);
  return (
    <div className={`conversation-entry ${active ? "active" : ""}`}>
      <button
        className="conversation-item"
        type="button"
        onClick={() => onSelect({ type, id: item.id })}
      >
        <span className={`run-item-indicator ${item.status}`} aria-hidden="true" />
        <span className="run-item-body">
          <span className="run-item-title">
            <span>{isProject ? <Sparkles size={13} /> : isTask ? <CircleDot size={13} /> : <Bot size={13} />}{item.title}</span>
            <span className="run-item-time">{formatRunTime(item.latestAt)}</span>
          </span>
          <span className="run-item-meta">
            <span>{isTask ? "task" : isProject ? "project" : "Manager"}</span>
            <span>·</span>
            <span>{item.agentCount} agents</span>
            <span>·</span>
            <span>{item.roomCount} rooms</span>
            {isProject && item.projectStatus && <span>· {projectStatusLabels[item.projectStatus]}</span>}
            {item.exceptionCount > 0 && <span className="run-badge attention">· {item.exceptionCount} alert</span>}
            {item.approvalCount > 0 && <span className="run-badge approval">· {item.approvalCount} approval</span>}
          </span>
          <span className="run-item-summary">{item.summary}</span>
        </span>
      </button>
      {active && item.rooms.length > 0 && (
        <div className="conversation-room-scope">
          <span className="scope-label">关联房间</span>
          {item.rooms.slice(0, 4).map((room) => (
            <span className="scope-room" key={room.roomId} title={room.roomId}>
              <CircleDot size={10} />
              <span>{room.label}</span>
            </span>
          ))}
          {item.rooms.length > 4 && <span className="scope-more">+{item.rooms.length - 4} 个房间</span>}
        </div>
      )}
    </div>
  );
}

function ConversationList({
  snapshot,
  selection,
  onSelect,
  onCreateProject,
  onCreateManagerDm,
  creatingProject,
  creationError,
}: {
  snapshot: WorkspaceSnapshot;
  selection?: Selection;
  onSelect: (selection: Selection) => void;
  onCreateProject: () => void;
  onCreateManagerDm: () => void;
  creatingProject: boolean;
  creationError?: string;
}) {
  return (
    <aside className="sidebar" aria-label="项目、任务与 Manager 对话" tabIndex={0}>
      <div className="sidebar-heading">
        <div className="sidebar-heading-top">
          <div>
            <p className="eyebrow">Workspace inbox</p>
            <h2 className="page-title">项目、任务与私聊</h2>
          </div>
          <span className="inbox-count">{snapshot.projects.length + snapshot.conversations.length}</span>
        </div>
        <p className="sidebar-copy">按项目或任务查看 Manager 与协作房间。</p>
        <div className="inbox-actions">
          <button className="inbox-action primary" type="button" onClick={onCreateProject} disabled={creatingProject}>
            <Sparkles size={12} /> 新建项目
          </button>
          <button className="inbox-action" type="button" onClick={onCreateManagerDm} disabled={creatingProject}>
            <Bot size={12} /> Manager 私聊
          </button>
        </div>
        {creationError && <p className="sidebar-action-error">{creationError}</p>}
      </div>
      <div className="conversation-list">
        {snapshot.projects.length > 0 && (
          <section className="inbox-section">
            <div className="inbox-section-heading">
              <p className="run-list-label">{conversationSourceLabels["dashboard-project"]}</p>
              <span>{snapshot.projects.length}</span>
            </div>
            {snapshot.projects.map((item) => <ConversationEntry item={item} selection={selection} onSelect={onSelect} key={item.id} />)}
          </section>
        )}
        <section className="inbox-section">
          <div className="inbox-section-heading">
            <p className="run-list-label">{conversationSourceLabels.controller}</p>
            <span>{conversationCountLabel(snapshot.conversations)}</span>
          </div>
          {snapshot.conversations.length > 0 ? snapshot.conversations.map((item) => (
            <ConversationEntry item={item} selection={selection} onSelect={onSelect} key={item.id} />
          )) : (
            <div className="empty-state compact-empty">
              <Inbox size={20} />
              <p className="empty-state-title">等待 Manager 会话或任务</p>
              <p className="empty-state-copy">Controller 暴露 Manager room 后，真实对话会出现在这里。</p>
            </div>
          )}
        </section>
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
  const [projectDialogOpen, setProjectDialogOpen] = useState(false);
  const [creatingProject, setCreatingProject] = useState(false);
  const [creationError, setCreationError] = useState<string>();
  const hasSnapshot = snapshot !== null;

  const refreshWorkspace = useCallback(async (preferredSelection?: Selection) => {
    setRefreshing(true);
    try {
      const next = await fetchJson<WorkspaceSnapshot>("/api/workspace");
      setSnapshot(next);
      setError(undefined);
      setStreamState(next.sync.state === "degraded" ? "degraded" : "live");
      setSelection((current) => {
        if (preferredSelection && (
          preferredSelection.type === "project"
            ? next.projects.some((project) => project.id === preferredSelection.id)
            : next.conversations.some((conversation) => conversation.id === preferredSelection.id)
        )) {
          return preferredSelection;
        }
        if (current?.type === "conversation" && next.conversations.some((conversation) => conversation.id === current.id)) {
          return current;
        }
        if (current?.type === "project" && next.projects.some((project) => project.id === current.id)) {
          return current;
        }
        return next.conversations[0]
          ? { type: "conversation", id: next.conversations[0].id }
          : next.projects[0]
            ? { type: "project", id: next.projects[0].id }
            : undefined;
      });
      setRevision((value) => value + 1);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法读取 workspace");
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void Promise.resolve().then(() => refreshWorkspace());
  }, [refreshWorkspace]);

  useEffect(() => {
    if (!selection) {
      return;
    }
    let cancelled = false;
    const resource = selection.type === "project" ? "projects" : "conversations";
    const endpoint = `/api/${resource}/${encodeURIComponent(selection.id)}`;
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
    eventSource.addEventListener("project.updated", refreshFromEvent);
    return () => eventSource.close();
  }, [refreshWorkspace, hasSnapshot]);

  const activeConversation = useMemo(
    () => selection?.type === "project"
      ? snapshot?.projects.find((project) => project.id === selection.id) || null
      : snapshot?.conversations.find((conversation) => conversation.id === selection?.id) || null,
    [selection, snapshot],
  );

  const sendMessage = useCallback(async (text: string) => {
    if (!selection) {
      return;
    }
    setSending(true);
    setSendError(undefined);
    try {
      const resource = selection.type === "project" ? "projects" : "conversations";
      const endpoint = `/api/${resource}/${encodeURIComponent(selection.id)}/messages`;
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

  const createManagerDm = useCallback(async () => {
    if (creatingProject) {
      return;
    }
    setCreatingProject(true);
    setCreationError(undefined);
    try {
      const result = await fetchJson<{ project: DashboardProject }>("/api/projects", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ kind: "manager-dm" }),
      });
      await refreshWorkspace({ type: "project", id: result.project.id });
    } catch (caught) {
      setCreationError(caught instanceof Error ? caught.message : "无法创建 Manager 私聊");
    } finally {
      setCreatingProject(false);
    }
  }, [creatingProject, refreshWorkspace]);

  const createProject = useCallback(async (values: ProjectCreateValues) => {
    if (creatingProject) {
      return;
    }
    setCreatingProject(true);
    setCreationError(undefined);
    try {
      const result = await fetchJson<{ project: DashboardProject }>("/api/projects", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ kind: "project", ...values }),
      });
      setProjectDialogOpen(false);
      await refreshWorkspace({ type: "project", id: result.project.id });
    } catch (caught) {
      setCreationError(caught instanceof Error ? caught.message : "无法创建项目");
    } finally {
      setCreatingProject(false);
    }
  }, [creatingProject, refreshWorkspace]);

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

  const activeDetail = conversationDetail
    && conversationDetail.conversation.id === selection?.id
    && ((selection.type === "project" && conversationDetail.conversation.source === "dashboard-project")
      || (selection.type === "conversation" && conversationDetail.conversation.source === "controller"))
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
          setCreationError(undefined);
          setFeedFilter("key");
          setEventQuery("");
        }} onCreateProject={() => {
          setCreationError(undefined);
          setProjectDialogOpen(true);
        }} onCreateManagerDm={() => void createManagerDm()} creatingProject={creatingProject} creationError={creationError} />
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
      {projectDialogOpen && (
        <ProjectCreateDialog
          participants={snapshot.participants}
          submitting={creatingProject}
          error={creationError}
          onClose={() => {
            if (!creatingProject) {
              setProjectDialogOpen(false);
              setCreationError(undefined);
            }
          }}
          onSubmit={(values) => void createProject(values)}
        />
      )}
    </div>
  );
}
