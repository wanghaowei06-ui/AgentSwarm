from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw_worker.api import QwenPawApiError
from qwenpaw_worker.worker import Worker


def _config(tmp_path: Path):
    from qwenpaw_worker.config import WorkerConfig

    return WorkerConfig(
        worker_name="worker-a",
        worker_cr_name="worker-a-cr",
        fs_endpoint="http://minio:9000",
        fs_access_key="key",
        fs_secret_key="secret",
        install_dir=tmp_path / "agents",
    )


def _clock(monkeypatch: pytest.MonkeyPatch):
    now = [0.0]
    sleeps: list[float] = []

    def monotonic() -> float:
        return now[0]

    def sleep(delay: float) -> None:
        sleeps.append(delay)
        now[0] += delay

    monkeypatch.setattr("qwenpaw_worker.worker.time.monotonic", monotonic)
    monkeypatch.setattr("qwenpaw_worker.worker.time.sleep", sleep)
    return sleeps


def test_builtin_mcp_configuration_retries_transient_startup_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = Worker(_config(tmp_path))
    attempts = [0]
    sleeps = _clock(monkeypatch)

    def configure_once() -> None:
        attempts[0] += 1
        if attempts[0] < 3:
            try:
                raise TimeoutError("startup not ready")
            except TimeoutError as cause:
                raise QwenPawApiError("QwenPaw API unavailable") from cause

    monkeypatch.setattr(worker, "_configure_builtin_plugin_mcp_clients_once", configure_once)

    worker._configure_builtin_plugin_mcp_clients()

    assert attempts == [3]
    assert sleeps == [0.25, 0.5]


def test_builtin_mcp_configuration_does_not_retry_permanent_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = Worker(_config(tmp_path))
    attempts = [0]
    sleeps = _clock(monkeypatch)

    def configure_once() -> None:
        attempts[0] += 1
        raise QwenPawApiError("QwenPaw MCP readback mismatch")

    monkeypatch.setattr(worker, "_configure_builtin_plugin_mcp_clients_once", configure_once)

    with pytest.raises(QwenPawApiError, match="readback mismatch"):
        worker._configure_builtin_plugin_mcp_clients()

    assert attempts == [1]
    assert sleeps == []


def test_builtin_mcp_configuration_fails_after_bounded_transient_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = Worker(_config(tmp_path))
    attempts = [0]
    sleeps = _clock(monkeypatch)

    def configure_once() -> None:
        attempts[0] += 1
        raise TimeoutError("startup not ready")

    monkeypatch.setattr(worker, "_configure_builtin_plugin_mcp_clients_once", configure_once)

    with pytest.raises(TimeoutError, match="startup not ready"):
        worker._configure_builtin_plugin_mcp_clients()

    assert attempts[0] > 1
    assert sum(sleeps) <= 60
