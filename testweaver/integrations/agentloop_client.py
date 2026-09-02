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
from urllib.parse import quote, urlsplit

from testweaver.authority import AuthorityError, digest_bytes, validate_ref
from testweaver.contracts.validator import canonical_hash


class AgentLoopCredentialLease:
    """Runtime-only credential lease that cannot be expanded by dataclasses.asdict."""

    __slots__ = ("_material", "protected_ref")

    def __init__(self, protected_ref: str, material: object) -> None:
        self.protected_ref = protected_ref
        self._material = material

    @property
    def material(self) -> object:
        return self._material

    def __repr__(self) -> str:
        return f"AgentLoopCredentialLease(protected_ref={self.protected_ref!r}, material=<redacted>)"

    def as_dict(self) -> dict[str, str]:
        return {"protected_ref": self.protected_ref, "material": "<redacted>"}


CredentialCallback = Callable[[], AgentLoopCredentialLease]


@dataclass(frozen=True, slots=True, repr=False)
class AgentLoopHTTPResponse:
    status_code: int
    body: bytes
    request_id: str | None = None
    error_code: str | None = None

    def __repr__(self) -> str:
        return (
            f"AgentLoopHTTPResponse(status_code={self.status_code!r}, body=<redacted>, "
            f"request_id_present={self.request_id is not None!r}, "
            f"error_code={self.error_code!r})"
        )


