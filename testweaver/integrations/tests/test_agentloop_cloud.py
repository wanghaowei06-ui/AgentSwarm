from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from testweaver.authority import AuthorityError
from testweaver.integrations.agentloop_client import (
    AgentLoopClient,
    AgentLoopCredentialLease,
    AgentLoopEndpoint,
    AgentLoopEvidenceBinding,
    AgentLoopHTTPResponse,
    AgentLoopScope,
)
from testweaver.integrations.tea_transport import (
    AlibabaCloudCredential,
    TeaAgentLoopTransport,
    assume_role_credential,
    load_protected_csv_credential,
)
from testweaver.integrations.xtrace_readback import (
    TeaXTraceTransport,
    XTraceCorrelation,
    XTraceHTTPResponse,
    XTraceReadbackClient,
)

HASH = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
TRACE_ID = "0123456789abcdef0123456789abcdef"


def _evidence_binding() -> AgentLoopEvidenceBinding:
    return AgentLoopEvidenceBinding(TRACE_ID, HASH, HASH_B, HASH_C)


class QueueTransport:
    def __init__(self, responses: list[AgentLoopHTTPResponse]):
        self.responses = responses

    def request(self, **_: Any) -> AgentLoopHTTPResponse:
        return self.responses.pop(0)


class RecordingAgentLoopTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def request(self, **request: Any) -> AgentLoopHTTPResponse:
        self.calls.append(request)
        return AgentLoopHTTPResponse(200, b'{"taskId":"task-1"}')


def _lease() -> AgentLoopCredentialLease:
    return AgentLoopCredentialLease(
        "protected:/root/projects/muti-agent/AccessKey.csv",
        AlibabaCloudCredential("access-id-sentinel", "secret-sentinel"),
    )


def test_credential_lease_and_material_are_not_dataclass_serializable() -> None:
    lease = _lease()
    assert "secret-sentinel" not in repr(lease)
    assert "access-id-sentinel" not in repr(lease.material)
    assert lease.as_dict() == {
        "protected_ref": "protected:/root/projects/muti-agent/AccessKey.csv",
        "material": "<redacted>",
    }
    with pytest.raises(TypeError):
        asdict(lease)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        asdict(lease.material)  # type: ignore[arg-type]


def test_http_response_reprs_do_not_expose_response_bodies() -> None:
    marker = "prompt-response-body-sentinel"
    assert marker not in repr(AgentLoopHTTPResponse(200, marker.encode(), "request-1"))
    assert marker not in repr(XTraceHTTPResponse(200, marker.encode(), "request-1"))
    with pytest.raises(TypeError):
        asdict(AgentLoopHTTPResponse(200, marker.encode()))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        asdict(XTraceHTTPResponse(200, marker.encode()))  # type: ignore[arg-type]


def test_protected_csv_loader_rejects_unsafe_files(tmp_path: Path) -> None:
    path = tmp_path / "AccessKey.csv"
    path.write_text("AccessKey ID,AccessKey Secret\nid,secret\n", encoding="utf-8")
    path.chmod(0o600)
    loaded = load_protected_csv_credential(path)
    assert "id" not in repr(loaded)
    path.chmod(0o644)
    with pytest.raises(AuthorityError, match="owner-only"):
        load_protected_csv_credential(path)


