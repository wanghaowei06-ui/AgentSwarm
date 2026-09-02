from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from testweaver.authority import AuthorityError
from testweaver.integrations.agentloop_client import (
    AgentLoopClient,
    AgentLoopCredentialLease,
    AgentLoopEndpoint,
    AgentLoopHTTPResponse,
    AgentLoopScope,
)
from testweaver.integrations.tea_transport import (
    AlibabaCloudCredential,
    TeaAgentLoopTransport,
    load_protected_csv_credential,
)
from testweaver.integrations.xtrace_readback import (
    XTraceCorrelation,
    XTraceHTTPResponse,
    XTraceReadbackClient,
)

HASH = "sha256:" + "a" * 64


class QueueTransport:
    def __init__(self, responses: list[AgentLoopHTTPResponse]):
        self.responses = responses

    def request(self, **_: Any) -> AgentLoopHTTPResponse:
        return self.responses.pop(0)


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


def test_protected_csv_loader_rejects_unsafe_files(tmp_path: Path) -> None:
    path = tmp_path / "AccessKey.csv"
    path.write_text("AccessKey ID,AccessKey Secret\nid,secret\n", encoding="utf-8")
    path.chmod(0o600)
    loaded = load_protected_csv_credential(path)
    assert "id" not in repr(loaded)
    path.chmod(0o644)
    with pytest.raises(AuthorityError, match="owner-only"):
        load_protected_csv_credential(path)


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


def test_evaluation_query_requires_ownership_scope_terminal_and_nonempty_result() -> (
    None
):
    scope = AgentLoopScope("campaign-1", "run-1", 7)
    task = {
        "taskId": "task-1",
        "agentSpace": "space-1",
        "status": "Completed",
        "evaluators": [{"evaluatorRef": "eval-1"}],
        "tags": {"campaignId": "campaign-1", "runId": "run-1", "revision": "7"},
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
    verified = client.verify_evaluation_task_run(scope, task_id="task-1")
    assert verified.status == "API_QUERY_VERIFIED"
    assert verified.ownership_verified
    assert verified.scope_verified
    assert verified.terminal
    assert verified.result_count == 1
    assert verified.successful_result_count == 1


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
    result = client.verify_evaluation_task_run(scope, task_id="task-1")
    assert result.status == "NOT_VERIFIED"
    assert not result.scope_verified
    assert result.result_count == 0


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