class AgentLoopTransport(Protocol):
    def request(
        self,
        *,
        operation: str,
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

    def __post_init__(self) -> None:
        _validate_agentloop_endpoint(self.endpoint)
        validate_ref(self.agent_space, "agent_space")


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
        if self.status not in {"API_ACCEPTED", "BLOCKED"}:
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
    response_summary: AgentLoopResponseSummary | None = None


@dataclass(frozen=True, slots=True)
class AgentLoopResponseSummary:
    ownership_verified: bool
    scope_verified: bool
    terminal: bool
    completed: bool
    result_count: int
    successful_result_count: int


@dataclass(frozen=True, slots=True)
class AgentLoopQueryVerification:
    status: str
    task_receipt_hash: str
    runs_receipt_hash: str
    ownership_verified: bool
    scope_verified: bool
    terminal: bool
    result_count: int
    successful_result_count: int
    observed_at: str
    content_hash: str

    def __post_init__(self) -> None:
        if self.status not in {"API_QUERY_VERIFIED", "NOT_VERIFIED", "BLOCKED"}:
            raise AuthorityError("AgentLoop query verification status is invalid")
        if self.result_count < 0 or self.successful_result_count < 0:
            raise AuthorityError("AgentLoop query result counts must be non-negative")
        expected = canonical_hash(
            {
                "status": self.status,
                "task_receipt_hash": self.task_receipt_hash,
                "runs_receipt_hash": self.runs_receipt_hash,
                "ownership_verified": self.ownership_verified,
                "scope_verified": self.scope_verified,
                "terminal": self.terminal,
                "result_count": self.result_count,
                "successful_result_count": self.successful_result_count,
                "observed_at": self.observed_at,
            }
        )
        if self.content_hash != expected:
            raise AuthorityError("AgentLoop query verification is not sealed")


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
        hidden_gold_visible: bool,
        client_token: str,
    ) -> AgentLoopCallResult:
        """Create a batch task with official backfill enabled (the bounded run operation)."""

        expected_filter = {"datasetName": dataset_name, "maxRecords": 1}
        if data_type != "dataset":
            raise AuthorityError("AgentLoop evaluation data_type must be dataset")
        if dict(data_filter) != expected_filter:
            raise AuthorityError(
                "AgentLoop evaluation must select exactly one row from its Dataset"
            )
        if dict(variable_mapping) != {"input": "content"}:
            raise AuthorityError(
                "AgentLoop evaluator input must map only to Dataset content"
            )
        if hidden_gold_visible is not False:
            raise AuthorityError(
                "AgentLoop candidate evaluation must keep hidden Gold isolated"
            )

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
                "dataFilter": expected_filter,
                "evaluators": [
                    {
                        "evaluatorRef": evaluator_ref,
                        "variableMapping": {"input": "content"},
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

    def verify_evaluation_task_run(
        self,
        scope: AgentLoopScope,
        *,
        task_id: str,
        max_results: int = 10,
    ) -> AgentLoopQueryVerification:
        """Read back task ownership/scope and a completed non-empty run.

        The two HTTP GET operations retain only their sealed receipts and
        bounded summaries. A successful POST or a bare HTTP 2xx can never
        reach ``API_QUERY_VERIFIED`` through this method.
        """

        task = self.get_evaluation_task(scope, task_id=task_id)
        runs = self.get_evaluation_runs(scope, task_id=task_id, max_results=max_results)
        task_summary = task.response_summary or _EMPTY_SUMMARY
        runs_summary = runs.response_summary or _EMPTY_SUMMARY
        blocked = task.receipt.status == "BLOCKED" or runs.receipt.status == "BLOCKED"
        ownership = task_summary.ownership_verified and runs_summary.ownership_verified
        scoped = task_summary.scope_verified
        terminal = (
            task_summary.terminal
            and task_summary.completed
            and runs_summary.terminal
            and runs_summary.completed
        )
        result_count = runs_summary.result_count
        successful = runs_summary.successful_result_count
        verified = (
            ownership and scoped and terminal and result_count > 0 and successful > 0
        )
        status = (
            "BLOCKED"
            if blocked
            else "API_QUERY_VERIFIED"
            if verified
            else "NOT_VERIFIED"
        )
        values = {
            "status": status,
            "task_receipt_hash": task.receipt.content_hash,
            "runs_receipt_hash": runs.receipt.content_hash,
            "ownership_verified": ownership,
            "scope_verified": scoped,
            "terminal": terminal,
            "result_count": result_count,
            "successful_result_count": successful,
            "observed_at": self.clock(),
        }
        return AgentLoopQueryVerification(**values, content_hash=canonical_hash(values))

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
                operation=operation,
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
        status = "API_ACCEPTED" if 200 <= response.status_code < 300 else "BLOCKED"
        if response.status_code in {401, 403}:
            category = "PERMISSION_DENIED"
        elif response.status_code == 404:
            category = "ENDPOINT_NOT_FOUND"
        elif status == "BLOCKED":
            category = "API_REJECTED"
        else:
            category = None
        returned_ref = resource_ref
        if status == "API_ACCEPTED" and response_resource_keys:
            try:
                returned_ref = _resource_ref_from_response(
                    response.body, response_resource_keys
                )
            except AuthorityError:
                returned_ref = None
                category = "RESPONSE_CONTRACT_INVALID"
        response_summary = None
        if status == "API_ACCEPTED" and method == "GET":
            response_summary = _response_summary(
                operation=operation,
                body=response.body,
                agent_space=self.config.agent_space,
                resource_ref=resource_ref,
                scope=scope,
            )
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
        return AgentLoopCallResult(
            receipt,
            returned_ref if status == "API_ACCEPTED" else None,
            response_summary,
        )


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


_EMPTY_SUMMARY = AgentLoopResponseSummary(False, False, False, False, 0, 0)


def _response_summary(
    *,
    operation: str,
    body: bytes,
    agent_space: str,
    resource_ref: str,
    scope: AgentLoopScope,
) -> AgentLoopResponseSummary:
    if len(body) > 4 * 1024 * 1024:
        return _EMPTY_SUMMARY
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _EMPTY_SUMMARY
    if not isinstance(value, Mapping):
        return _EMPTY_SUMMARY
    if operation == "GetEvaluationTask":
        task = value.get("evaluationTask", value)
        if not isinstance(task, Mapping):
            return _EMPTY_SUMMARY
        tags = task.get("tags")
        expected_tags = {
            "campaignId": scope.campaign_id,
            "runId": scope.run_id,
            "revision": str(scope.revision),
        }
        status = task.get("status")
        return AgentLoopResponseSummary(
            ownership_verified=(
                task.get("agentSpace") == agent_space
                and task.get("taskId") == resource_ref
            ),
            scope_verified=isinstance(tags, Mapping)
            and all(
                tags.get(key) == expected for key, expected in expected_tags.items()
            ),
            terminal=status in {"Completed", "Failed", "Terminated", "Deleted"},
            completed=status == "Completed",
            result_count=0,
            successful_result_count=0,
        )
    if operation == "ListEvaluationRuns":
        rows = value.get("evaluationRuns")
        if not isinstance(rows, list):
            return _EMPTY_SUMMARY
        matching = [
            row
            for row in rows
            if isinstance(row, Mapping) and row.get("taskId") == resource_ref
        ]
        completed_rows = [row for row in matching if row.get("status") == "Completed"]
        result_count = sum(
            _nonnegative_int(row.get("totalCount")) for row in completed_rows
        )
        successful = sum(
            _nonnegative_int(row.get("successCount")) for row in completed_rows
        )
        statuses = {row.get("status") for row in matching}
        return AgentLoopResponseSummary(
            ownership_verified=bool(matching),
            scope_verified=False,
            terminal=bool(matching)
            and statuses.issubset({"Completed", "Failed", "Terminated"}),
            completed=bool(completed_rows),
            result_count=result_count,
            successful_result_count=successful,
        )
    if operation == "GetDataset":
        schema = value.get("schema")
        return AgentLoopResponseSummary(
            ownership_verified=value.get("agentSpace") == agent_space
            and value.get("datasetName") == resource_ref,
            scope_verified=False,
            terminal=True,
            completed=True,
            result_count=1 if isinstance(schema, Mapping) and bool(schema) else 0,
            successful_result_count=0,
        )
    if operation == "GetEvaluator":
        evaluator = value.get("evaluator")
        if not isinstance(evaluator, Mapping):
            return _EMPTY_SUMMARY
        return AgentLoopResponseSummary(
            ownership_verified=evaluator.get("agentSpace") == agent_space
            and evaluator.get("name") == resource_ref,
            scope_verified=False,
            terminal=True,
            completed=True,
            result_count=1 if evaluator else 0,
            successful_result_count=0,
        )
    return _EMPTY_SUMMARY


def _nonnegative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _validate_agentloop_endpoint(endpoint: str) -> None:
    parsed = urlsplit(endpoint)
    hostname = parsed.hostname or ""
    labels = hostname.split(".")
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or len(labels) != 4
        or labels[0] != "agentloop"
        or not labels[1]
        or any(
            not (character.islower() or character.isdigit() or character == "-")
            for character in labels[1]
        )
        or labels[-2:] != ["aliyuncs", "com"]
    ):
        raise AuthorityError(
            "AgentLoop endpoint must be a canonical Alibaba Cloud HTTPS endpoint"
        )