def test_protected_csv_loader_rejects_a_different_runtime_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "AccessKey.csv"
    path.write_text("AccessKey ID,AccessKey Secret\nid,secret\n", encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setattr(os, "geteuid", lambda: path.stat().st_uid + 1)
    with pytest.raises(AuthorityError, match="current runtime user"):
        load_protected_csv_credential(path)


def test_assume_role_returns_temporary_credential_with_security_token() -> None:
    calls: list[dict[str, Any]] = []
    long_term = AlibabaCloudCredential("long-id-sentinel", "long-secret-sentinel")

    def caller(**values: Any) -> dict[str, Any]:
        calls.append(values)
        return {
            "status_code": 200,
            "body": {
                "RequestId": "request-1",
                "Credentials": {
                    "AccessKeyId": "temporary-id-sentinel",
                    "AccessKeySecret": "temporary-secret-sentinel",
                    "SecurityToken": "security-token-sentinel",
                    "Expiration": "2026-09-03T03:00:00Z",
                },
            },
        }

    temporary = assume_role_credential(
        long_term,
        region="cn-beijing",
        role_arn="acs:ram::1234567890123456:role/testweaveragentlooprole",
        role_session_name="testweaver-hero-readback",
        duration_seconds=900,
        caller=caller,
    )

    assert repr(temporary) == "AlibabaCloudCredential(<redacted>)"
    assert calls[0]["operation"] == "AssumeRole"
    assert calls[0]["version"] == "2015-04-01"
    assert calls[0]["hostname"] == "sts.cn-beijing.aliyuncs.com"
    assert calls[0]["credential"] is long_term
    assert calls[0]["duration_seconds"] == 900
    assert temporary._runtime_values() == (
        "temporary-id-sentinel",
        "temporary-secret-sentinel",
        "security-token-sentinel",
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"region": "CN-beijing"}, "region"),
        ({"role_arn": "acs:ram::*:role/admin"}, "role ARN"),
        ({"role_session_name": "bad session"}, "session name"),
        ({"duration_seconds": 899}, "duration"),
        ({"duration_seconds": 3601}, "duration"),
    ],
)
def test_assume_role_rejects_unbounded_authority_inputs_before_call(
    overrides: dict[str, Any], message: str
) -> None:
    called = False

    def caller(**_: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        return {}

    values: dict[str, Any] = {
        "region": "cn-beijing",
        "role_arn": "acs:ram::1234567890123456:role/testweaveragentlooprole",
        "role_session_name": "testweaver-hero-readback",
        "duration_seconds": 900,
    }
    values.update(overrides)
    with pytest.raises(AuthorityError, match=message):
        assume_role_credential(
            AlibabaCloudCredential("id", "secret"), caller=caller, **values
        )
    assert not called


def test_assume_role_fails_closed_without_leaking_caller_or_response_secrets() -> None:
    def raising_caller(**_: Any) -> dict[str, Any]:
        raise RuntimeError("long-secret-sentinel security-token-sentinel")

    with pytest.raises(AuthorityError) as raised:
        assume_role_credential(
            AlibabaCloudCredential("long-id-sentinel", "long-secret-sentinel"),
            region="cn-beijing",
            role_arn="acs:ram::1234567890123456:role/testweaveragentlooprole",
            role_session_name="testweaver-hero-readback",
            caller=raising_caller,
        )
    assert "sentinel" not in str(raised.value)

    with pytest.raises(AuthorityError) as malformed:
        assume_role_credential(
            AlibabaCloudCredential("long-id-sentinel", "long-secret-sentinel"),
            region="cn-beijing",
            role_arn="acs:ram::1234567890123456:role/testweaveragentlooprole",
            role_session_name="testweaver-hero-readback",
            caller=lambda **_: {
                "status_code": 200,
                "body": {
                    "Credentials": {
                        "AccessKeyId": "temporary-id-sentinel",
                        "AccessKeySecret": "temporary-secret-sentinel",
                    }
                },
            },
        )
    assert "sentinel" not in str(malformed.value)


def test_assume_role_rejects_temporary_source_credential() -> None:
    with pytest.raises(AuthorityError, match="long-term"):
        assume_role_credential(
            AlibabaCloudCredential("id", "secret", "already-temporary"),
            region="cn-beijing",
            role_arn="acs:ram::1234567890123456:role/testweaveragentlooprole",
            role_session_name="testweaver-hero-readback",
            caller=lambda **_: {},
        )


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://agentloop.cn-beijing.aliyuncs.com",
        "https://user@agentloop.cn-beijing.aliyuncs.com",
        "https://agentloop.cn-beijing.aliyuncs.com/path",
        "https://evil.example.com",
    ],
)
def test_tea_transport_rejects_noncanonical_agentloop_endpoint(endpoint: str) -> None:
    transport = TeaAgentLoopTransport("cn-beijing", caller=lambda **_: None)
    with pytest.raises(AuthorityError):
        transport.request(
            operation="GetDataset",
            method="GET",
            endpoint=endpoint,
            path="/agentspace/space/dataset/data",
            query={},
            body=None,
            credential=_lease().material,
        )


