"""Bounded AgentLoop Dataset/Evaluator/EvaluationTask HTTP client.

The request shapes follow the inherited Alibaba Cloud AgentLoop integration.
Credentials are leased through a callback and never enter receipts.  There is
intentionally no delete, resource lifecycle controller, observer, or LIVE
classification API here.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

from testweaver.authority import AuthorityError, digest_bytes, validate_ref
from testweaver.contracts.validator import canonical_hash


@dataclass(frozen=True, slots=True, repr=False)
class AgentLoopCredentialLease:
    protected_ref: str
    material: object

    def __repr__(self) -> str:
        return f"AgentLoopCredentialLease(protected_ref={self.protected_ref!r}, material=<redacted>)"


CredentialCallback = Callable[[], AgentLoopCredentialLease]


@dataclass(frozen=True, slots=True)
class AgentLoopHTTPResponse:
    status_code: int
    body: bytes
    request_id: str | None = None
    error_code: str | None = None


class AgentLoopTransport(Protocol):
    def request(
        self,
        *,
        method: str,
        endpoint: str,
        path: str,
        query: Mapping[str, str],
        body: bytes | None,
        credential: object,
    ) -> AgentLoopHTTPResponse: ...


@dataclass(frozen=True, slots=True)
class AgentLoopEndpoint:
    endpoint: str
    agent_space: str


@dataclass(frozen=True, slots=True)
class AgentLoopScope:
    campaign_id: str
    run_id: str
    revision: int

    def validate(self) -> None:
        validate_ref(self.campaign_id, "campaign_id")
        validate_ref(self.run_id, "run_id")
        if type(self.revision) is not int or self.revision < 1:
            raise AuthorityError("AgentLoop scope revision must be positive")


@dataclass(frozen=True, slots=True)
class AgentLoopReceipt:
    operation: str
    status: str
    status_code: int | None
    request_hash: str
    response_hash: str | None
    endpoint_hash: str
    path_hash: str
    scope_hash: str
    credential_ref_hash: str | None
    resource_ref_hash: str | None
    request_id_hash: str | None
    error_category: str | None
    observed_at: str
    content_hash: str

    def __post_init__(self) -> None:
        validate_ref(self.operation, "agentloop_operation")
        validate_ref(self.observed_at, "observed_at")
        if self.status not in {"PASS", "BLOCKED"}:
            raise AuthorityError("AgentLoop receipt status is invalid")
        if self.status_code is not None and (
            type(self.status_code) is not int or not 100 <= self.status_code <= 599
        ):
            raise AuthorityError("AgentLoop status code is invalid")
        if self.error_category is not None:
            validate_ref(self.error_category, "error_category")
        for field in (
            "request_hash",
            "endpoint_hash",
            "path_hash",
            "scope_hash",
            "content_hash",
        ):
            from testweaver.authority import validate_hash

            validate_hash(getattr(self, field), field)
        for field in (
            "response_hash",
            "credential_ref_hash",
            "resource_ref_hash",
            "request_id_hash",
        ):
            value = getattr(self, field)
            if value is not None:
                from testweaver.authority import validate_hash

                validate_hash(value, field)
        expected = canonical_hash(
            {
                "operation": self.operation,
                "status": self.status,
                "status_code": self.status_code,
                "request_hash": self.request_hash,
                "response_hash": self.response_hash,
                "endpoint_hash": self.endpoint_hash,
                "path_hash": self.path_hash,
                "scope_hash": self.scope_hash,
                "credential_ref_hash": self.credential_ref_hash,
                "resource_ref_hash": self.resource_ref_hash,
                "request_id_hash": self.request_id_hash,
                "error_category": self.error_category,
                "observed_at": self.observed_at,
            }
        )
        if self.content_hash != expected:
            raise AuthorityError("AgentLoop receipt is not sealed")

    @classmethod
    def create(cls, **values: Any) -> AgentLoopReceipt:
        return cls(**values, content_hash=canonical_hash(values))


@dataclass(frozen=True, slots=True)
class AgentLoopCallResult:
    receipt: AgentLoopReceipt
    resource_ref: str | None = None


@dataclass(slots=True)
class AgentLoopClient:
    config: AgentLoopEndpoint
    transport: AgentLoopTransport
    credentials: CredentialCallback
    clock: Callable[[], str]

    def create_dataset(
        self,
        scope: AgentLoopScope,
        *,
        dataset_name: str,
        description: str,
        client_token: str,
    ) -> AgentLoopCallResult:
        body = {
            "datasetName": dataset_name,
            "description": description,
            "schema": {"content": {"type": "text", "chn": False, "embedding": "false"}},
        }
        return self._call(
            scope,
            operation="CreateDataset",
            method="POST",
            path=f"/agentspace/{_quoted(self.config.agent_space)}/dataset",
            query={"clientToken": client_token},
            body=body,
            resource_ref=dataset_name,
        )

    def upsert_dataset_rows(
        self,
        scope: AgentLoopScope,
        *,
        dataset_name: str,
        item_hashes: Sequence[str],
        client_token: str,
    ) -> AgentLoopCallResult:
        if not item_hashes:
            raise AuthorityError("at least one hash-bound Dataset row is required")
        for item_hash in item_hashes:
            from testweaver.authority import validate_hash

            validate_hash(item_hash, "dataset_item_hash")
        return self._call(
            scope,
            operation="AddDatasetData",
            method="POST",
            path=f"/agentspace/{_quoted(self.config.agent_space)}/dataset/{_quoted(dataset_name)}/rows",
            query={"clientToken": client_token},
            body={"dataArray": [{"content": value} for value in item_hashes]},
            resource_ref=dataset_name,
        )

    def get_dataset(
        self, scope: AgentLoopScope, *, dataset_name: str
    ) -> AgentLoopCallResult:
        return self._call(
            scope,
            operation="GetDataset",
            method="GET",
            path=(
                f"/agentspace/{_quoted(self.config.agent_space)}/dataset/"
                f"{_quoted(dataset_name)}"
            ),
            query={},
            body=None,
            resource_ref=dataset_name,
        )

    def create_evaluator(
        self,
        scope: AgentLoopScope,
        *,
        evaluator_name: str,
        metric_name: str,
        prompt: str,
        client_token: str,
    ) -> AgentLoopCallResult:
        return self._call(
            scope,
            operation="CreateEvaluator",
            method="POST",
            path=f"/api/v1/evaluators/{_quoted(self.config.agent_space)}",
            query={"clientToken": client_token},
            body={
                "name": evaluator_name,
                "displayName": evaluator_name,
                "type": "AGENT",
                "description": "TestWeaver bounded evaluator.",
                "metricName": metric_name,
                "version": "1.0.0",
                "versionDescription": "TestWeaver bounded version",
                "config": {"prompt": prompt, "variables": [{"name": "input"}]},
                "annotations": ["__en"],
                "properties": {"agentEvaluatorMode": "raw_prompt"},
            },
            resource_ref=evaluator_name,
        )

    def get_evaluator(
        self, scope: AgentLoopScope, *, evaluator_name: str, version: str = "1.0.0"
    ) -> AgentLoopCallResult:
        return self._call(
            scope,
            operation="GetEvaluator",
            method="GET",
            path=(
                f"/api/v1/evaluators/{_quoted(self.config.agent_space)}/"
                f"{_quoted(evaluator_name)}"
            ),
            query={"version": version},
            body=None,
            resource_ref=evaluator_name,
        )

    def create_evaluation_task_run(
        self,
        scope: AgentLoopScope,
        *,
        task_name: str,
        dataset_name: str,
        evaluator_ref: str,
        data_type: str,
        data_filter: Mapping[str, Any],
        variable_mapping: Mapping[str, Any],
        client_token: str,
    ) -> AgentLoopCallResult:
        """Create a batch task with official backfill enabled (the bounded run operation)."""

        return self._call(
            scope,
            operation="CreateEvaluationTask",
            method="POST",
            path=f"/api/v1/evaluation-task/{_quoted(self.config.agent_space)}",
            query={"clientToken": client_token},
            body={
                "taskName": task_name,
                "taskMode": "batch",
                "dataType": data_type,
                "dataFilter": dict(data_filter),
                "evaluators": [
                    {
                        "evaluatorRef": evaluator_ref,
                        "variableMapping": dict(variable_mapping),
                    }
                ],
                "config": {"datasetName": dataset_name},
                "channel": "default",
                "runStrategies": {"backfill": {"enabled": True}},
                "tags": {
                    "campaignId": scope.campaign_id,
                    "runId": scope.run_id,
                    "revision": str(scope.revision),
                },
                "description": "TestWeaver bounded real-run evaluation task.",
            },
            resource_ref=task_name,
            response_resource_keys=("taskId", "id"),
        )

    def get_evaluation_task(
        self, scope: AgentLoopScope, *, task_id: str
    ) -> AgentLoopCallResult:
        return self._call(
            scope,
            operation="GetEvaluationTask",
            method="GET",
            path=f"/api/v1/evaluation-task/{_quoted(self.config.agent_space)}/{_quoted(task_id)}",
            query={},
            body=None,
            resource_ref=task_id,
        )

    def get_evaluation_runs(
        self, scope: AgentLoopScope, *, task_id: str, max_results: int = 10
    ) -> AgentLoopCallResult:
        if not 1 <= max_results <= 100:
            raise AuthorityError("max_results must be between 1 and 100")
        return self._call(
            scope,
            operation="ListEvaluationRuns",
            method="GET",
            path=(
                f"/api/v1/evaluation-task/{_quoted(self.config.agent_space)}/"
                f"{_quoted(task_id)}/runs"
            ),
            query={"maxResults": str(max_results)},
            body=None,
            resource_ref=task_id,
        )

    def _call(
        self,
        scope: AgentLoopScope,
        *,
        operation: str,
        method: str,
        path: str,
        query: Mapping[str, str],
        body: Mapping[str, Any] | None,
        resource_ref: str,
        response_resource_keys: tuple[str, ...] = (),
    ) -> AgentLoopCallResult:
        scope.validate()
        validate_ref(self.config.endpoint, "agentloop_endpoint")
        validate_ref(self.config.agent_space, "agent_space")
        validate_ref(resource_ref, "agentloop_resource_ref")
        request_value = {
            "operation": operation,
            "method": method,
            "path": path,
            "query": dict(query),
            "body": body,
            "scope": {
                "campaign_id": scope.campaign_id,
                "run_id": scope.run_id,
                "revision": scope.revision,
            },
        }
        request_body = (
            None
            if body is None
            else json.dumps(
                body,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )
        request_hash = canonical_hash(request_value)
        endpoint_hash = digest_bytes(self.config.endpoint.encode())
        path_hash = digest_bytes(path.encode())
        scope_hash = canonical_hash(request_value["scope"])
        resource_hash = digest_bytes(resource_ref.encode())
        observed_at = self.clock()
        try:
            lease = self.credentials()
            validate_ref(lease.protected_ref, "credential_protected_ref")
        except Exception:  # noqa: BLE001 - credential callback is an external boundary
            receipt = AgentLoopReceipt.create(
                operation=operation,
                status="BLOCKED",
                status_code=None,
                request_hash=request_hash,
                response_hash=None,
                endpoint_hash=endpoint_hash,
                path_hash=path_hash,
                scope_hash=scope_hash,
                credential_ref_hash=None,
                resource_ref_hash=resource_hash,
                request_id_hash=None,
                error_category="CREDENTIAL_UNAVAILABLE",
                observed_at=observed_at,
            )
            return AgentLoopCallResult(receipt)
        credential_ref_hash = digest_bytes(lease.protected_ref.encode())
        try:
            response = self.transport.request(
                method=method,
                endpoint=self.config.endpoint,
                path=path,
                query=query,
                body=request_body,
                credential=lease.material,
            )
        except Exception:  # noqa: BLE001 - transport failures are normalized to BLOCKED
            receipt = AgentLoopReceipt.create(
                operation=operation,
                status="BLOCKED",
                status_code=None,
                request_hash=request_hash,
                response_hash=None,
                endpoint_hash=endpoint_hash,
                path_hash=path_hash,
                scope_hash=scope_hash,
                credential_ref_hash=credential_ref_hash,
                resource_ref_hash=resource_hash,
                request_id_hash=None,
                error_category="ENDPOINT_UNAVAILABLE",
                observed_at=observed_at,
            )
            return AgentLoopCallResult(receipt)
        status = "PASS" if 200 <= response.status_code < 300 else "BLOCKED"
        if response.status_code in {401, 403}:
            category = "PERMISSION_DENIED"
        elif response.status_code == 404:
            category = "ENDPOINT_NOT_FOUND"
        elif status == "BLOCKED":
            category = "API_REJECTED"
        else:
            category = None
        returned_ref = resource_ref
        if status == "PASS" and response_resource_keys:
            try:
                returned_ref = _resource_ref_from_response(
                    response.body, response_resource_keys
                )
            except AuthorityError:
                status = "BLOCKED"
                category = "RESPONSE_CONTRACT_INVALID"
        receipt = AgentLoopReceipt.create(
            operation=operation,
            status=status,
            status_code=response.status_code,
            request_hash=request_hash,
            response_hash=digest_bytes(response.body),
            endpoint_hash=endpoint_hash,
            path_hash=path_hash,
            scope_hash=scope_hash,
            credential_ref_hash=credential_ref_hash,
            resource_ref_hash=resource_hash,
            request_id_hash=(
                digest_bytes(response.request_id.encode())
                if response.request_id
                else None
            ),
            error_category=category,
            observed_at=observed_at,
        )
        return AgentLoopCallResult(receipt, returned_ref if status == "PASS" else None)


def _quoted(value: str) -> str:
    validate_ref(value, "agentloop_path_component")
    return quote(value, safe="")


def _resource_ref_from_response(body: bytes, keys: tuple[str, ...]) -> str:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthorityError(
            "successful AgentLoop create response is not JSON"
        ) from exc
    if not isinstance(value, Mapping):
        raise AuthorityError("successful AgentLoop create response must be an object")
    for key in keys:
        candidate = value.get(key)
        if candidate is not None:
            return validate_ref(candidate, f"agentloop_response_{key}")
    raise AuthorityError("successful AgentLoop create response lacks its resource ID")
