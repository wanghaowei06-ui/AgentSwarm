"""Bounded newline JSON-RPC client for a single stdio MCP subprocess.

Notifications deliberately have no response.  A request with no ``id`` is
therefore written and returned from immediately; response-bearing requests
are bounded and the subprocess is closed as one process group on failure.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import os
import selectors
import signal
import subprocess
import time
from typing import Any


DEFAULT_RESPONSE_TIMEOUT = 30.0
DEFAULT_CLOSE_TIMEOUT = 1.0
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class StdioJsonRpcError(RuntimeError):
    """Raised when a stdio JSON-RPC exchange cannot complete safely."""


class StdioJsonRpcTimeout(StdioJsonRpcError):
    """Raised when a response does not arrive within the configured bound."""


class StdioJsonRpcProtocolError(StdioJsonRpcError):
    """Raised when the subprocess emits an invalid or mismatched response."""


def _terminate_process_group(process: subprocess.Popen[bytes], timeout: float) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:  # pragma: no cover - supported Worker images are POSIX.
            process.terminate()
        process.wait(timeout=timeout)
        return
    except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
        pass
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:  # pragma: no cover
            process.kill()
        process.wait(timeout=timeout)
    except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
        pass


class StdioJsonRpcClient:
    """Exchange JSON-RPC messages with one child process over newline stdio."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        response_timeout: float = DEFAULT_RESPONSE_TIMEOUT,
        close_timeout: float = DEFAULT_CLOSE_TIMEOUT,
    ) -> None:
        if not command or any(not isinstance(item, str) or not item for item in command):
            raise ValueError("command must be a non-empty sequence of strings")
        if response_timeout <= 0 or close_timeout <= 0:
            raise ValueError("timeouts must be greater than zero")
        self.response_timeout = response_timeout
        self.close_timeout = close_timeout
        try:
            self.process = subprocess.Popen(
                list(command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=cwd,
                env=dict(env) if env is not None else None,
                shell=False,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            raise StdioJsonRpcError("stdio JSON-RPC server could not be started") from exc
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        self._stdin = self.process.stdin
        self._stdout = self.process.stdout
        self._selector = selectors.DefaultSelector()
        self._selector.register(self._stdout, selectors.EVENT_READ)
        self._buffer = bytearray()
        self._closed = False

    def _send(self, request: Mapping[str, Any]) -> None:
        if self._closed:
            raise StdioJsonRpcError("stdio JSON-RPC client is closed")
        try:
            payload = (
                json.dumps(
                    dict(request),
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                + b"\n"
            )
            self._stdin.write(payload)
            self._stdin.flush()
        except (BrokenPipeError, OSError, TypeError, ValueError) as exc:
            raise StdioJsonRpcError("stdio JSON-RPC request could not be written") from exc

    def send_notification(self, method: str, params: Any = None) -> None:
        """Send a notification without attempting to read a response."""

        if not isinstance(method, str) or not method:
            raise ValueError("notification method must be a non-empty string")
        request: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            request["params"] = params
        self._send(request)

    def rpc(self, request: Mapping[str, Any]) -> dict[str, Any] | None:
        """Send one request, returning no value for a notification."""

        if not isinstance(request, Mapping) or not isinstance(request.get("method"), str):
            raise ValueError("request must contain a method")
        request_dict = dict(request)
        self._send(request_dict)
        request_id = request_dict.get("id")
        if request_id is None:
            return None
        try:
            response = self._read_response(request_id)
        except StdioJsonRpcTimeout:
            self.close()
            raise
        except StdioJsonRpcError:
            self.close()
            raise
        return response

    def _read_response(self, request_id: Any) -> dict[str, Any]:
        deadline = time.monotonic() + self.response_timeout
        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                line = bytes(self._buffer[:newline])
                del self._buffer[: newline + 1]
                if not line.strip():
                    continue
                try:
                    response = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise StdioJsonRpcProtocolError("stdio JSON-RPC response is invalid JSON") from exc
                if not isinstance(response, dict):
                    raise StdioJsonRpcProtocolError("stdio JSON-RPC response must be an object")
                if response.get("id") != request_id:
                    raise StdioJsonRpcProtocolError("stdio JSON-RPC response id does not match request")
                return response

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise StdioJsonRpcTimeout("stdio JSON-RPC response timed out")
            events = self._selector.select(remaining)
            if not events:
                raise StdioJsonRpcTimeout("stdio JSON-RPC response timed out")
            try:
                chunk = os.read(self._stdout.fileno(), 64 * 1024)
            except BlockingIOError:
                continue
            except OSError as exc:
                raise StdioJsonRpcError("stdio JSON-RPC response could not be read") from exc
            if not chunk:
                raise StdioJsonRpcProtocolError("stdio JSON-RPC server closed before responding")
            self._buffer.extend(chunk)
            if len(self._buffer) > MAX_RESPONSE_BYTES:
                raise StdioJsonRpcProtocolError("stdio JSON-RPC response exceeds the size limit")

    def close(self) -> None:
        """Close stdin, wait for EOF, and terminate the child group if needed."""

        if self._closed:
            return
        self._closed = True
        try:
            self._stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=self.close_timeout)
        except subprocess.TimeoutExpired:
            _terminate_process_group(self.process, self.close_timeout)
        finally:
            try:
                self._selector.unregister(self._stdout)
            except (KeyError, ValueError):
                pass
            self._selector.close()
            try:
                self._stdout.close()
            except OSError:
                pass

    def __enter__(self) -> "StdioJsonRpcClient":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()