def test_client_endpoint_rejects_nested_or_noncanonical_hosts() -> None:
    with pytest.raises(AuthorityError):
        AgentLoopEndpoint("https://agentloop.extra.cn-beijing.aliyuncs.com", "space-1")


def test_tea_transport_uses_roa_shape_without_exposing_credential() -> None:
    calls: list[dict[str, Any]] = []

    def caller(**values: Any) -> dict[str, Any]:
        calls.append(values)
        return {
            "status_code": 200,
            "headers": {"x-acs-request-id": "request-1"},
            "body": {
                "agentSpace": "space",
                "datasetName": "dataset",
                "schema": {"content": {}},
            },
        }

    response = TeaAgentLoopTransport("cn-beijing", caller=caller).request(
        operation="GetDataset",
        method="GET",
        endpoint="https://agentloop.cn-beijing.aliyuncs.com",
        path="/agentspace/space/dataset/dataset",
        query={},
        body=None,
        credential=_lease().material,
    )
    assert response.status_code == 200
    assert calls[0]["style"] == "ROA"
    assert calls[0]["version"] == "2026-05-20"
    assert "secret-sentinel" not in json.dumps(
        {key: value for key, value in calls[0].items() if key != "credential"},
        default=str,
    )


def test_transports_hashable_request_id_can_come_from_transient_body() -> None:
    def agentloop_caller(**_: Any) -> dict[str, Any]:
        return {"status_code": 200, "headers": {}, "body": {"requestId": "agent-1"}}

    agentloop = TeaAgentLoopTransport("cn-beijing", caller=agentloop_caller).request(
        operation="GetDataset",
        method="GET",
        endpoint="https://agentloop.cn-beijing.aliyuncs.com",
        path="/agentspace/space/dataset/dataset",
        query={},
        body=None,
        credential=_lease().material,
    )
    assert agentloop.request_id == "agent-1"

    def xtrace_caller(**_: Any) -> dict[str, Any]:
        return {"status_code": 200, "headers": {}, "body": {"RequestId": "trace-1"}}

    xtrace = TeaXTraceTransport(caller=xtrace_caller).get_trace(
        region="cn-beijing",
        trace_id="0123456789abcdef0123456789abcdef",
        credential=_lease().material,
    )
    assert xtrace.request_id == "trace-1"


def test_evaluation_query_requires_ownership_scope_terminal_and_nonempty_result() -> (
    None
):
    scope = AgentLoopScope("campaign-1", "run-1", 7)
    task = {
        "taskId": "task-1",
        "agentSpace": "space-1",
        "status": "Completed",
        "evaluators": [{"evaluatorRef": "eval-1"}],
        "tags": {
            "campaignId": "campaign-1",
            "runId": "run-1",
            "revision": "7",
            "traceId": TRACE_ID,
            "contentHash": HASH,
            "providerTurnRecordHash": HASH_B,
            "providerTurnSourceHash": HASH_C,
        },
    }
    runs = {
        "evaluationRuns": [
            {
                "taskId": "task-1",
                "runId": "evaluation-run-1",
                "status": "Completed",
                "totalCount": 1,
                "successCount": 1,
                "failedCount": 0,
            }
        ]
    }
    client = AgentLoopClient(
        AgentLoopEndpoint("https://agentloop.cn-beijing.aliyuncs.com", "space-1"),
        QueueTransport(
            [
                AgentLoopHTTPResponse(200, json.dumps(task).encode(), "request-1"),
                AgentLoopHTTPResponse(200, json.dumps(runs).encode(), "request-2"),
            ]
        ),
        _lease,
        lambda: "2026-09-03T02:00:00Z",
    )
    verified = client.verify_evaluation_task_run(
        scope, task_id="task-1", evidence_binding=_evidence_binding()
    )
    assert verified.status == "API_QUERY_VERIFIED"
    assert verified.ownership_verified
    assert verified.scope_verified
    assert verified.evidence_verified
    assert verified.terminal
    assert verified.result_count == 1
    assert verified.successful_result_count == 1


