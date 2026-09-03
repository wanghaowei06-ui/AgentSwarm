"use client";

import { useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  Clock3,
  FileOutput,
  GitBranch,
  LoaderCircle,
  Search,
  Send,
  Sparkles,
  Terminal,
  UserRound,
} from "lucide-react";
import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  useExternalStoreRuntime,
  type AppendMessage,
  type ExternalStoreAdapter,
} from "@assistant-ui/react";
import type { AgentTeamsEvent, JsonObject, RunDetail, RunStatus, RunSummary } from "../lib/types";
import { actorDisplayName, actorRoleLabel } from "../lib/ui/actor";
import { toThreadMessageLike } from "../lib/ui/thread-message";

type ChatEvent = AgentTeamsEvent & { kind: "message" };

type RunThreadProps = {
  run: RunSummary;
  detail: RunDetail | null;
  loading: boolean;
  sending: boolean;
  sendError?: string;
  onSend: (text: string) => Promise<void>;
};

const isObject = (value: unknown): value is JsonObject =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const textValue = (value: unknown): string =>
  typeof value === "string" ? value.trim() : "";

const displayValue = (value: unknown): string => {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value, null, 2) || "—";
  } catch {
    return "[无法显示]";
  }
};

const statusClass = (status: string): string =>
  status.toLowerCase().replace(/[^a-z0-9_-]/g, "-");

