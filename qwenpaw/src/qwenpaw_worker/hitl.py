"""AgentTeams persistence bridge for QwenPaw approvals.

QwenPaw keeps the live approval Future in memory.  This module keeps the
approval record and its first terminal decision in an atomic, redacted JSON
file, then installs a small compatibility layer during AgentTeams plugin
startup.  The bridge deliberately does not serialize Python Futures or tool
callables; a process restart can restore the approval control record, while a
lost in-flight task still needs the runtime's normal replay path.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import copy
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

HITL_STATE_FILE_NAME = "agentteams-hitl.json"
HITL_STATE_VERSION = 1
DEFAULT_APPROVAL_TIMEOUT_SECONDS = 24 * 60 * 60.0
MAX_COMPLETED_RECORDS = 500
COMPLETED_RECORD_MAX_AGE_SECONDS = 3600.0
MAX_PENDING_RECORDS = 200
NOTIFICATION_INITIAL_DELAY_SECONDS = 0.25
NOTIFICATION_MAX_DELAY_SECONDS = 30.0

_SECRET_KEY_RE = re.compile(
    r"(?:token|secret|password|passwd|authorization|api[_-]?key|credential|private[_-]?key)",
    re.IGNORECASE,
)
_SECRET_TEXT_RE = re.compile(
    r"(?P<key>token|secret|password|passwd|authorization|api[_-]?key|credential|private[_-]?key)"
    r"(?P<separator>\s*[:=]\s*)(?P<value>[^\s,;]+)",
    re.IGNORECASE,
)


def hitl_state_path() -> Path:
    """Return the configured per-worker durable HITL state path."""

    configured = os.environ.get("AGENTTEAMS_HITL_STATE_PATH", "").strip()
    if configured:
        return Path(configured)
    working_dir = os.environ.get("QWENPAW_WORKING_DIR", "").strip()
    root = Path(working_dir) if working_dir else Path.cwd()
    return root / HITL_STATE_FILE_NAME


def _json_safe(value: Any, *, key: str = "", omit_private: bool = False) -> Any:
    """Make approval metadata JSON-safe without copying credentials."""

    if _SECRET_KEY_RE.search(key):
        return "[redacted]"
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            child_key = str(raw_key)
            if omit_private and child_key.startswith("_") and child_key != "_spawn_subagent":
                continue
            result[child_key] = _json_safe(
                raw_value,
                key=child_key,
                omit_private=omit_private,
            )
        return result
    if isinstance(value, (list, tuple)):
        return [
            _json_safe(item, omit_private=omit_private)
            for item in value
        ]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return f"<{type(value).__name__}>"


def _redact_text(value: str) -> str:
    """Redact common key/value secret forms in a user-facing summary."""

    return _SECRET_TEXT_RE.sub(
        lambda match: f"{match.group('key')}{match.group('separator')}[redacted]",
        value[:8192],
    )


def _approval_metadata(pending: Any) -> dict[str, Any]:
    """Convert one QwenPaw PendingApproval into a durable record."""

    timeout_seconds = float(getattr(pending, "timeout_seconds", 0) or 0)
    created_at = float(getattr(pending, "created_at", time.time()))
    scope = getattr(getattr(pending, "scope", None), "value", None)
    return {
        "request_id": str(getattr(pending, "request_id", "")),
        "session_id": str(getattr(pending, "session_id", "")),
        "root_session_id": str(getattr(pending, "root_session_id", "")),
        "owner_agent_id": str(getattr(pending, "owner_agent_id", "")),
        "user_id": str(getattr(pending, "user_id", "")),
        "channel": str(getattr(pending, "channel", "")),
        "agent_id": str(getattr(pending, "agent_id", "")),
        "tool_name": str(getattr(pending, "tool_name", "")),
        "created_at": created_at,
        "timeout_seconds": timeout_seconds,
        "expires_at": (
            created_at + timeout_seconds if timeout_seconds > 0 else None
        ),
        "status": str(getattr(pending, "status", "pending")),
        "resolved_at": getattr(pending, "resolved_at", None),
        "result_summary": _redact_text(
            str(getattr(pending, "result_summary", "")),
        ),
        "findings_count": int(getattr(pending, "findings_count", 0) or 0),
        "severity": str(getattr(pending, "severity", "medium")),
        "extra": _json_safe(
            getattr(pending, "extra", {}) or {},
            omit_private=True,
        ),
        "scope": scope,
        "notification_status": "pending",
        "updated_at": time.time(),
    }


class PersistentApprovalStore:
    """Small atomic JSON store for one worker's approval control records."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._records = self._read()

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                "Ignoring invalid HITL state file path=%s error_type=%s",
                self.path,
                type(exc).__name__,
            )
            return {}

        if not isinstance(payload, dict) or payload.get("version") != HITL_STATE_VERSION:
            logger.warning("Ignoring unsupported HITL state file path=%s", self.path)
            return {}
        records = payload.get("records")
        if not isinstance(records, dict):
            return {}
        return {
            str(request_id): dict(record)
            for request_id, record in records.items()
            if isinstance(record, dict)
        }

    def _write_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=str(self.path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(
                    {
                        "version": HITL_STATE_VERSION,
                        "records": self._records,
                    },
                    stream,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.path)
            os.chmod(self.path, 0o600)
        except Exception:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _prune_locked(self, now: float) -> None:
        completed = [
            (request_id, record)
            for request_id, record in self._records.items()
            if record.get("status") != "pending"
        ]
        stale_ids = [
            request_id
            for request_id, record in completed
            if now - float(record.get("updated_at") or record.get("resolved_at") or now)
            > COMPLETED_RECORD_MAX_AGE_SECONDS
        ]
        for request_id in stale_ids:
            self._records.pop(request_id, None)

        remaining_completed = [
            (request_id, record)
            for request_id, record in self._records.items()
            if record.get("status") != "pending"
        ]
        if len(remaining_completed) > MAX_COMPLETED_RECORDS:
            remaining_completed.sort(
                key=lambda item: float(item[1].get("updated_at") or 0),
            )
            for request_id, _record in remaining_completed[:-MAX_COMPLETED_RECORDS]:
                self._records.pop(request_id, None)

        pending = [
            (request_id, record)
            for request_id, record in self._records.items()
            if record.get("status") == "pending"
        ]
        if len(pending) > MAX_PENDING_RECORDS:
            pending.sort(key=lambda item: float(item[1].get("created_at") or 0))
            for request_id, _record in pending[:-MAX_PENDING_RECORDS]:
                self._records.pop(request_id, None)

    def record_pending(self, pending: Any) -> None:
        """Persist a newly created pending approval."""

        record = _approval_metadata(pending)
        request_id = record["request_id"]
        with self._lock:
            previous = self._records.get(request_id, {})
            record["notification_status"] = previous.get(
                "notification_status",
                "pending",
            )
            self._records[request_id] = record
            self._prune_locked(time.time())
            self._write_locked()

    def record_resolution(
        self,
        request_id: str,
        decision: str,
        *,
        resolved_at: float | None = None,
        scope: str | None = None,
    ) -> bool:
        """Persist the first terminal decision for a request."""

        with self._lock:
            record = self._records.get(request_id)
            if record is None or record.get("status") != "pending":
                return False
            record["status"] = decision
            record["resolved_at"] = resolved_at or time.time()
            record["updated_at"] = time.time()
            if scope is not None:
                record["scope"] = scope
            self._prune_locked(time.time())
            self._write_locked()
            return True

    def record_notification(self, request_id: str, status: str) -> None:
        """Record notification delivery state without changing approval state."""

        with self._lock:
            record = self._records.get(request_id)
            if record is None:
                return
            record["notification_status"] = status
            record["updated_at"] = time.time()
            self._write_locked()

    def expire_due(self, now: float | None = None) -> list[str]:
        """Mark all expired pending records as timeout and return their IDs."""

        now = now or time.time()
        expired: list[str] = []
        changed = False
        with self._lock:
            for request_id, record in self._records.items():
                expires_at = record.get("expires_at")
                if (
                    record.get("status") == "pending"
                    and expires_at is not None
                    and float(expires_at) <= now
                ):
                    record["status"] = "timeout"
                    record["resolved_at"] = now
                    record["updated_at"] = now
                    expired.append(request_id)
                    changed = True
            if changed:
                self._prune_locked(now)
                self._write_locked()
        return expired

    def pending_records(self, now: float | None = None) -> list[dict[str, Any]]:
        """Return non-expired pending records sorted by creation time."""

        self.expire_due(now)
        with self._lock:
            records = [
                copy.deepcopy(record)
                for record in self._records.values()
                if record.get("status") == "pending"
            ]
        return sorted(records, key=lambda record: float(record.get("created_at") or 0))

    def get(self, request_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._records.get(request_id)
            return copy.deepcopy(record) if record is not None else None


def _configured_timeout(requested: float) -> float:
    raw = os.environ.get("AGENTTEAMS_HITL_APPROVAL_TIMEOUT_SECONDS", "").strip()
    if raw:
        try:
            value = float(raw)
        except ValueError as exc:
            raise RuntimeError(
                "AGENTTEAMS_HITL_APPROVAL_TIMEOUT_SECONDS must be numeric",
            ) from exc
        if value < 0:
            raise RuntimeError(
                "AGENTTEAMS_HITL_APPROVAL_TIMEOUT_SECONDS must be non-negative",
            )
        return value
    return max(float(requested or 0), DEFAULT_APPROVAL_TIMEOUT_SECONDS)


def _decision_value(decision: Any) -> str:
    return str(getattr(decision, "value", decision))


def _scope_value(scope: Any) -> str | None:
    value = getattr(scope, "value", None)
    return str(value) if value is not None else None


def _install_instance_state(service: Any) -> None:
    if not hasattr(service, "_agentteams_hitl_store"):
        service._agentteams_hitl_store = PersistentApprovalStore(hitl_state_path())
        service._agentteams_hitl_restored = False
        service._agentteams_hitl_notification_tasks = {}
        service._agentteams_hitl_expiry_tasks = {}


def _restore_pending(service: Any) -> None:
    _install_instance_state(service)
    if getattr(service, "_agentteams_hitl_restored", False):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    from qwenpaw.app.approvals.service import PendingApproval
    from qwenpaw.security.tool_guard.approval import ApprovalScope

    store: PersistentApprovalStore = service._agentteams_hitl_store
    for record in store.pending_records():
        request_id = str(record.get("request_id") or "")
        if not request_id or request_id in service._pending:
            continue
        scope = None
        raw_scope = record.get("scope")
        if raw_scope:
            try:
                scope = ApprovalScope(str(raw_scope))
            except ValueError:
                scope = None
        pending = PendingApproval(
            request_id=request_id,
            session_id=str(record.get("session_id") or ""),
            root_session_id=str(record.get("root_session_id") or ""),
            owner_agent_id=str(record.get("owner_agent_id") or ""),
            user_id=str(record.get("user_id") or ""),
            channel=str(record.get("channel") or ""),
            agent_id=str(record.get("agent_id") or ""),
            tool_name=str(record.get("tool_name") or ""),
            created_at=float(record.get("created_at") or time.time()),
            future=loop.create_future(),
            timeout_seconds=float(record.get("timeout_seconds") or 0),
            status="pending",
            result_summary=str(record.get("result_summary") or ""),
            findings_count=int(record.get("findings_count") or 0),
            severity=str(record.get("severity") or "medium"),
            extra=dict(record.get("extra") or {}),
            scope=scope,
        )
        service._pending[request_id] = pending
        _schedule_expiry(service, pending)
        _schedule_notification(service, pending)
        logger.info(
            "Restored pending HITL request request_id=%s agent_id=%s tool=%s",
            request_id[:8],
            pending.agent_id,
            pending.tool_name,
        )
    service._agentteams_hitl_restored = True


def _expire_pending_in_memory(service: Any) -> None:
    _restore_pending(service)
    store: PersistentApprovalStore = service._agentteams_hitl_store
    expired_ids = set(store.expire_due())
    if not expired_ids:
        return
    from qwenpaw.security.tool_guard.approval import ApprovalDecision

    for request_id in expired_ids:
        pending = service._pending.pop(request_id, None)
        if pending is None:
            continue
        pending.status = ApprovalDecision.TIMEOUT.value
        pending.resolved_at = time.time()
        if not pending.future.done():
            pending.future.set_result(ApprovalDecision.TIMEOUT)
        _cancel_lifecycle_tasks(service, request_id)


def _cancel_lifecycle_tasks(service: Any, request_id: str) -> None:
    for attr in (
        "_agentteams_hitl_notification_tasks",
        "_agentteams_hitl_expiry_tasks",
    ):
        tasks = getattr(service, attr, {})
        task = tasks.pop(request_id, None)
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()


def _schedule_expiry(service: Any, pending: Any) -> None:
    timeout = float(getattr(pending, "timeout_seconds", 0) or 0)
    if timeout <= 0:
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    tasks = service._agentteams_hitl_expiry_tasks
    existing = tasks.get(pending.request_id)
    if existing is not None and not existing.done():
        return

    async def expire() -> None:
        remaining = (
            float(pending.created_at) + timeout - time.time()
        )
        if remaining > 0:
            await asyncio.sleep(remaining)
        current = await service.get_request(pending.request_id)
        if current is not None:
            from qwenpaw.security.tool_guard.approval import ApprovalDecision

            await service.resolve_request(
                pending.request_id,
                ApprovalDecision.TIMEOUT,
            )

    tasks[pending.request_id] = asyncio.create_task(
        expire(),
        name=f"hitl-expire-{pending.request_id[:8]}",
    )


async def _resolve_channel(service: Any, pending: Any) -> Any | None:
    channel_instance = (getattr(pending, "extra", {}) or {}).get(
        "_channel_instance",
    )
    if channel_instance is not None:
        return channel_instance

    managers = getattr(service, "_channel_managers", {})
    manager = (
        managers.get(getattr(pending, "agent_id", ""))
        or managers.get(getattr(pending, "owner_agent_id", ""))
        or managers.get("default")
    )
    if manager is None:
        return None
    try:
        return await manager.get_channel(pending.channel)
    except Exception:
        logger.warning(
            "HITL channel is not ready request_id=%s channel=%s",
            pending.request_id[:8],
            pending.channel,
            exc_info=True,
        )
        return None


def _schedule_notification(
    service: Any,
    pending: Any,
    channel_body: str | None = None,
) -> None:
    if not pending.channel or pending.channel == "console":
        return
    store: PersistentApprovalStore = service._agentteams_hitl_store
    record = store.get(pending.request_id)
    if record is not None and record.get("notification_status") == "sent":
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    tasks = service._agentteams_hitl_notification_tasks
    existing = tasks.get(pending.request_id)
    if existing is not None and not existing.done():
        return
    body = channel_body or pending.result_summary

    async def notify_until_delivered() -> None:
        delay = NOTIFICATION_INITIAL_DELAY_SECONDS
        while True:
            current = await service.get_request(pending.request_id)
            if current is None:
                return
            record = store.get(pending.request_id)
            if record is not None and record.get("notification_status") == "sent":
                return
            expires_at = record.get("expires_at") if record else None
            if expires_at is not None and float(expires_at) <= time.time():
                return
            channel_instance = await _resolve_channel(service, pending)
            if channel_instance is not None:
                try:
                    await channel_instance.send_approval_notification(
                        session_id=(
                            pending.root_session_id
                            if getattr(pending, "extra", {}).get("_spawn_subagent")
                            else pending.session_id
                        ),
                        user_id=pending.user_id,
                        request_id=pending.request_id,
                        tool_name=pending.tool_name,
                        severity=pending.severity,
                        result_summary=body,
                        channel_meta=(getattr(pending, "extra", {}) or {}).get(
                            "channel_meta",
                        ),
                    )
                    store.record_notification(pending.request_id, "sent")
                    logger.info(
                        "HITL approval notification sent request_id=%s channel=%s",
                        pending.request_id[:8],
                        pending.channel,
                    )
                    return
                except Exception:
                    logger.warning(
                        "HITL approval notification failed request_id=%s",
                        pending.request_id[:8],
                        exc_info=True,
                    )
            await asyncio.sleep(delay)
            delay = min(delay * 2, NOTIFICATION_MAX_DELAY_SECONDS)

    tasks[pending.request_id] = asyncio.create_task(
        notify_until_delivered(),
        name=f"hitl-notify-{pending.request_id[:8]}",
    )


def _agentteams_gc_pending_locked(service: Any) -> None:
    """Expire only according to the AgentTeams deadline, not QwenPaw's 30m GC."""

    _expire_pending_in_memory(service)
    overflow = len(service._pending) - MAX_PENDING_RECORDS
    if overflow <= 0:
        return
    from qwenpaw.security.tool_guard.approval import ApprovalDecision

    ordered = sorted(
        service._pending.items(),
        key=lambda item: item[1].created_at,
    )
    for request_id, pending in ordered[:overflow]:
        service._pending.pop(request_id, None)
        pending.status = ApprovalDecision.TIMEOUT.value
        pending.resolved_at = time.time()
        if not pending.future.done():
            pending.future.set_result(ApprovalDecision.TIMEOUT)
        service._agentteams_hitl_store.record_resolution(
            request_id,
            ApprovalDecision.TIMEOUT.value,
            resolved_at=pending.resolved_at,
        )
        _cancel_lifecycle_tasks(service, request_id)


def install_qwenpaw_approval_persistence() -> bool:
    """Install the AgentTeams HITL bridge into QwenPaw 2.0.1 once."""

    from qwenpaw.app.approvals import service as service_module
    from qwenpaw.app.approvals.service import ApprovalService
    from qwenpaw.security.tool_guard.approval import ApprovalDecision

    if getattr(ApprovalService, "_agentteams_hitl_installed", False):
        return False

    original_init = ApprovalService.__init__
    original_gc = ApprovalService._gc_pending_locked
    original_create = ApprovalService.create_pending
    original_create_summary = ApprovalService.create_pending_summary
    original_get_request = ApprovalService.get_request
    original_set_manager = ApprovalService.set_channel_manager
    original_cancel_tool = ApprovalService.cancel_stale_pending_for_tool_call
    original_cancel_root = ApprovalService.cancel_all_pending_by_root_session

    async_methods_to_prepare = (
        "get_pending_by_session",
        "get_all_pending_by_session",
        "list_pending_by_session",
        "get_pending_by_root_session",
        "get_all_pending_by_agent",
    )
    original_queries = {
        name: getattr(ApprovalService, name)
        for name in async_methods_to_prepare
    }

    def patched_init(self: Any) -> None:
        original_init(self)
        _install_instance_state(self)
        _restore_pending(self)

    def patched_gc(self: Any) -> None:
        if not hasattr(self, "_agentteams_hitl_store"):
            original_gc(self)
            return
        _agentteams_gc_pending_locked(self)

    async def patched_notify(self: Any, pending: Any, channel_body: str) -> None:
        # Keep the original method signature for QwenPaw callers.  The
        # AgentTeams loop supplies retry and manager lookup semantics.
        _restore_pending(self)
        _schedule_notification(self, pending, channel_body=channel_body)

    async def patched_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        _restore_pending(self)
        if "timeout_seconds" in kwargs:
            kwargs["timeout_seconds"] = _configured_timeout(kwargs["timeout_seconds"])
        pending = await original_create(self, *args, **kwargs)
        pending.timeout_seconds = _configured_timeout(pending.timeout_seconds)
        self._agentteams_hitl_store.record_pending(pending)
        _schedule_expiry(self, pending)
        extra = kwargs.get("extra") or {}
        if not extra.get("_channel_instance") and not extra.get("_spawn_subagent"):
            _schedule_notification(self, pending)
        return pending

    async def patched_create_summary(self: Any, *args: Any, **kwargs: Any) -> Any:
        _restore_pending(self)
        if "timeout_seconds" in kwargs:
            kwargs["timeout_seconds"] = _configured_timeout(kwargs["timeout_seconds"])
        pending = await original_create_summary(self, *args, **kwargs)
        pending.timeout_seconds = _configured_timeout(pending.timeout_seconds)
        self._agentteams_hitl_store.record_pending(pending)
        _schedule_expiry(self, pending)
        extra = kwargs.get("extra") or {}
        if not extra.get("_channel_instance") and not extra.get("_spawn_subagent"):
            _schedule_notification(self, pending)
        return pending

    async def patched_resolve(
        self: Any,
        request_id: str,
        decision: Any,
        scope: Any = None,
    ) -> Any:
        _restore_pending(self)
        _expire_pending_in_memory(self)
        async with self._lock:
            resolved = self._pending.pop(request_id, None)
            if resolved is None:
                return None
            resolved.status = _decision_value(decision)
            resolved.resolved_at = time.time()
            resolved.scope = scope

        if not resolved.future.done():
            resolved.future.set_result(decision)
        self._agentteams_hitl_store.record_resolution(
            request_id,
            resolved.status,
            resolved_at=resolved.resolved_at,
            scope=_scope_value(scope),
        )
        _cancel_lifecycle_tasks(self, request_id)
        logger.info(
            "Approval request %s resolved: decision=%s scope=%s tool=%s",
            request_id[:8],
            resolved.status,
            _scope_value(scope) or "exact(default)",
            resolved.tool_name,
        )
        return resolved

    async def patched_get_request(self: Any, request_id: str) -> Any:
        _restore_pending(self)
        _expire_pending_in_memory(self)
        return await original_get_request(self, request_id)

    async def patched_wait(
        self: Any,
        request_id: str,
        timeout_seconds: float,
    ) -> Any:
        _restore_pending(self)
        _expire_pending_in_memory(self)
        async with self._lock:
            pending = self._pending.get(request_id)
        if pending is None:
            raise ValueError(f"Approval request {request_id} not found")

        configured_timeout = float(getattr(pending, "timeout_seconds", 0) or 0)
        if configured_timeout > 0:
            timeout = configured_timeout + pending.created_at - time.time()
            if timeout <= 0:
                await self.resolve_request(request_id, ApprovalDecision.TIMEOUT)
                return ApprovalDecision.TIMEOUT
        else:
            timeout = None

        try:
            future = asyncio.shield(pending.future)
            if timeout is None:
                return await future
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            resolved = await self.resolve_request(
                request_id,
                ApprovalDecision.TIMEOUT,
            )
            if resolved is None:
                return ApprovalDecision.TIMEOUT
            return ApprovalDecision.TIMEOUT

    def patched_set_manager(self: Any, channel_manager: Any, agent_id: str = "default") -> None:
        _restore_pending(self)
        original_set_manager(self, channel_manager, agent_id=agent_id)
        for pending in list(self._pending.values()):
            _schedule_notification(self, pending)

    async def patched_cancel_tool(self: Any, *args: Any, **kwargs: Any) -> int:
        _restore_pending(self)
        candidates = [
            pending
            for pending in self._pending.values()
            if pending.status == "pending"
        ]
        result = await original_cancel_tool(self, *args, **kwargs)
        for pending in candidates:
            if pending.status != "pending":
                self._agentteams_hitl_store.record_resolution(
                    pending.request_id,
                    pending.status,
                    resolved_at=pending.resolved_at,
                )
                _cancel_lifecycle_tasks(self, pending.request_id)
        return result

    async def patched_cancel_root(self: Any, *args: Any, **kwargs: Any) -> int:
        _restore_pending(self)
        candidates = [
            pending
            for pending in self._pending.values()
            if pending.status == "pending"
        ]
        result = await original_cancel_root(self, *args, **kwargs)
        for pending in candidates:
            if pending.status != "pending":
                self._agentteams_hitl_store.record_resolution(
                    pending.request_id,
                    pending.status,
                    resolved_at=pending.resolved_at,
                )
                _cancel_lifecycle_tasks(self, pending.request_id)
        return result

    ApprovalService.__init__ = patched_init
    ApprovalService._gc_pending_locked = patched_gc
    ApprovalService._notify_channel = patched_notify
    ApprovalService.create_pending = patched_create
    ApprovalService.create_pending_summary = patched_create_summary
    ApprovalService.resolve_request = patched_resolve
    ApprovalService.get_request = patched_get_request
    ApprovalService.wait_for_approval = patched_wait
    ApprovalService.set_channel_manager = patched_set_manager
    ApprovalService.cancel_stale_pending_for_tool_call = patched_cancel_tool
    ApprovalService.cancel_all_pending_by_root_session = patched_cancel_root

    for name, original in original_queries.items():
        async def query(self: Any, *args: Any, _original=original, **kwargs: Any) -> Any:
            _restore_pending(self)
            _expire_pending_in_memory(self)
            return await _original(self, *args, **kwargs)

        setattr(ApprovalService, name, query)

    ApprovalService._agentteams_hitl_installed = True

    existing = getattr(service_module, "_approval_service", None)
    if existing is not None:
        _install_instance_state(existing)
        _restore_pending(existing)

    logger.info(
        "Installed AgentTeams persistent HITL bridge state_path=%s timeout_seconds=%s",
        hitl_state_path(),
        os.environ.get(
            "AGENTTEAMS_HITL_APPROVAL_TIMEOUT_SECONDS",
            str(DEFAULT_APPROVAL_TIMEOUT_SECONDS),
        ),
    )
    return True