def test_evaluation_task_can_carry_every_exact_provider_turn_tag() -> None:
    transport = RecordingAgentLoopTransport()
    client = AgentLoopClient(
        AgentLoopEndpoint("https://agentloop.cn-beijing.aliyuncs.com", "space-1"),
        transport,
        _lease,
        lambda: "2026-09-03T02:00:00Z",
    )
    client.create_evaluation_task_run(
        AgentLoopScope("campaign-1", "run-1", 7),
        task_name="task-1",
        dataset_name="dataset-1",
        evaluator_ref="eval-1",
        data_type="dataset",
        data_filter={"datasetName": "dataset-1", "maxRecords": 1},
        variable_mapping={"input": "content"},
        hidden_gold_visible=False,
        client_token="client-token-1",
        evidence_binding=_evidence_binding(),
    )
    body = json.loads(transport.calls[0]["body"])
    assert body["tags"] == {
        "campaignId": "campaign-1",
        "runId": "run-1",
        "revision": "7",
        "traceId": TRACE_ID,
        "contentHash": HASH,
        "providerTurnRecordHash": HASH_B,
        "providerTurnSourceHash": HASH_C,
    }


def test_trace_evaluation_task_uses_native_trace_source_and_exact_filter() -> None:
    transport = RecordingAgentLoopTransport()
    client = AgentLoopClient(
        AgentLoopEndpoint("https://agentloop.cn-beijing.aliyuncs.com", "space-1"),
        transport,
        _lease,
        lambda: "2026-09-03T02:00:00Z",
    )
    result = client.create_trace_evaluation_task_run(
        AgentLoopScope("campaign-1", "run-1", 7),
        task_name="trace-task-1",
        trace_id=TRACE_ID,
        client_token="client-token-1",
        start_time_ms=1788390000000,
        end_time_ms=1788393600000,
        evidence_binding=_evidence_binding(),
    )
    assert result.receipt.operation == "CreateEvaluationTask"
    assert result.resource_ref == "task-1"
    body = json.loads(transport.calls[0]["body"])
    assert body["dataType"] == "trace"
    assert body["dataFilter"] == {
        "query": "traceId='0123456789abcdef0123456789abcdef'",
        "maxRecords": 1,
        "samplingRate": 100,
    }
    assert body["config"] == {"dataScope": "trace"}
    assert body["runStrategies"] == {
        "backfill": {
            "enabled": True,
            "startTime": 1788390000000,
            "endTime": 1788393600000,
        }
    }
    assert body["evaluators"][0]["variableMapping"] == {
        "input": "trace.input",
        "output": "trace.output",
        "agent_trajectory": "trace.agent_trajectory",
    }
    assert body["tags"] == {
        "campaignId": "campaign-1",
        "runId": "run-1",
        "revision": "7",
        "traceId": TRACE_ID,
        "contentHash": HASH,
        "providerTurnRecordHash": HASH_B,
        "providerTurnSourceHash": HASH_C,
    }


