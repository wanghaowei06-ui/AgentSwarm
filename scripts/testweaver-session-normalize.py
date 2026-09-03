#!/usr/bin/env python3
"""Project provider metadata from JSONL or QwenPaw session JSON.

Only metadata, hashes and reference tokens are emitted.  Prompt, response and
tool content is consumed for correlation but is never written to stdout.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import sys
from collections.abc import Iterable, Mapping
from typing import Any


def _timestamp_ms(value: Any) -> int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, str):
        try:
            return int(datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            return None
    return None


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)


def _references(value: Any) -> tuple[list[str], list[str]]:
    text = "\n".join(_strings(value))
    task_refs = set(re.findall(r"task-[A-Za-z0-9._:-]+", text))
    task_refs.update(re.findall(r'"(?:task_id|taskId)"\s*:\s*"([A-Za-z0-9._:@/-]+)"', text))
    task_refs.update(
        candidate
        for candidate in re.findall(
            r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9._:@/]+){2,})(?![A-Za-z0-9])",
            text,
        )
        if not candidate.startswith(("http-", "https-", "sha256-"))
    )
    event_refs = set(re.findall(r"\$[A-Za-z0-9_-]{8,}", text))
    return sorted(task_refs), sorted(event_refs)


def _qwenpaw_records(root: Mapping[str, Any]) -> list[tuple[bytes, Mapping[str, Any]]]:
    try:
        context = root["agent"]["state"]["context"]
    except (KeyError, TypeError):
        return []
    if not isinstance(context, list):
        return []
    records: list[tuple[bytes, Mapping[str, Any]]] = []
    for item in context:
        if not isinstance(item, Mapping) or item.get("role") not in {"user", "assistant"}:
            continue
        metadata = item.get("metadata")
        turn_usage = metadata.get("qwenpaw_turn_usage") if isinstance(metadata, Mapping) else None
        provider_usage = turn_usage.get("usage") if isinstance(turn_usage, Mapping) else None
        safe_item = {
            "role": item.get("role"),
            "id": item.get("id"),
            "created_at": item.get("created_at"),
            "finished_at": item.get("finished_at"),
            "usage": item.get("usage"),
            "provider_usage": provider_usage,
            "content_refs": _references(item.get("content")),
        }
        raw = json.dumps(safe_item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        records.append((raw, item))
    return records


def _records(data: bytes) -> list[tuple[bytes, Mapping[str, Any]]]:
    lines: list[tuple[bytes, Mapping[str, Any]]] = []
    for raw in data.splitlines():
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            lines = []
            break
        if isinstance(value, Mapping):
            lines.append((raw, value))
    if lines and any(
        isinstance(value.get("message"), Mapping) or value.get("role") in {"user", "assistant"}
        for _, value in lines
    ):
        return lines
    if len(lines) == 1:
        return _qwenpaw_records(lines[0][1])
    try:
        value = json.loads(data)
    except json.JSONDecodeError:
        return []
    return _qwenpaw_records(value) if isinstance(value, Mapping) else []


def main() -> int:
    if len(sys.argv) != 4:
        return 2
    run_id, campaign_id, trace_id = sys.argv[1:]
    data = sys.stdin.buffer.read()
    previous_user_ms: int | None = None
    output: list[dict[str, Any]] = []
    for sequence, (raw, value) in enumerate(_records(data)):
        message = value.get("message", value)
        if not isinstance(message, Mapping):
            continue
        role = message.get("role", value.get("role"))
        if role not in {"user", "assistant"}:
            continue
        usage = message.get("usage") if isinstance(message.get("usage"), Mapping) else None
        metadata = value.get("metadata") if isinstance(value.get("metadata"), Mapping) else {}
        turn_usage = metadata.get("qwenpaw_turn_usage") if isinstance(metadata, Mapping) else None
        provider_usage = turn_usage.get("usage") if isinstance(turn_usage, Mapping) else None
        if usage is None and isinstance(provider_usage, Mapping):
            usage = {
                key: provider_usage[source]
                for source, key in (
                    ("prompt_tokens", "input_tokens"),
                    ("completion_tokens", "output_tokens"),
                    ("total_tokens", "total_tokens"),
                )
                if isinstance(provider_usage.get(source), int) and not isinstance(provider_usage.get(source), bool)
            }
        timestamp = value.get("timestamp", value.get("created_at"))
        timestamp_ms = _timestamp_ms(timestamp)
        task_refs, event_refs = _references(value.get("content", value.get("message", value)))
        if role == "user" and timestamp_ms is not None:
            previous_user_ms = timestamp_ms
        provider = message.get("provider")
        model = message.get("model")
        if provider is None and isinstance(provider_usage, Mapping):
            provider = provider_usage.get("provider_id")
        if model is None and isinstance(provider_usage, Mapping):
            model = provider_usage.get("model_name")
        latency = message.get("durationMs", value.get("durationMs"))
        if latency is None and role == "assistant" and timestamp_ms is not None and previous_user_ms is not None:
            latency = max(0, timestamp_ms - previous_user_ms)
        safe = {
            "record_hash": hashlib.sha256(raw).hexdigest(),
            "sequence": sequence,
            "id": value.get("id"),
            "timestamp": timestamp,
            "timestamp_ms": timestamp_ms,
            "role": role,
            "provider": provider,
            "model": model,
            "usage": dict(usage) if isinstance(usage, Mapping) else None,
            "latency_ms": latency,
            "scope_mentions": {
                "run_id": run_id in data.decode("utf-8", "replace"),
                "campaign_id": campaign_id in data.decode("utf-8", "replace"),
                "trace_id": trace_id in data.decode("utf-8", "replace"),
            },
            "task_refs": task_refs,
            "matrix_event_refs": event_refs,
        }
        output.append(safe)
    for item in output:
        print(json.dumps(item, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
