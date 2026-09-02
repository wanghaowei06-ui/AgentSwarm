from __future__ import annotations

import json
from dataclasses import asdict, replace
from typing import Any

import pytest

from testweaver.authority import AuthorityError, AuthorityStore, OracleResult, digest_bytes
from testweaver.integrations import (
    AgentLoopClient,
    AgentLoopCredentialLease,
    AgentLoopEndpoint,
    AgentLoopHTTPResponse,
    AgentLoopScope,
    CandidateCapability,
    HeterogeneityPolicyFact,
    MatrixDecisionExpectation,
    MatrixHumanReadbackVerifier,
    NativeEventProjector,
    ProjectionError,
)
from testweaver.integrations.matrix_readback import MatrixAuthenticatedEvent
from testweaver.integrations.projector import (
    LIVE_SOURCE_ATTESTED,
    UNATTESTED_PARTIAL,
    NativeCollectorAttestation,
)

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def _raw_event(event_type: str, revision: int, facts: dict[str, Any]) -> bytes:
    return json.dumps(
        {
            "event_type": event_type,
            "event_id": f"native-event-{revision}",
            "aggregate_id": "native-run-1",
            "revision": revision,
            "actor": "native-agentteams",
            "occurred_at": "2026-09-03T01:00:00Z",
            "campaign_id": "campaign-1",
            "run_id": "run-1",
            "trace_id": "trace-1",
            "source_ref": f"matrix:event-{revision}",
            "lifecycle_state": "FINISHED",
            "facts": facts,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def test_projector_accepts_all_finished_native_fact_types_and_only_appends() -> None:
    store = AuthorityStore.from_sqlite_memory()
    projector = NativeEventProjector(store)
    cases = [
        (
            "manager_choice",
            {
                "choice": "exploration",
                "team_ref": "team:e",
                "leader_ref": "leader:e",
                "evidence_refs": ["evidence:1"],
                "runtime": "qwenpaw",
                "provider": "agentteams-gateway",
                "model": "qwen",
                "call_count": 1,
                "input_tokens": 11,
                "output_tokens": 7,
                "latency_ms": 123,
                "request_hash": HASH_A,
                "response_hash": HASH_B,
            },
        ),
        (
            "accepted_result",
            {
                "task_ref": "task:1",
                "worker_ref": "worker:1",
                "result_ref": "result:1",
                "result_hash": HASH_A,
                "generation": 1,
            },
        ),
        (
            "handoff",
            {
                "handoff_ref": "handoff:1",
                "handoff_hash": HASH_A,
                "source_team_ref": "team:e",
                "target_team_ref": "team:c",
            },
        ),
        (
            "skill_invocation",
            {
                "skill_name": "diagnose",
                "skill_version": "v1",
                "skill_hash": HASH_A,
                "invocation_ref": "skill-call:1",
                "worker_ref": "worker:1",
            },
        ),
        (
            "dsh_call",
            {
                "worker_ref": "worker:dsh",
                "runtime": "deepseek-harness",
                "provider": "bailian",
                "model": "deepseek-v4-flash",
                "input_tokens": 11,
                "output_tokens": 7,
                "latency_ms": 123,
                "request_hash": HASH_A,
                "response_hash": HASH_B,
            },
        ),
        (
            "recovery_generation",
            {
                "task_ref": "task:1",
                "previous_generation": 1,
                "new_generation": 2,
                "cause_ref": "fault:1",
            },
        ),
        (
            "late_result_rejection",
            {
                "task_ref": "task:1",
                "result_ref": "result:late",
                "result_hash": HASH_A,
                "generation": 1,
                "reason_code": "STALE_GENERATION",
            },
        ),
        (
            "oracle_ref",
            {
                "oracle_kind": "OUTCOME",
                "oracle_identity": "worker:outcome",
                "oracle_process_ref": "process:outcome",
                "result_ref": "oracle:1",
                "result_hash": HASH_A,
                "evidence_root_ref": "evidence-root:1",
                "evidence_root_hash": HASH_B,
                "oracle_attestation_ref": "oracle-result:1",
                "oracle_attestation_hash": HASH_C,
            },
        ),
        (
            "agentloop_ref",
            {
                "trace_ref": "agentloop:trace:1",
                "trace_hash": HASH_A,
                "evaluation_ref": "agentloop:eval:1",
                "evaluation_hash": HASH_B,
            },
        ),
    ]
    events = projector.project_many(
        [_raw_event(kind, index, facts) for index, (kind, facts) in enumerate(cases, 1)]
    )
    assert [event.event_type for event in events] == [item[0] for item in cases]
    assert all(
        event.run_id == "run-1" and event.campaign_id == "campaign-1"
        for event in events
    )
    assert all(
        event.payload["native_source_hash"].startswith("sha256:") for event in events
    )
    assert all(
        event.payload["projection_classification"] == UNATTESTED_PARTIAL
        for event in events
    )
    assert projector.project(_raw_event(cases[0][0], 1, cases[0][1]))[1] is False
    assert not any(
        hasattr(projector, name) for name in ("create_task", "send_message", "resume")
    )


def test_projector_rejects_unfinished_unknown_or_body_bearing_facts() -> None:
    projector = NativeEventProjector(AuthorityStore.from_sqlite_memory())
    unfinished = json.loads(
        _raw_event(
            "manager_choice",
            1,
            {
                "choice": "x",
                "team_ref": "t",
                "leader_ref": "l",
                "evidence_refs": ["e"],
                "runtime": "qwenpaw",
                "provider": "gateway",
                "model": "qwen",
                "call_count": 1,
                "input_tokens": 1,
                "output_tokens": 1,
                "latency_ms": 1,
                "request_hash": HASH_A,
                "response_hash": HASH_B,
            },
        )
    )
    unfinished["lifecycle_state"] = "RUNNING"
    with pytest.raises(ProjectionError, match="completed"):
        projector.project(json.dumps(unfinished).encode())
    with pytest.raises(ProjectionError, match="unknown fact"):
        projector.project(
            _raw_event(
                "manager_choice",
                1,
                {
                    "choice": "x",
                    "team_ref": "t",
                    "leader_ref": "l",
                    "evidence_refs": ["e"],
                    "runtime": "qwenpaw",
                    "provider": "gateway",
                    "model": "qwen",
                    "call_count": 1,
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "latency_ms": 1,
                    "request_hash": HASH_A,
                    "response_hash": HASH_B,
                    "output": "forbidden",
                },
            )
        )


def _manager_facts() -> dict[str, Any]:
    return {
        "choice": "exploration",
        "team_ref": "team:e",
        "leader_ref": "leader:e",
        "evidence_refs": ["evidence:1"],
        "runtime": "qwenpaw",
        "provider": "agentteams-gateway",
        "model": "qwen",
        "call_count": 1,
        "input_tokens": 11,
        "output_tokens": 7,
        "latency_ms": 123,
        "request_hash": HASH_A,
        "response_hash": HASH_B,
    }


def _collector_attestation(raw: bytes, *, source_ref: str, exact_get_ref: str):
    return NativeCollectorAttestation.create(
        attestation_ref=f"attestation:{exact_get_ref}",
        collector_ref="collector:native",
        collector_identity_ref="service:native-reader",
        source_ref=source_ref,
        exact_get_ref=exact_get_ref,
        raw_bytes=raw,
        observed_at="2026-09-03T01:00:01Z",
    )


def test_projector_requires_allowlisted_exact_get_before_source_is_live() -> None:
    raw = _raw_event("manager_choice", 1, _manager_facts())
    source_ref = "matrix:event-1"
    exact_get_ref = "matrix-get:event-1"
    attestation = _collector_attestation(
        raw, source_ref=source_ref, exact_get_ref=exact_get_ref
    )
    projector = NativeEventProjector(
        AuthorityStore.from_sqlite_memory(),
        get_source=lambda reference: attestation if reference == exact_get_ref else None,
        collector_identities={"collector:native": "service:native-reader"},
    )
    event, inserted = projector.project(raw, attestation=attestation)
    assert inserted is True
    assert event.payload["projection_classification"] == LIVE_SOURCE_ATTESTED
    assert event.payload["collector_attestation_hash"] == attestation.record_hash

    forged = NativeCollectorAttestation.create(
        attestation_ref=attestation.attestation_ref,
        collector_ref=attestation.collector_ref,
        collector_identity_ref="service:forged",
        source_ref=attestation.source_ref,
        exact_get_ref=attestation.exact_get_ref,
        raw_bytes=raw,
        observed_at=attestation.observed_at,
    )
    with pytest.raises(ProjectionError, match="allowlist"):
        projector.materialize(raw, attestation=forged)
    changed = raw.replace(b'"choice":"exploration"', b'"choice":"convergence"')
    with pytest.raises(ProjectionError, match="bytes differ"):
        projector.materialize(changed, attestation=attestation)


def test_projector_requires_manager_usage_generation_and_full_oracle_readback() -> None:
    projector = NativeEventProjector(AuthorityStore.from_sqlite_memory())
    manager = _manager_facts()
    manager.pop("provider")
    with pytest.raises(ProjectionError, match="missing fact"):
        projector.materialize(_raw_event("manager_choice", 1, manager))
    with pytest.raises(ProjectionError, match="missing fact"):
        projector.materialize(
            _raw_event(
                "accepted_result",
                1,
                {
                    "task_ref": "task:1",
                    "worker_ref": "worker:1",
                    "result_ref": "result:1",
                    "result_hash": HASH_A,
                },
            )
        )

    oracle = OracleResult.create(
        result_id="oracle-result:1",
        oracle_kind="outcome",
        run_id="run-1",
        campaign_id="campaign-1",
        trace_id="trace-1",
        identity_ref="worker:outcome",
        process_ref="process:outcome",
        result_ref="oracle:1",
        result_hash=HASH_A,
        evidence_root_ref="evidence-root:1",
        evidence_root_hash=HASH_B,
        evidence_refs=[{"ref": "evidence:1", "content_hash": HASH_A}],
        gold_ref="gold:sealed",
        source_ref="worker-result:outcome",
        status="PASS",
        provenance="agentteams:worker:outcome",
    )
    facts = {
        "oracle_kind": "OUTCOME",
        "oracle_identity": oracle.identity_ref,
        "oracle_process_ref": oracle.process_ref,
        "result_ref": oracle.result_ref,
        "result_hash": oracle.result_hash,
        "evidence_root_ref": oracle.evidence_root_ref,
        "evidence_root_hash": oracle.evidence_root_hash,
        "oracle_attestation_ref": oracle.result_id,
        "oracle_attestation_hash": oracle.content_hash,
    }
    raw = _raw_event("oracle_ref", 1, facts)
    attestation = _collector_attestation(
        raw, source_ref="matrix:event-1", exact_get_ref="matrix-get:oracle-1"
    )
    linked = NativeEventProjector(
        AuthorityStore.from_sqlite_memory(),
        get_source=lambda _reference: attestation,
        collector_identities={"collector:native": "service:native-reader"},
        oracle_lookup=lambda ref: oracle if ref == oracle.result_id else None,
    ).materialize(raw, attestation=attestation)
    assert linked.payload["oracle_readback_verified"] is True
    assert linked.payload["projection_classification"] == LIVE_SOURCE_ATTESTED

    unlinked = NativeEventProjector(
        AuthorityStore.from_sqlite_memory(),
        get_source=lambda _reference: attestation,
        collector_identities={"collector:native": "service:native-reader"},
    ).materialize(raw, attestation=attestation)
    assert unlinked.payload["oracle_readback_verified"] is False
    assert unlinked.payload["projection_classification"] == UNATTESTED_PARTIAL


def _matrix_expectation() -> MatrixDecisionExpectation:
    return MatrixDecisionExpectation.create(
        room_id="!room:matrix.local",
        event_id="$event:matrix.local",
        sender="@human:matrix.local",
        identity_ref="human:operator-1",
        approval_id="approval-1",
        phase="APPROVE",
        decision="APPROVE",
        campaign_id="campaign-1",
        run_id="run-1",
        trace_id="trace-1",
        revision=3,
        action_ref="action:write-sandbox",
        action_hash=HASH_A,
        verification_ref="matrix-readback:1",
        verified_at="2026-09-03T01:02:00Z",
    )


def _matrix_raw(expected: MatrixDecisionExpectation) -> bytes:
    return json.dumps(
        {
            "type": "m.room.message",
            "room_id": expected.room_id,
            "event_id": expected.event_id,
            "sender": expected.sender,
            "origin_server_ts": 1788406920000,
            "content": {
                "msgtype": "m.notice",
                "body": "human-readable copy is not authoritative",
                "testweaver": {
                    "identity_ref": expected.identity_ref,
                    "approval_id": expected.approval_id,
                    "phase": expected.phase,
                    "decision": expected.decision,
                    "campaign_id": expected.campaign_id,
                    "run_id": expected.run_id,
                    "trace_id": expected.trace_id,
                    "revision": expected.revision,
                    "action_ref": expected.action_ref,
                    "action_hash": expected.action_hash,
                    "action_fingerprint": expected.action_fingerprint,
                },
            },
        },
        sort_keys=True,
    ).encode()


def _matrix_readback(
    expected: MatrixDecisionExpectation, raw: bytes | None = None
) -> MatrixAuthenticatedEvent:
    return MatrixAuthenticatedEvent.create(
        raw_bytes=raw or _matrix_raw(expected),
        homeserver_ref="matrix-homeserver:native",
        reader_identity_ref="service:matrix-readback",
        request_ref=f"matrix-get:{expected.event_id}",
        room_id=expected.room_id,
        event_id=expected.event_id,
    )


def _matrix_verifier(
    expected: MatrixDecisionExpectation,
    *,
    raw: bytes | None = None,
    identity: str = "human:operator-1",
    protected_identity: str = "human:operator-1",
) -> MatrixHumanReadbackVerifier:
    return MatrixHumanReadbackVerifier(
        get_event=lambda _room, _event: _matrix_readback(expected, raw),
        get_identity=lambda _sender: identity,
        human_identities={expected.sender: protected_identity},
        get_pending_approval=lambda _approval_id: expected,
        trusted_homeserver_ref="matrix-homeserver:native",
        trusted_reader_identity_ref="service:matrix-readback",
        clock=lambda: "2026-09-03T01:05:00Z",
    )


def test_matrix_exact_get_produces_sealed_external_human_attestation() -> None:
    expected = _matrix_expectation()
    calls: list[tuple[str, str]] = []

    def get_event(room: str, event: str) -> MatrixAuthenticatedEvent:
        calls.append((room, event))
        return _matrix_readback(expected)

    attestation = MatrixHumanReadbackVerifier(
        get_event=get_event,
        get_identity=lambda _sender: "human:operator-1",
        human_identities={expected.sender: "human:operator-1"},
        get_pending_approval=lambda _approval_id: expected,
        trusted_homeserver_ref="matrix-homeserver:native",
        trusted_reader_identity_ref="service:matrix-readback",
        clock=lambda: "2026-09-03T01:05:00Z",
    ).verify(expected)
    assert calls == [(expected.room_id, expected.event_id)]
    assert attestation.source == "matrix-live-readback"
    assert attestation.event_hash.startswith("sha256:")
    assert attestation.verified_at == "2026-09-03T01:05:00Z"
    attestation.validate()


def test_matrix_readback_rejects_sender_or_action_substitution() -> None:
    expected = _matrix_expectation()
    value = json.loads(_matrix_raw(expected))
    value["sender"] = "@agent:matrix.local"
    with pytest.raises(AuthorityError, match="sender"):
        _matrix_verifier(expected, raw=json.dumps(value).encode()).verify(expected)
    with pytest.raises(AuthorityError, match="identity_ref"):
        _matrix_verifier(expected, identity="human:someone-else").verify(expected)
    with pytest.raises(AuthorityError, match="fingerprint"):
        MatrixDecisionExpectation.create(
            **{**asdict(expected), "action_fingerprint": HASH_C}
        )


def test_matrix_readback_requires_authenticated_get_allowlist_and_pending_authority() -> None:
    expected = _matrix_expectation()
    with pytest.raises(AuthorityError, match="trust configuration"):
        MatrixHumanReadbackVerifier(
            lambda _r, _e: _matrix_raw(expected),
            lambda _sender: expected.identity_ref,
        ).verify(expected)
    with pytest.raises(AuthorityError, match="protected identity"):
        _matrix_verifier(expected, protected_identity="human:someone-else").verify(expected)
    changed = replace(expected, action_ref="action:other")
    with pytest.raises(AuthorityError, match="pending approval"):
        MatrixHumanReadbackVerifier(
            get_event=lambda _r, _e: _matrix_readback(expected),
            get_identity=lambda _sender: expected.identity_ref,
            human_identities={expected.sender: expected.identity_ref},
            get_pending_approval=lambda _approval_id: changed,
            trusted_homeserver_ref="matrix-homeserver:native",
            trusted_reader_identity_ref="service:matrix-readback",
        ).verify(expected)


@pytest.mark.parametrize("mutation", ["type", "msgtype", "redacted"])
def test_matrix_readback_rejects_non_message_or_redacted_event(mutation: str) -> None:
    expected = _matrix_expectation()
    value = json.loads(_matrix_raw(expected))
    if mutation == "type":
        value["type"] = "m.room.member"
    elif mutation == "msgtype":
        value["content"]["msgtype"] = "m.image"
    else:
        value["unsigned"] = {"redacted_because": {"event_id": "$redaction"}}
    with pytest.raises(AuthorityError):
        _matrix_verifier(expected, raw=json.dumps(value).encode()).verify(expected)


def _candidate(
    ref: str, runtime: str, provider: str, model: str
) -> CandidateCapability:
    return CandidateCapability(
        candidate_ref=ref,
        runtime=runtime,
        provider=provider,
        model=model,
        capability_refs=("capability:diagnosis",),
        evidence_refs=(f"evidence:{ref}",),
        evidence_hashes=(HASH_A,),
    )


def test_heterogeneity_fact_seals_actual_manager_choice_without_selecting() -> None:
    candidates = (
        _candidate("worker:qwen", "qwenpaw", "agentteams-gateway", "qwen"),
        _candidate("worker:dsh", "deepseek-harness", "bailian", "deepseek-v4-flash"),
    )
    fact = HeterogeneityPolicyFact.create(
        fact_id="heterogeneity:1",
        campaign_id="campaign-1",
        run_id="run-1",
        revision=2,
        policy_ref="policy:heterogeneity-v1",
        policy_hash=HASH_A,
        candidates=candidates,
        manager_choice_ref="matrix:manager-choice-2",
        manager_choice_hash=HASH_B,
        chosen_candidate_ref="worker:dsh",
        actual_runtime="deepseek-harness",
        actual_provider="bailian",
        actual_model="deepseek-v4-flash",
        input_tokens=20,
        output_tokens=10,
        latency_ms=250,
        request_hash=HASH_A,
        response_hash=HASH_B,
        observed_at="2026-09-03T01:03:00Z",
    )
    fact.validate()
    assert fact.content_hash.startswith("sha256:")
    assert fact.projection_classification == UNATTESTED_PARTIAL
    assert not any(hasattr(fact, method) for method in ("choose", "dispatch", "rank"))
    with pytest.raises(AuthorityError, match="actual runtime identity"):
        replace(fact, actual_provider="other")


def test_heterogeneity_live_source_requires_attested_manager_and_runtime() -> None:
    manager_raw = _raw_event("manager_choice", 1, _manager_facts())
    runtime_facts = {
        "worker_ref": "worker:dsh",
        "runtime": "deepseek-harness",
        "provider": "bailian",
        "model": "deepseek-v4-flash",
        "input_tokens": 20,
        "output_tokens": 10,
        "latency_ms": 250,
        "request_hash": HASH_A,
        "response_hash": HASH_B,
    }
    runtime_raw = _raw_event("dsh_call", 2, runtime_facts)
    manager_attestation = _collector_attestation(
        manager_raw,
        source_ref="matrix:event-1",
        exact_get_ref="matrix-get:manager",
    )
    runtime_attestation = _collector_attestation(
        runtime_raw,
        source_ref="matrix:event-2",
        exact_get_ref="matrix-get:runtime",
    )
    exact = {
        "matrix-get:manager": manager_attestation,
        "matrix-get:runtime": runtime_attestation,
    }
    projector = NativeEventProjector(
        AuthorityStore.from_sqlite_memory(),
        get_source=exact.__getitem__,
        collector_identities={"collector:native": "service:native-reader"},
    )
    manager, _ = projector.project(
        manager_raw,
        attestation=manager_attestation,
    )
    runtime, _ = projector.project(
        runtime_raw,
        attestation=runtime_attestation,
    )
    candidates = (
        _candidate("worker:qwen", "qwenpaw", "agentteams-gateway", "qwen"),
        _candidate("worker:dsh", "deepseek-harness", "bailian", "deepseek-v4-flash"),
    )
    fact = HeterogeneityPolicyFact.create_attested(
        manager_projection=manager,
        runtime_projection=runtime,
        fact_id="heterogeneity:live",
        campaign_id="campaign-1",
        run_id="run-1",
        revision=2,
        policy_ref="policy:heterogeneity-v1",
        policy_hash=HASH_A,
        candidates=candidates,
        manager_choice_ref=manager.provenance,
        manager_choice_hash=manager.request_hash,
        chosen_candidate_ref="worker:dsh",
        actual_runtime=runtime_facts["runtime"],
        actual_provider=runtime_facts["provider"],
        actual_model=runtime_facts["model"],
        input_tokens=runtime_facts["input_tokens"],
        output_tokens=runtime_facts["output_tokens"],
        latency_ms=runtime_facts["latency_ms"],
        request_hash=runtime_facts["request_hash"],
        response_hash=runtime_facts["response_hash"],
        observed_at="2026-09-03T01:03:00Z",
    )
    assert fact.projection_classification == LIVE_SOURCE_ATTESTED
    with pytest.raises(AuthorityError, match="self-assert"):
        HeterogeneityPolicyFact.create(
            **{
                **fact.as_dict(include_hash=False),
                "candidates": candidates,
            }
        )


class RecordingTransport:
    def __init__(
        self,
        response: AgentLoopHTTPResponse | None = None,
        error: Exception | None = None,
    ):
        self.response = response or AgentLoopHTTPResponse(
            200, b'{"taskId":"task-1"}', "req-1"
        )
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def request(self, **values: Any) -> AgentLoopHTTPResponse:
        self.calls.append(values)
        if self.error:
            raise self.error
        return self.response


def _client(
    transport: RecordingTransport, credential: object = "credential-material-sentinel"
) -> AgentLoopClient:
    return AgentLoopClient(
        AgentLoopEndpoint("https://agentloop.cn-beijing.aliyuncs.com", "space-1"),
        transport,
        lambda: AgentLoopCredentialLease("protected:/etc/agentloop", credential),
        lambda: "2026-09-03T01:04:00Z",
    )


def test_agentloop_client_uses_inherited_dataset_evaluator_task_shapes_and_hash_receipts() -> (
    None
):
    transport = RecordingTransport()
    client = _client(transport)
    scope = AgentLoopScope("campaign-1", "run-1", 4)
    results = [
        client.create_dataset(
            scope,
            dataset_name="dataset-1",
            description="real run",
            client_token="idem-1",
        ),
        client.upsert_dataset_rows(
            scope, dataset_name="dataset-1", item_hashes=[HASH_A], client_token="idem-2"
        ),
        client.get_dataset(scope, dataset_name="dataset-1"),
        client.create_evaluator(
            scope,
            evaluator_name="eval-1",
            metric_name="quality",
            prompt="Evaluate evidence",
            client_token="idem-3",
        ),
        client.get_evaluator(scope, evaluator_name="eval-1"),
        client.create_evaluation_task_run(
            scope,
            task_name="task-1",
            dataset_name="dataset-1",
            evaluator_ref="eval-1",
            data_type="dataset",
            data_filter={"datasetName": "dataset-1", "maxRecords": 1},
            variable_mapping={"input": "content"},
            hidden_gold_visible=False,
            client_token="idem-4",
        ),
        client.get_evaluation_task(scope, task_id="task-1"),
        client.get_evaluation_runs(scope, task_id="task-1"),
    ]
    assert [result.receipt.operation for result in results] == [
        "CreateDataset",
        "AddDatasetData",
        "GetDataset",
        "CreateEvaluator",
        "GetEvaluator",
        "CreateEvaluationTask",
        "GetEvaluationTask",
        "ListEvaluationRuns",
    ]
    task_body = json.loads(transport.calls[5]["body"])
    assert task_body["dataType"] == "dataset"
    assert task_body["dataFilter"] == {
        "datasetName": "dataset-1",
        "maxRecords": 1,
    }
    assert task_body["evaluators"][0]["variableMapping"] == {"input": "content"}
    assert "gold" not in json.dumps(task_body).lower()
    assert task_body["runStrategies"] == {"backfill": {"enabled": True}}
    assert task_body["tags"] == {
        "campaignId": "campaign-1",
        "runId": "run-1",
        "revision": "4",
    }
    serialized = json.dumps([asdict(result.receipt) for result in results], default=str)
    assert "credential-material-sentinel" not in serialized
    assert "credential-material-sentinel" not in repr(
        AgentLoopCredentialLease(
            "protected:/etc/agentloop", "credential-material-sentinel"
        )
    )
    assert all(result.receipt.status == "API_ACCEPTED" for result in results)
    assert results[5].resource_ref == "task-1"
    assert not any(
        hasattr(client, method)
        for method in (
            "delete",
            "delete_dataset",
            "delete_evaluator",
            "delete_evaluation_task",
        )
    )


def test_agentloop_endpoint_and_permission_failures_are_explicitly_blocked() -> None:
    scope = AgentLoopScope("campaign-1", "run-1", 1)
    denied = _client(
        RecordingTransport(
            AgentLoopHTTPResponse(403, b"denied", error_code="Forbidden")
        )
    )
    denied_result = denied.get_evaluation_task(scope, task_id="task-1")
    assert denied_result.receipt.status == "BLOCKED"
    assert denied_result.receipt.error_category == "PERMISSION_DENIED"
    unavailable = _client(RecordingTransport(error=OSError("offline")))
    unavailable_result = unavailable.get_evaluation_task(scope, task_id="task-1")
    assert unavailable_result.receipt.status == "BLOCKED"
    assert unavailable_result.receipt.error_category == "ENDPOINT_UNAVAILABLE"

    malformed = _client(RecordingTransport(AgentLoopHTTPResponse(200, b"{}")))
    malformed_result = malformed.create_evaluation_task_run(
        scope,
        task_name="task-1",
        dataset_name="dataset-1",
        evaluator_ref="eval-1",
        data_type="dataset",
        data_filter={"datasetName": "dataset-1", "maxRecords": 1},
        variable_mapping={"input": "content"},
        hidden_gold_visible=False,
        client_token="idem-1",
    )
    assert malformed_result.receipt.status == "API_ACCEPTED"
    assert malformed_result.receipt.error_category == "RESPONSE_CONTRACT_INVALID"


@pytest.mark.parametrize(
    ("data_type", "data_filter", "variable_mapping", "hidden_gold_visible"),
    [
        ("trace", {"datasetName": "dataset-1", "maxRecords": 1}, {"input": "content"}, False),
        ("dataset", {"datasetName": "dataset-1", "maxRecords": 2}, {"input": "content"}, False),
        ("dataset", {"datasetName": "other", "maxRecords": 1}, {"input": "content"}, False),
        ("dataset", {"datasetName": "dataset-1", "maxRecords": 1}, {"output": "content"}, False),
        ("dataset", {"datasetName": "dataset-1", "maxRecords": 1}, {"input": "content"}, True),
    ],
)
def test_agentloop_evaluation_task_rejects_unbounded_or_gold_visible_inputs(
    data_type: str,
    data_filter: dict[str, Any],
    variable_mapping: dict[str, Any],
    hidden_gold_visible: bool,
) -> None:
    client = _client(RecordingTransport())
    with pytest.raises(AuthorityError):
        client.create_evaluation_task_run(
            AgentLoopScope("campaign-1", "run-1", 1),
            task_name="task-1",
            dataset_name="dataset-1",
            evaluator_ref="eval-1",
            data_type=data_type,
            data_filter=data_filter,
            variable_mapping=variable_mapping,
            hidden_gold_visible=hidden_gold_visible,
            client_token="idem-1",
        )


def test_agentloop_credential_callback_failure_is_blocked_without_transport_call() -> (
    None
):
    transport = RecordingTransport()
    client = AgentLoopClient(
        AgentLoopEndpoint("https://agentloop.cn-beijing.aliyuncs.com", "space-1"),
        transport,
        lambda: (_ for _ in ()).throw(RuntimeError("missing")),
        lambda: "2026-09-03T01:04:00Z",
    )
    result = client.get_evaluation_task(
        AgentLoopScope("campaign-1", "run-1", 1), task_id="task-1"
    )
    assert result.receipt.status == "BLOCKED"
    assert result.receipt.error_category == "CREDENTIAL_UNAVAILABLE"
    assert transport.calls == []