def test_trace_evaluation_readback_requires_trace_source_shape() -> None:
    task = {
        "taskId": "task-1",
        "agentSpace": "space-1",
        "status": "Completed",
        "dataType": "trace",
        "dataFilter": json.dumps(
            {"query": f"traceId='{TRACE_ID}'", "maxRecords": 1}
        ),
        "config": {"dataScope": "trace"},
        "tags": {
            "campaignId": "campaign-1",
            "runId": "run-1",
            "revision": "7",
            **_evidence_binding().tags(),
        },
    }
    runs = {
        "evaluationRuns": [
            {
                "taskId": "task-1",
                "runId": "evaluation-run-1",
                "status": "Completed",
                "totalCount": 1,
                "successCount": 1,
            }
        ]
    }
    client = AgentLoopClient(
        AgentLoopEndpoint("https://agentloop.cn-beijing.aliyuncs.com", "space-1"),
        QueueTransport(
            [
                AgentLoopHTTPResponse(200, json.dumps(task).encode()),
                AgentLoopHTTPResponse(200, json.dumps(runs).encode()),
            ]
        ),
        _lease,
        lambda: "2026-09-03T02:00:00Z",
    )
    result = client.verify_trace_evaluation_task_run(
        AgentLoopScope("campaign-1", "run-1", 7),
        task_id="task-1",
        trace_id=TRACE_ID,
        evidence_binding=_evidence_binding(),
    )
    assert result.status == "API_QUERY_VERIFIED"


@pytest.mark.parametrize(
    "overrides",
    [
        {"dataType": "dataset"},
        {"config": {"dataScope": "dataset"}},
        {"dataFilter": {"query": "traceId='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'", "maxRecords": 1}},
    ],
)
def test_trace_evaluation_readback_rejects_non_trace_source_shape(
    overrides: dict[str, Any],
) -> None:
    task = {
        "taskId": "task-1",
        "agentSpace": "space-1",
        "status": "Completed",
        "dataType": "trace",
        "dataFilter": {"query": f"traceId='{TRACE_ID}'", "maxRecords": 1},
        "config": {"dataScope": "trace"},
        "tags": {
            "campaignId": "campaign-1",
            "runId": "run-1",
            "revision": "7",
            **_evidence_binding().tags(),
        },
    }
    task.update(overrides)
    runs = {
        "evaluationRuns": [
            {"taskId": "task-1", "status": "Completed", "totalCount": 1, "successCount": 1}
        ]
    }
    client = AgentLoopClient(
        AgentLoopEndpoint("https://agentloop.cn-beijing.aliyuncs.com", "space-1"),
        QueueTransport(
            [
                AgentLoopHTTPResponse(200, json.dumps(task).encode()),
                AgentLoopHTTPResponse(200, json.dumps(runs).encode()),
            ]
        ),
        _lease,
        lambda: "2026-09-03T02:00:00Z",
    )
    result = client.verify_trace_evaluation_task_run(
        AgentLoopScope("campaign-1", "run-1", 7),
        task_id="task-1",
        trace_id=TRACE_ID,
        evidence_binding=_evidence_binding(),
    )
    assert result.status == "NOT_VERIFIED"


def test_trace_evaluation_task_rejects_mismatched_or_unbounded_inputs() -> None:
    client = AgentLoopClient(
        AgentLoopEndpoint("https://agentloop.cn-beijing.aliyuncs.com", "space-1"),
        RecordingAgentLoopTransport(),
        _lease,
        lambda: "2026-09-03T02:00:00Z",
    )
    scope = AgentLoopScope("campaign-1", "run-1", 7)
    with pytest.raises(AuthorityError, match="trace_id"):
        client.create_trace_evaluation_task_run(
            scope,
            task_name="trace-task-1",
            trace_id="not-a-trace",
            client_token="client-token-1",
        )
    with pytest.raises(AuthorityError, match="binding"):
        client.create_trace_evaluation_task_run(
            scope,
            task_name="trace-task-1",
            trace_id=TRACE_ID,
            client_token="client-token-1",
            evidence_binding=AgentLoopEvidenceBinding("a" * 32, HASH, HASH_B, HASH_C),
        )
    with pytest.raises(AuthorityError, match="both"):
        client.create_trace_evaluation_task_run(
            scope,
            task_name="trace-task-1",
            trace_id=TRACE_ID,
            client_token="client-token-1",
            start_time_ms=1788390000000,
        )


