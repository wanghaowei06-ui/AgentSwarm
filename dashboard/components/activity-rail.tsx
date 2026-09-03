"use client";

import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  CircleDot,
  RefreshCw,
  Server,
  ShieldCheck,
  Sparkles,
  Terminal,
  Users,
} from "lucide-react";
import type {
  AttentionItem,
  ConversationDetail,
  ConversationRoom,
  ConversationSummary,
  EvidenceCategory,
  JsonObject,
  WorkspaceSnapshot,
} from "../lib/types";
import {
  approvalState,
  eventEvidenceCategory,
  latestPhaseReports,
  phaseReportInfo,
  isPriorityEvidence,
} from "../lib/events/evidence";
import { actorDisplayName } from "../lib/ui/actor";

type ActivityRailProps = {
  snapshot: WorkspaceSnapshot;
  conversation: ConversationSummary | null;
  detail: ConversationDetail | null;
  refreshing: boolean;
  onRefresh: () => void;
};

const attentionLabel = (item: AttentionItem): string => {
  if (item.severity === "error") {
    return "需要处理";
  }
  if (item.severity === "warning") {
    return "需要关注";
  }
  return "信息";
};

const controllerSources = (data?: JsonObject): string[] =>
  data ? Object.keys(data).sort() : [];

const evidenceLabels: Record<EvidenceCategory, string> = {
  collaboration: "Agent 协作",
  skill: "Skill 调用",
  tool: "工具调用",
  exception: "异常证据",
  approval: "人工审批",
  artifact: "产物",
  message: "消息",
  system: "系统",
};

