-- PostgreSQL-compatible append-only TestWeaver authority tables.
-- Payload columns contain canonical metadata/ref JSON only, no prompt or body.

CREATE TABLE IF NOT EXISTS tw_authority_events (
    event_id TEXT PRIMARY KEY,
    aggregate_id TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    run_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    provenance TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    UNIQUE (aggregate_id, revision),
    UNIQUE (idempotency_key)
);

CREATE INDEX IF NOT EXISTS ix_tw_authority_events_run
    ON tw_authority_events (run_id, campaign_id, trace_id, revision);

CREATE TABLE IF NOT EXISTS tw_capsules (
    record_key TEXT PRIMARY KEY,
    capsule_id TEXT NOT NULL,
    capsule_type TEXT NOT NULL,
    state TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    fault_owner TEXT NOT NULL,
    target_fault_domains_json TEXT NOT NULL,
    observation_ref TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    baseline_strategy TEXT NOT NULL,
    observed_strategy TEXT NOT NULL,
    root_cause_ref TEXT,
    repair_ref TEXT,
    regression_refs_json TEXT NOT NULL,
    artifact_ref TEXT NOT NULL,
    artifact_hash TEXT NOT NULL,
    run_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    provenance TEXT NOT NULL,
    content_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_tw_capsules_fingerprint
    ON tw_capsules (fingerprint, capsule_type, revision);

CREATE TABLE IF NOT EXISTS tw_capsule_hits (
    hit_id TEXT PRIMARY KEY,
    capsule_id TEXT NOT NULL,
    capsule_revision INTEGER NOT NULL CHECK (capsule_revision > 0),
    capsule_content_hash TEXT NOT NULL,
    matched_fingerprint TEXT NOT NULL,
    recurrence BOOLEAN NOT NULL,
    evidence_ref TEXT NOT NULL,
    run_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    provenance TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    UNIQUE (capsule_id, run_id, trace_id)
);

CREATE TABLE IF NOT EXISTS tw_hitl_events (
    event_id TEXT PRIMARY KEY,
    approval_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    decision TEXT,
    run_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    previous_revision INTEGER,
    matrix_event_ref TEXT NOT NULL,
    matrix_event_hash TEXT NOT NULL,
    verification_ref TEXT,
    verification_hash TEXT,
    sender TEXT NOT NULL,
    identity_ref TEXT NOT NULL,
    actor_kind TEXT NOT NULL,
    policy_ref TEXT NOT NULL,
    reason_ref TEXT,
    occurred_at TEXT NOT NULL,
    provenance TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    UNIQUE (approval_id, revision)
);

CREATE INDEX IF NOT EXISTS ix_tw_hitl_run
    ON tw_hitl_events (run_id, campaign_id, trace_id, revision);

CREATE TABLE IF NOT EXISTS tw_oracle_results (
    result_id TEXT PRIMARY KEY,
    oracle_kind TEXT NOT NULL,
    run_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    identity_ref TEXT NOT NULL,
    process_ref TEXT NOT NULL,
    result_ref TEXT NOT NULL,
    result_hash TEXT NOT NULL,
    evidence_root_ref TEXT NOT NULL,
    evidence_root_hash TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    gold_ref TEXT,
    source_ref TEXT NOT NULL,
    status TEXT NOT NULL,
    provenance TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    UNIQUE (run_id, oracle_kind),
    UNIQUE (run_id, identity_ref),
    UNIQUE (run_id, process_ref),
    UNIQUE (run_id, result_ref)
);

CREATE TABLE IF NOT EXISTS tw_side_effect_ledger (
    entry_id TEXT PRIMARY KEY,
    call_ref TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    actor_ref TEXT NOT NULL,
    tool_ref TEXT NOT NULL,
    operation TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    decision TEXT NOT NULL,
    effect TEXT NOT NULL,
    fencing TEXT NOT NULL,
    observed BOOLEAN NOT NULL,
    occurred_at TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    result_hash TEXT,
    provenance TEXT NOT NULL,
    content_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_tw_side_effect_run
    ON tw_side_effect_ledger (run_id, campaign_id, trace_id, occurred_at);