def test_evaluation_query_keeps_empty_or_wrong_scope_result_not_verified() -> None:
    scope = AgentLoopScope("campaign-1", "run-1", 7)
    task = {
        "taskId": "task-1",
        "agentSpace": "space-1",
        "status": "Completed",
        "evaluators": [{"evaluatorRef": "eval-1"}],
        "tags": {"campaignId": "campaign-1", "runId": "other", "revision": "7"},
    }
    runs = {"evaluationRuns": []}
    client = AgentLoopClient(
        AgentLoopEndpoint("https://agentloop.cn-beijing.aliyuncs.com", "space-1"),
        QueueTransport(
            [
                AgentLoopHTTPResponse(200, json.dumps(task).encode()),
                AgentLoopHTTPResponse(200, json.dumps(runs).encode()),
            ]
        ),
        _lease,
        lambda: "2026-09-03T02:00:00Z",
    )
    result = client.verify_evaluation_task_run(
        scope, task_id="task-1", evidence_binding=_evidence_binding()
    )
    assert result.status == "NOT_VERIFIED"
    assert not result.scope_verified
    assert result.result_count == 0


@pytest.mark.parametrize(
    "missing_tag",
    ["traceId", "contentHash", "providerTurnRecordHash", "providerTurnSourceHash"],
)
def test_evaluation_query_never_verifies_without_every_provider_turn_tag(
    missing_tag: str,
) -> None:
    tags = {
        "campaignId": "campaign-1",
        "runId": "run-1",
        "revision": "7",
        "traceId": TRACE_ID,
        "contentHash": HASH,
        "providerTurnRecordHash": HASH_B,
        "providerTurnSourceHash": HASH_C,
    }
    tags.pop(missing_tag)
    task = {
        "taskId": "task-1",
        "agentSpace": "space-1",
        "status": "Completed",
        "tags": tags,
    }
    runs = {
        "evaluationRuns": [
            {
                "taskId": "task-1",
                "status": "Completed",
                "totalCount": 1,
                "successCount": 1,
            }
        ]
    }
    client = AgentLoopClient(
        AgentLoopEndpoint("https://agentloop.cn-beijing.aliyuncs.com", "space-1"),
        QueueTransport(
            [
                AgentLoopHTTPResponse(200, json.dumps(task).encode()),
                AgentLoopHTTPResponse(200, json.dumps(runs).encode()),
            ]
        ),
        _lease,
        lambda: "2026-09-03T02:00:00Z",
    )
    result = client.verify_evaluation_task_run(
        AgentLoopScope("campaign-1", "run-1", 7),
        task_id="task-1",
        evidence_binding=_evidence_binding(),
    )
    assert result.status == "NOT_VERIFIED"
    assert not result.evidence_verified


def test_evaluation_query_never_verifies_a_mismatched_provider_turn_tag() -> None:
    tags = {
        "campaignId": "campaign-1",
        "runId": "run-1",
        "revision": "7",
        **_evidence_binding().tags(),
        "providerTurnSourceHash": HASH_B,
    }
    task = {
        "taskId": "task-1",
        "agentSpace": "space-1",
        "status": "Completed",
        "tags": tags,
    }
    runs = {
        "evaluationRuns": [
            {
                "taskId": "task-1",
                "status": "Completed",
                "totalCount": 1,
                "successCount": 1,
            }
        ]
    }
    client = AgentLoopClient(
        AgentLoopEndpoint("https://agentloop.cn-beijing.aliyuncs.com", "space-1"),
        QueueTransport(
            [
                AgentLoopHTTPResponse(200, json.dumps(task).encode()),
                AgentLoopHTTPResponse(200, json.dumps(runs).encode()),
            ]
        ),
        _lease,
        lambda: "2026-09-03T02:00:00Z",
    )
    result = client.verify_evaluation_task_run(
        AgentLoopScope("campaign-1", "run-1", 7),
        task_id="task-1",
        evidence_binding=_evidence_binding(),
    )
    assert result.status == "NOT_VERIFIED"
    assert not result.evidence_verified