const roomRoleLabels: Record<ConversationRoom["role"], string> = {
  manager: "Manager",
  team: "Team",
  leader: "Leader DM",
  worker: "Worker",
  project: "项目房间",
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

const evidenceIcon = (category: EvidenceCategory) => {
  if (category === "exception") {
    return <AlertTriangle size={11} />;
  }
  if (category === "skill") {
    return <Sparkles size={11} />;
  }
  if (category === "tool") {
    return <Terminal size={11} />;
  }
  if (category === "approval") {
    return <ShieldCheck size={11} />;
  }
  return <CircleDot size={11} />;
};

const roomRoleLabel = (room: ConversationRoom): string => {
  if (room.role === "worker" && room.agentName) {
    return `${roomRoleLabels[room.role]} · ${room.agentName}`;
  }
  if (room.role === "team" && room.teamName) {
    return `${roomRoleLabels[room.role]} · ${room.teamName}`;
  }
  if (room.role === "leader" && room.agentName) {
    return `${roomRoleLabels[room.role]} · ${room.agentName}`;
  }
  return roomRoleLabels[room.role];
};

const collectionCount = (value: unknown): number | undefined => {
  if (Array.isArray(value)) {
    return value.length;
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return undefined;
  }
  for (const key of ["workers", "items", "results"]) {
    const collection = (value as JsonObject)[key];
    if (Array.isArray(collection)) {
      return collection.length;
    }
  }
  return undefined;
};

export function ActivityRail({ snapshot, conversation, detail, refreshing, onRefresh }: ActivityRailProps) {
  const events = detail?.observations || [];
  const attention = detail?.attention || [];
  const rooms = detail?.rooms || conversation?.rooms || [];
  const summary = detail?.conversation || conversation;
  const evidence = detail?.evidence || events.filter(isPriorityEvidence);
  const progressReports = latestPhaseReports(events);
  const approvalEvidence = events
    .filter((event) => eventEvidenceCategory(event) === "approval")
    .sort((left, right) => right.occurredAt.localeCompare(left.occurredAt));
  const approvalSourceIds = new Set(approvalEvidence.flatMap((event) => [event.id, event.sourceRef.eventId].filter((value): value is string => Boolean(value))));
  const exceptionAttention = attention.filter((item) => !item.sourceEventId || !approvalSourceIds.has(item.sourceEventId));
  const priorityEvidence = [...evidence]
    .filter((event) => eventEvidenceCategory(event) !== "approval")
    .sort((left, right) => right.occurredAt.localeCompare(left.occurredAt))
    .slice(0, 6);
  const messages = summary?.messageCount ?? events.filter((event) => event.kind === "message").length;
  const tools = summary?.toolCount ?? events.filter((event) => event.kind === "tool").length;
  const skills = summary?.skillCount ?? events.filter((event) => event.kind === "skill").length;
  const collaboration = summary?.collaborationCount ?? events.filter((event) => eventEvidenceCategory(event) === "collaboration").length;
  const exceptions = summary?.exceptionCount ?? events.filter((event) => eventEvidenceCategory(event) === "exception").length;
  const approvals = summary?.approvalCount ?? approvalEvidence.length;
  const artifacts = detail?.artifacts.length || events.filter((event) => event.kind === "artifact").length;
  const controllerKeys = controllerSources(snapshot.controller.data);
  const agentCount = summary?.agentCount ?? collectionCount(snapshot.controller.data?.["/api/v1/workers"]);
  const eventCount = summary?.eventCount ?? events.length;

  return (
    <aside className="inspector" aria-label="Conversation evidence and observability" tabIndex={0}>
      <section className="inspector-section">
        <div className="inspector-title-row">
          <div>
            <p className="eyebrow">Evidence rail</p>
            <h2 className="section-title">链路证据</h2>
          </div>
          <button className="refresh-button" type="button" onClick={onRefresh} disabled={refreshing}>
            <RefreshCw size={12} className={refreshing ? "spin-icon" : undefined} />
            刷新
          </button>
        </div>
        <div className="stat-grid">
          <div className="stat-card">
            <span className="stat-label"><Activity size={11} /> events</span>
            <strong className="stat-value">{eventCount}</strong>
          </div>
          <div className="stat-card">
            <span className="stat-label"><Users size={11} /> messages</span>
            <strong className="stat-value teal">{messages}</strong>
          </div>
          <div className="stat-card">
            <span className="stat-label"><Users size={11} /> agents</span>
            <strong className="stat-value teal">{agentCount ?? "—"}</strong>
          </div>
          <div className="stat-card">
            <span className="stat-label"><CircleDot size={11} /> rooms</span>
            <strong className="stat-value">{rooms.length}</strong>
          </div>
          <div className="stat-card">
            <span className="stat-label"><Sparkles size={11} /> skills</span>
            <strong className="stat-value orange">{skills}</strong>
          </div>
          <div className="stat-card">
            <span className="stat-label"><AlertTriangle size={11} /> exceptions</span>
            <strong className="stat-value red">{exceptions}</strong>
          </div>
          <div className="stat-card approval-stat">
            <span className="stat-label"><ShieldCheck size={11} /> approvals</span>
            <strong className="stat-value approval-value">{approvals}</strong>
          </div>
        </div>
        <div className="evidence-count-line">
          <span><CircleDot size={11} /> {collaboration} collaboration</span>
          <span><Terminal size={11} /> {tools} tools</span>
          <span><ShieldCheck size={11} /> {approvals} approvals</span>
          <span>{artifacts} artifacts</span>
        </div>
      </section>

      {progressReports.length > 0 && (
        <section className="inspector-section">
          <div className="inspector-title-row">
            <div>
              <p className="eyebrow">Live progress</p>
              <h2 className="section-title">执行进度</h2>
            </div>
            <span className="mono-label">{progressReports.length} latest</span>
          </div>
          <div className="rail-progress-list">
            {progressReports.map((event) => {
              const report = phaseReportInfo(event);
              if (!report) {
                return null;
              }
              return (
                <article className="rail-progress" key={event.id}>
                  <div className="rail-evidence-head">
                    <span className="evidence-category collaboration"><Activity size={11} /> Phase report</span>
                    <time>{report.reportedAt || formatDate(event.occurredAt)}</time>
                  </div>
                  <strong title={report.headline}>{report.headline}</strong>
                  <div className="rail-evidence-meta">
                    <span title={report.runLabel}>{report.runLabel}</span>
                    <span title={actorDisplayName(event)}>{actorDisplayName(event)}</span>
                  </div>
                  {report.highlights.length > 0 && (
                    <ul className="rail-progress-highlights">
                      {report.highlights.map((highlight) => <li key={`${event.id}:${highlight}`}>{highlight}</li>)}
                    </ul>
                  )}
                </article>
              );
            })}
          </div>
        </section>
      )}

      <section className="inspector-section">
        <div className="inspector-title-row">
          <div>
            <p className="eyebrow">Exception handling</p>
            <h2 className="section-title">异常处理证据</h2>
          </div>
          <span className="mono-label">{exceptionAttention.length} items</span>
        </div>
        {exceptionAttention.length > 0 ? (
          <div className="attention-list">
            {exceptionAttention.slice(0, 5).map((item) => (
              <div className={`attention-item ${item.severity}`} key={item.id}>
                <span className="attention-icon">
                  {item.severity === "error" ? <AlertTriangle size={14} /> : <Activity size={14} />}
                </span>
                <div className="attention-copy">
                  <strong>{item.summary}</strong>
                  <span>{attentionLabel(item)}{item.sourceEventId ? ` · ${item.sourceEventId}` : ""}</span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="muted-copy">当前会话没有失败或等待中的观测。</div>
          )}
      </section>

      <section className="inspector-section">
        <div className="inspector-title-row">
          <div>
            <p className="eyebrow">Human in the loop</p>
            <h2 className="section-title">人工审批证据</h2>
          </div>
          <span className="mono-label">{approvals} records</span>
        </div>
        {approvalEvidence.length > 0 ? (
          <div className="approval-list">
            {approvalEvidence.slice(0, 5).map((event) => {
              const state = approvalState(event) || "unknown";
              const stateLabel = state === "pending" ? "待审批" : state === "approved" ? "已批准" : state === "rejected" ? "已拒绝" : "已记录";
              const sourceId = event.sourceRef.eventId || event.id;
              return (
                <article className={`approval-item ${statusClass(state)}`} key={event.id}>
                  <div className="rail-evidence-head">
                    <span className="evidence-category approval"><ShieldCheck size={11} /> {stateLabel}</span>
                    <time>{formatDate(event.occurredAt)}</time>
                  </div>
                  <strong title={event.summary}>{event.summary}</strong>
                  <div className="rail-evidence-meta">
                    <span title={actorDisplayName(event)}>{actorDisplayName(event)}</span>
                    <span title={event.roomId}>{rooms.find((room) => room.roomId === event.roomId)?.label || "unassigned room"}</span>
                    <span title={sourceId}>{sourceId}</span>
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <div className="muted-copy">当前会话没有检测到明确的人工审批记录。</div>
        )}
      </section>

      <section className="inspector-section">
        <div className="inspector-title-row">
          <div>
            <p className="eyebrow">Priority evidence</p>
            <h2 className="section-title">关键链路</h2>
          </div>
          <span className="mono-label">{evidence.length} records</span>
        </div>
        {priorityEvidence.length > 0 ? (
          <div className="rail-evidence-list">
            {priorityEvidence.map((event) => {
              const category = eventEvidenceCategory(event);
              const sourceId = event.sourceRef.eventId || event.id;
              return (
                <article className={`rail-evidence ${statusClass(category)}`} key={event.id}>
                  <div className="rail-evidence-head">
                    <span className={`evidence-category ${statusClass(category)}`}>
                      {evidenceIcon(category)} {evidenceLabels[category]}
                    </span>
                    <time>{formatDate(event.occurredAt)}</time>
                  </div>
                  <strong title={event.summary}>{event.summary}</strong>
                  <div className="rail-evidence-meta">
                    <span title={actorDisplayName(event)}>{actorDisplayName(event)}</span>
                    <span title={event.roomId}>{rooms.find((room) => room.roomId === event.roomId)?.label || "unassigned room"}</span>
                    <span title={sourceId}>{sourceId}</span>
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <div className="muted-copy">当前会话尚未收到 Agent 协作、Skill、工具或异常证据。</div>
        )}
      </section>

      <section className="inspector-section">
        <div className="inspector-title-row">
          <div>
            <p className="eyebrow">Room scope</p>
            <h2 className="section-title">关联协作 rooms</h2>
          </div>
          <span className="mono-label">{rooms.length} rooms</span>
        </div>
        {rooms.length > 0 ? (
          <div className="rail-room-list">
            {rooms.map((room) => (
              <div className="rail-room" key={room.roomId}>
                <span className="rail-room-icon"><CircleDot size={11} /></span>
                <div className="rail-room-copy">
                  <strong title={room.label}>{room.label}</strong>
                  <span>{roomRoleLabel(room)} · {room.eventCount} events · {room.messageCount} messages</span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="muted-copy">读取 Controller room 关系后，关联 Team、Leader 和 Worker 会显示在这里。</div>
        )}
      </section>

      <section className="inspector-section">
        <div className="inspector-title-row">
          <div>
            <p className="eyebrow">Sources</p>
            <h2 className="section-title">实时数据源</h2>
          </div>
          {snapshot.controller.state === "live" ? <CheckCircle2 size={14} color="var(--teal)" /> : <AlertTriangle size={14} color="var(--yellow)" />}
        </div>
        <div className="source-list">
          <div className="source-row"><span><Server size={12} /> Matrix sync</span><span>{snapshot.sync.state}</span></div>
          <div className="source-row"><span><Server size={12} /> Controller</span><span>{snapshot.controller.state}</span></div>
          <div className="source-row"><span><CircleDot size={12} /> event store</span><span>{eventCount} observed</span></div>
          {controllerKeys.slice(0, 4).map((key) => (
            <div className="source-row" key={key}><span>{key.replace("/api/v1/", "")}</span><span>received</span></div>
          ))}
        </div>
        {snapshot.sync.lastError && <p className="composer-error">{snapshot.sync.lastError}</p>}
        {!snapshot.capabilities.traceQuery && <p className="muted-copy">Trace 查询等待上游 API 暴露稳定的 trace contract；当前链路证据来自 Matrix timeline 与 Controller snapshot。</p>}
      </section>
    </aside>
  );
}