const statusLabel: Record<RunStatus, string> = {
  queued: "queued",
  running: "running",
  waiting: "waiting",
  done: "done",
  failed: "failed",
  unknown: "unknown",
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

export const extractText = (message: AppendMessage): string => {
  return message.content
    .filter((part): part is { type: "text"; text: string } => part.type === "text")
    .map((part) => part.text)
    .join("")
    .trim();
};

function EventMeta({ event }: { event: AgentTeamsEvent }) {
  const source = event.source === "matrix" ? "Matrix" : "Controller";
  const sourceId = event.sourceRef.eventId || event.sourceRef.endpoint || event.id;
  return (
    <div className="event-meta">
      <span>{formatDate(event.occurredAt)}</span>
      <span>·</span>
      <span className="event-source" title={sourceId}>
        {source}
        <span>{sourceId}</span>
      </span>
    </div>
  );
}

function MessageEvent({ event }: { event: AgentTeamsEvent }) {
  const human = event.actor?.role === "human";
  const label = actorDisplayName(event);
  const role = event.actor?.role || "unknown";
  return (
    <div className={`event-row ${human ? "human" : "agent"}`}>
      <div className="event-avatar" aria-hidden="true">
        {human ? <UserRound size={14} /> : <Bot size={14} />}
      </div>
      <div className="event-content">
        <div className="message-bubble">
          <div className="event-author">
            <span>{label}</span>
            <span className={`actor-role ${statusClass(role)}`}>{actorRoleLabel[role]}</span>
          </div>
          <p className="event-text">{event.summary}</p>
        </div>
        <EventMeta event={event} />
      </div>
    </div>
  );
}

function WorkflowEvent({ event }: { event: AgentTeamsEvent }) {
  const detail = event.detail || {};
  const steps = Array.isArray(detail.steps) ? detail.steps.filter(isObject) : [];
  const status = textValue(detail.status) || "observed";
  return (
    <div className="event-row">
      <div className="event-avatar" aria-hidden="true"><GitBranch size={14} /></div>
      <div className="event-content">
        <div className="workflow-event">
          <div className="event-kind"><GitBranch size={12} /> Workflow update</div>
          <p className="event-card-title">{event.summary}</p>
          <p className="event-card-copy">
            {textValue(detail.ownerRole) ? `Owner · ${textValue(detail.ownerRole)}` : "AgentTeams orchestration event"}
            {` · ${status}`}
          </p>
          {steps.length > 0 && (
            <div className="workflow-progress">
              {steps.map((step, index) => {
                const stepStatus = textValue(step.status) || "unknown";
                return (
                  <div className="workflow-step" key={`${event.id}:step:${textValue(step.id) || index}`}>
                    <span className="workflow-step-label">
                      {textValue(step.title) || textValue(step.label) || textValue(step.name) || `Step ${index + 1}`}
                    </span>
                    <span className={`workflow-step-status ${statusClass(stepStatus)}`}>{stepStatus}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
        <EventMeta event={event} />
      </div>
    </div>
  );
}

function ToolEvent({ event }: { event: AgentTeamsEvent }) {
  const detail = event.detail || {};
  const name = textValue(detail.name) || "tool";
  const status = textValue(detail.status) || "observed";
  const payload = detail.args ?? detail.arguments ?? detail.result ?? detail.output ?? detail.error;
  const skill = event.kind === "skill";
  return (
    <div className="event-row">
      <div className="event-avatar" aria-hidden="true"><Terminal size={14} /></div>
      <div className="event-content">
        <div className={`tool-event ${skill ? "skill-event" : ""}`}>
          <div className="event-kind">{skill ? <Sparkles size={12} /> : <Terminal size={12} />} {skill ? "Skill invocation" : "Tool call"}</div>
          <div className="tool-header">
            <span className="tool-name">{name}</span>
            <span className={`tool-status ${statusClass(status)}`}>{status}</span>
          </div>
          {payload !== undefined && (
            <details className="tool-detail">
              <summary>查看已脱敏 payload</summary>
              <pre className="tool-payload">{displayValue(payload)}</pre>
            </details>
          )}
          <div className="tool-footer">
            <span>{textValue(detail.phase) || "runtime observation"}</span>
            {textValue(detail.callId) && <span>{textValue(detail.callId)}</span>}
          </div>
        </div>
        <EventMeta event={event} />
      </div>
    </div>
  );
}

function ArtifactEvent({ event }: { event: AgentTeamsEvent }) {
  const detail = event.detail || {};
  const mxc = textValue(detail.mxc);
  const mediaHref = mxc ? `/api/matrix/media?mxc=${encodeURIComponent(mxc)}` : undefined;
  return (
    <div className="event-row">
      <div className="event-avatar" aria-hidden="true"><FileOutput size={14} /></div>
      <div className="event-content">
        <div className="artifact-event">
          <div className="event-kind"><FileOutput size={12} /> Artifact</div>
          <div className="artifact-header">
            <span className="artifact-name">{textValue(detail.filename) || event.summary}</span>
            <span className="mono-label">{textValue(detail.mimetype) || "binary"}</span>
          </div>
          <div className="artifact-detail">
            {typeof detail.size === "number" && <span>{Math.ceil(detail.size / 1024)} KB</span>}
            {mediaHref ? (
              <a className="artifact-link" href={mediaHref} target="_blank" rel="noreferrer">打开真实附件</a>
            ) : (
              <span>暂无可下载地址</span>
            )}
          </div>
        </div>
        <EventMeta event={event} />
      </div>
    </div>
  );
}

function SystemEvent({ event }: { event: AgentTeamsEvent }) {
  const degraded = /degraded|unavailable|error|failed/i.test(event.summary);
  return (
    <div className="event-row">
      <div className="event-avatar" aria-hidden="true"><Activity size={14} /></div>
      <div className="event-content">
        <div className="system-event">
          <div className="event-kind">
            {degraded ? <AlertTriangle size={12} /> : <Activity size={12} />}
            System observation
          </div>
          <p className="event-text">{event.summary}</p>
        </div>
        <EventMeta event={event} />
      </div>
    </div>
  );
}

export function EventItem({ event }: { event: AgentTeamsEvent }) {
  if (event.kind === "message") {
    return <MessageEvent event={event} />;
  }
  if (event.kind === "workflow") {
    return <WorkflowEvent event={event} />;
  }
  if (event.kind === "tool") {
    return <ToolEvent event={event} />;
  }
  if (event.kind === "skill") {
    return <ToolEvent event={event} />;
  }
  if (event.kind === "artifact") {
    return <ArtifactEvent event={event} />;
  }
  return <SystemEvent event={event} />;
}

export function RunThread({ run, detail, loading, sending, sendError, onSend }: RunThreadProps) {
  const [query, setQuery] = useState("");
  const chatEvents = useMemo<ChatEvent[]>(
    () => (detail?.messages || []).filter((event): event is ChatEvent => event.kind === "message"),
    [detail?.messages],
  );
  const adapter = useMemo<ExternalStoreAdapter<ChatEvent>>(() => ({
    messages: chatEvents,
    isLoading: loading,
    isRunning: sending,
    isSendDisabled: sending || !run.roomId,
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
  }), [chatEvents, loading, onSend, run.roomId, sending]);
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
      event.sourceRef.endpoint,
      event.kind,
      event.detail?.name,
      event.detail?.status,
    ].some((value) => typeof value === "string" && value.toLowerCase().includes(normalizedQuery)));
  }, [observations, query]);
  const hasRoom = Boolean(run.roomId);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <section className="thread-pane" aria-label="AgentTeams conversation">
        <header className="thread-header">
          <div>
            <div className="thread-title-line">
              <h1 className="thread-title">{run.title}</h1>
              <span className={`status-badge ${statusClass(run.status)}`}>{statusLabel[run.status]}</span>
            </div>
            <p className="thread-subtitle">{run.summary || "等待新的 AgentTeams 观测事件"}</p>
          </div>
          <div className="thread-header-meta">
            <span className="thread-room" title={run.roomId || undefined}>{run.roomId || "no room bound"}</span>
            <span className="mono-label">{run.completedStepCount}/{run.stepCount || 0} steps complete</span>
          </div>
        </header>

        <div className="thread-tools">
          <label className="thread-filter">
            <Search size={13} />
            <span className="sr-only">筛选当前事件</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="筛选消息、工具或事件 ID…"
              type="search"
            />
          </label>
          <span className="mono-label">{filteredObservations.length}/{observations.length} observed</span>
        </div>

        <div className="event-scroll">
          <div className="event-list">
            {loading && (
              <div className="empty-state">
                <LoaderCircle className="spin-icon" size={24} />
                <p className="empty-state-title">正在读取真实事件流</p>
                <p className="empty-state-copy">页面正在从本地持久化投影读取这个 run 的 Matrix 与 Controller 观测。</p>
              </div>
            )}
            {!loading && observations.length === 0 && (
              <div className="empty-state">
                <Clock3 size={24} className="empty-state-icon" />
                <p className="empty-state-title">还没有观测记录</p>
                <p className="empty-state-copy">这个 run 尚未产生可展示的消息、工作流、工具或系统事件。</p>
              </div>
            )}
            {!loading && observations.length > 0 && filteredObservations.length === 0 && (
              <div className="empty-state">
                <Search size={24} className="empty-state-icon" />
                <p className="empty-state-title">没有匹配的事件</p>
                <p className="empty-state-copy">换一个关键词，或清空筛选以查看这个 run 的完整观测。</p>
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
                placeholder={hasRoom ? "向当前 AgentTeam 发送消息…" : "当前 run 没有绑定 Matrix 房间"}
                submitMode="ctrlEnter"
                disabled={!hasRoom}
                aria-label="Message the current AgentTeam"
              />
              <div className="composer-footer">
                <div className="composer-hints">
                  <kbd>⌘ / Ctrl</kbd>
                  <span>+ Enter 发送到 Matrix</span>
                </div>
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

export function RunStatusIcon({ status }: { status: RunStatus }) {
  if (status === "done") {
    return <CheckCircle2 size={13} />;
  }
  if (status === "failed") {
    return <AlertTriangle size={13} />;
  }
  if (status === "running") {
    return <LoaderCircle size={13} className="spin-icon" />;
  }
  return <Clock3 size={13} />;
}