class XTraceQueue:
    def __init__(self, responses: list[XTraceHTTPResponse]):
        self.responses = responses
        self.calls = 0

    def get_trace(self, **_: Any) -> XTraceHTTPResponse:
        self.calls += 1
        return self.responses.pop(0)


def _trace_body(*, run_id: str = "run-1") -> bytes:
    tags = [
        {"Key": "testweaver.campaign_id", "Value": "campaign-1"},
        {"Key": "testweaver.run_id", "Value": run_id},
        {"Key": "testweaver.pg_revision", "Value": "7"},
        {"Key": "testweaver.content_hash", "Value": HASH},
    ]
    return json.dumps(
        {
            "Spans": {
                "Span": [
                    {
                        "TraceID": "0123456789abcdef0123456789abcdef",
                        "TagEntryList": {"TagEntry": tags},
                    }
                ]
            }
        }
    ).encode()


def test_xtrace_readback_verifies_exact_trace_and_authority_anchors() -> None:
    transport = XTraceQueue([XTraceHTTPResponse(200, _trace_body(), "request-1")])
    receipt = XTraceReadbackClient(
        region="cn-beijing",
        transport=transport,
        credentials=_lease,
        clock=lambda: "2026-09-03T02:00:00Z",
    ).get_trace(
        trace_id="0123456789abcdef0123456789abcdef",
        correlation=XTraceCorrelation("campaign-1", "run-1", 7, HASH),
        max_attempts=1,
    )
    assert receipt.status == "API_QUERY_VERIFIED"
    assert receipt.span_count == 1
    assert all(receipt.authority_anchor_matches.values())
    assert not hasattr(receipt, "response_body")


def test_xtrace_readback_retries_boundedly_and_never_upgrades_partial_match() -> None:
    transport = XTraceQueue(
        [
            XTraceHTTPResponse(200, _trace_body(run_id="wrong")),
            XTraceHTTPResponse(200, _trace_body(run_id="wrong")),
            XTraceHTTPResponse(200, _trace_body(run_id="wrong")),
        ]
    )
    receipt = XTraceReadbackClient(
        region="cn-beijing",
        transport=transport,
        credentials=_lease,
        clock=lambda: "2026-09-03T02:00:00Z",
        sleeper=lambda _: None,
    ).get_trace(
        trace_id="0123456789abcdef0123456789abcdef",
        correlation=XTraceCorrelation("campaign-1", "run-1", 7, HASH),
        max_attempts=3,
        poll_interval_seconds=1,
        max_elapsed_seconds=90,
    )
    assert receipt.status == "NOT_VERIFIED"
    assert receipt.attempt_count == 3
    assert transport.calls == 3
    assert not receipt.authority_anchor_matches["run_id"]


def test_xtrace_permission_denial_is_blocked_without_retry() -> None:
    transport = XTraceQueue([XTraceHTTPResponse(403, b"", error_code="Forbidden")])
    receipt = XTraceReadbackClient(
        region="cn-beijing",
        transport=transport,
        credentials=_lease,
        clock=lambda: "2026-09-03T02:00:00Z",
    ).get_trace(
        trace_id="0123456789abcdef0123456789abcdef",
        correlation=XTraceCorrelation("campaign-1", "run-1", 7, HASH),
        max_attempts=3,
    )
    assert receipt.status == "BLOCKED"
    assert receipt.reason == "PERMISSION_DENIED"
    assert transport.calls == 1


def test_xtrace_accepts_bounded_legacy_thirty_character_trace_id() -> None:
    trace_id = "a" * 30
    body = json.dumps({"Spans": [{"TraceID": trace_id}]}).encode()
    receipt = XTraceReadbackClient(
        region="cn-beijing",
        transport=XTraceQueue([XTraceHTTPResponse(200, body)]),
        credentials=_lease,
        clock=lambda: "2026-09-03T02:00:00Z",
    ).get_trace(
        trace_id=trace_id,
        correlation=XTraceCorrelation("campaign-1", "run-1", 7, HASH),
    )
    assert receipt.status == "NOT_VERIFIED"
    assert receipt.trace_id_matched
