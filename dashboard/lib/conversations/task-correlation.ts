import type { AgentTeamsEvent } from "../types";

type IdentifierKind = "run" | "task";

type Identifier = {
  kind: IdentifierKind;
  value: string;
};

export type TaskCorrelation = {
  eventRunIds: Map<string, string>;
  taskIdsByRun: Map<string, string[]>;
};

const stringValue = (value: unknown): string =>
  typeof value === "string" ? value.trim() : "";

const detailRunId = (event: AgentTeamsEvent): string => {
  const detail = event.detail || {};
  return event.runId
    || stringValue(detail.runId)
    || stringValue(detail.run_id)
    || stringValue(detail.projectId)
    || stringValue(detail.project_id);
};

const detailTaskId = (event: AgentTeamsEvent): string => {
  const detail = event.detail || {};
  return stringValue(detail.taskId) || stringValue(detail.task_id);
};

const relationIds = (event: AgentTeamsEvent): string[] => {
  const detail = event.detail || {};
  return [
    stringValue(detail.threadRootEventId),
    stringValue(detail.relatedEventId),
    stringValue(detail.editedEventId),
  ].filter(Boolean);
};

const eventAliases = (event: AgentTeamsEvent): string[] => [
  event.id,
  event.sourceRef.eventId || "",
  stringValue(event.detail?.eventId),
].filter(Boolean);

const textIdentifiers = (summary: string): Identifier[] => {
  // Values must contain a hyphen so ordinary phrases such as "run the test"
  // cannot accidentally become task boundaries.
  const pattern = /\b(run(?:[\s_-]?id)?|task(?:[\s_-]?id)?|project(?:[\s_-]?id)?)\s*(?:["']\s*)?(?:[:=]\s*|\s+)["']?([A-Za-z0-9][A-Za-z0-9_.:-]*?-[A-Za-z0-9_.:-]+)(?=$|[^A-Za-z0-9_.:-])/gi;
  const identifiers: Identifier[] = [];
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(summary)) !== null) {
    const label = match[1].toLowerCase();
    const value = match[2].replace(/[.:]+$/, "");
    if (!value) {
      continue;
    }
    identifiers.push({
      kind: label.startsWith("task") ? "task" : "run",
      value,
    });
  }
  return identifiers;
};

const unique = (values: string[]): string[] => [...new Set(values.filter(Boolean))];

const exactIdentifierIn = (summary: string, identifier: string): boolean => {
  const escaped = identifier.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(^|[^A-Za-z0-9_-])${escaped}(?=$|[^A-Za-z0-9_-])`, "i").test(summary);
};

const addToSetMap = (map: Map<string, Set<string>>, key: string, value: string): void => {
  const values = map.get(key) || new Set<string>();
  values.add(value);
  map.set(key, values);
};

const uniqueMappedValue = (map: Map<string, Set<string>>, key: string): string | undefined => {
  const values = map.get(key);
  return values?.size === 1 ? [...values][0] : undefined;
};

export const correlateTasks = (events: AgentTeamsEvent[]): TaskCorrelation => {
  const eventRunIds = new Map<string, string>();
  const aliasesToRuns = new Map<string, Set<string>>();
  const taskToRuns = new Map<string, Set<string>>();
  const textByEvent = new Map<string, Identifier[]>();
  const knownRunIds = new Set<string>();
  const eventsByRelationId = new Map<string, AgentTeamsEvent[]>();
  const pendingRelationKeys: string[] = [];

  for (const event of events) {
    for (const relationId of relationIds(event)) {
      const relatedEvents = eventsByRelationId.get(relationId) || [];
      relatedEvents.push(event);
      eventsByRelationId.set(relationId, relatedEvents);
    }
  }

  const registerEventRun = (event: AgentTeamsEvent, runId: string): void => {
    eventRunIds.set(event.id, runId);
    for (const alias of eventAliases(event)) {
      addToSetMap(aliasesToRuns, alias, runId);
    }
    for (const relationId of relationIds(event)) {
      addToSetMap(aliasesToRuns, relationId, runId);
    }
    pendingRelationKeys.push(...eventAliases(event), ...relationIds(event));
  };

  for (const event of events) {
    const runId = detailRunId(event);
    const taskId = detailTaskId(event);
    if (runId) {
      knownRunIds.add(runId);
      registerEventRun(event, runId);
      if (taskId) {
        addToSetMap(taskToRuns, taskId, runId);
      }
    }
    const identifiers = textIdentifiers(event.summary);
    textByEvent.set(event.id, identifiers);
  }

  const resolveTextRun = (event: AgentTeamsEvent, identifiers: Identifier[]): string | undefined => {
    const labeledRuns = unique(unique(identifiers
      .filter((identifier) => identifier.kind === "run")
      .map((identifier) => identifier.value))
      .flatMap((identifier) => {
        const matches = [...knownRunIds].filter((runId) => runId.toLowerCase() === identifier.toLowerCase());
        return matches.length === 1 ? matches : [];
      }));
    if (labeledRuns.length === 1) {
      return labeledRuns[0];
    }

    const exactMatches = [...knownRunIds].filter((runId) => exactIdentifierIn(event.summary, runId));
    return exactMatches.length === 1 ? exactMatches[0] : undefined;
  };

  for (const event of events) {
    if (eventRunIds.has(event.id)) {
      continue;
    }
    const identifiers = textByEvent.get(event.id) || [];
    const textRun = resolveTextRun(event, identifiers);
    if (textRun) {
      registerEventRun(event, textRun);
      continue;
    }
    const taskRuns = unique(identifiers
      .filter((identifier) => identifier.kind === "task")
      .map((identifier) => uniqueMappedValue(taskToRuns, identifier.value) || ""));
    if (taskRuns.length === 1) {
      registerEventRun(event, taskRuns[0]);
    }
  }

  // Thread replies and edits inherit the only unambiguous task boundary of
  // the event they point at. A queue keeps long reply chains linear instead
  // of rescanning the entire event list once per link.
  for (let index = 0; index < pendingRelationKeys.length; index += 1) {
    const relationKey = pendingRelationKeys[index];
    for (const event of eventsByRelationId.get(relationKey) || []) {
      if (eventRunIds.has(event.id)) {
        continue;
      }
      const relatedRuns = unique(relationIds(event)
        .flatMap((relationId) => [...(aliasesToRuns.get(relationId) || [])]));
      if (relatedRuns.length === 1) {
        registerEventRun(event, relatedRuns[0]);
      }
    }
  }

  const taskIdsByRun = new Map<string, string[]>();
  for (const event of events) {
    const runId = eventRunIds.get(event.id);
    if (!runId) {
      continue;
    }
    const taskIds = new Set<string>();
    const detailTask = detailTaskId(event);
    if (detailTask) {
      taskIds.add(detailTask);
    }
    for (const identifier of textByEvent.get(event.id) || []) {
      if (identifier.kind === "task" && uniqueMappedValue(taskToRuns, identifier.value) === runId) {
        taskIds.add(identifier.value);
      }
    }
    if (taskIds.size > 0) {
      taskIdsByRun.set(runId, unique([...(taskIdsByRun.get(runId) || []), ...taskIds]).sort());
    }
  }

  return { eventRunIds, taskIdsByRun };
};

export const taskRunIdFor = (event: AgentTeamsEvent, correlation: TaskCorrelation): string | undefined =>
  correlation.eventRunIds.get(event.id)
  || (event.sourceRef.eventId ? correlation.eventRunIds.get(event.sourceRef.eventId) : undefined);
