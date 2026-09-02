"""One-shot external execution for an AgentTeams-native Worker.

The native Worker owns assignment, task state, and submission.  This module
only starts one allowlisted process, bounds it, and normalizes its result.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
from typing import Any

from .codex_cli import build_codex_cli_launch
from .config import (
    AdapterConfig,
    AdapterConfigError,
    ProtectedReference,
    PROTECTED_REFERENCE_ENV_NAMES,
    bind_bailian_route,
    preflight_execution_reference,
    resolve_dsh_file_environment,
)
from .native_worker import (
    DSH_PROVIDER_PROFILES,
    NativeWorkerAssignment,
    prepare_native_worker_invocation,
)
from .result import EvidenceReference, NormalizedResult, Provenance, ResultContractError


NATIVE_EXECUTION_PROTOCOL = "testweaver.native-external/v1"
NATIVE_EXECUTION_TOOL = "native_worker_execute"
PRODUCTION_ROOT = Path("/opt/agentteams/testweaver-native-worker")
PRODUCTION_DSH_EXECUTABLE = PRODUCTION_ROOT / "bin" / "dsh"
PRODUCTION_DSH_PATCH = PRODUCTION_ROOT / "dsh-headless-max-tokens.patch.yml"
PRODUCTION_CODEX_EXECUTABLE = PRODUCTION_ROOT / "bin" / "codex-cc"
WORKSPACE_ENVIRONMENT = "AGENT_WORKSPACE"
ARTIFACT_DIRECTORY = ".testweaver-native-results"
MAX_PROMPT_BYTES = 128 * 1024
DEFAULT_MAX_OUTPUT_BYTES = 1024 * 1024
KILL_GRACE_SECONDS = 1.0

_CHILD_ENV_NAMES = frozenset("CODEX_HOME HOME HTTPS_PROXY HTTP_PROXY LANG LC_ALL NO_PROXY PATH SSL_CERT_DIR SSL_CERT_FILE TMPDIR".split())
_WORKSPACE_ROOTS = tuple(Path(item) for item in ("/root/agentteams-fs/agents", "/tmp/agentteams-native-worker"))
_SECRET_RE = re.compile(r"(?i)(\b(?:authorization|api[_-]?key|access[_-]?key|secret|token|password)\b\s*[:=]\s*)([^\s,;\}\]\"]+)")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----", re.DOTALL | re.IGNORECASE)


class NativeExecutionError(ValueError):
    pass


def _inside(path: Path, roots: Iterable[Path]) -> bool:
    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            pass
    return False


def _redact(value: str, secrets: Iterable[str] = ()) -> str:
    result = value
    for secret in sorted({item for item in secrets if isinstance(item, str) and len(item) >= 8}, key=len, reverse=True):
        result = result.replace(secret, "[REDACTED]")
    result = _PRIVATE_KEY_RE.sub("[REDACTED_PRIVATE_KEY]", result)
    result = _BEARER_RE.sub("Bearer [REDACTED]", result)
    return _SECRET_RE.sub(r"\1[REDACTED]", result)


def _validate_reference(reference: ProtectedReference, field: str, *, dsh_file: bool = False) -> None:
    if reference.source == "env":
        if reference.location not in PROTECTED_REFERENCE_ENV_NAMES:
            raise NativeExecutionError(f"{field} environment reference is not allowlisted")
    check = preflight_execution_reference(
        reference,
        dedicated_provider=dsh_file,
        field=field,
    )
    if not check.usable:
        raise NativeExecutionError(f"{field} protected reference is unavailable")


def _workspace() -> Path:
    raw = os.environ.get(WORKSPACE_ENVIRONMENT, "")
    if not raw or not Path(raw).is_absolute():
        raise NativeExecutionError("Worker workspace must be an absolute approved path")
    path = Path(raw).resolve()
    if not path.is_dir() or not _inside(path, _WORKSPACE_ROOTS):
        raise NativeExecutionError("Worker workspace is outside approved roots")
    return path


def _environment(config: AdapterConfig) -> tuple[dict[str, str], tuple[str, ...]]:
    names = set(_CHILD_ENV_NAMES)
    refs = (config.route.endpoint_ref, config.route.model_ref, config.route.credential_ref)
    if config.adapter_kind == "dsh":
        names.update(ref.location for ref in refs if ref.source == "env")
    values = {name: os.environ[name] for name in names if name in os.environ}
    if config.adapter_kind == "dsh":
        try:
            return resolve_dsh_file_environment(config.route, values)
        except AdapterConfigError as exc:
            raise NativeExecutionError(str(exc)) from exc
    if config.adapter_kind == "codex-cli" and any(not values.get(name) for name in ("HOME", "CODEX_HOME")):
        raise NativeExecutionError("Codex protected environment is not bound")
    return values, tuple(values.values())


def _validate(assignment: NativeWorkerAssignment, config: AdapterConfig, provenance: Provenance, prompt: str) -> None:
    if not isinstance(assignment, NativeWorkerAssignment): raise NativeExecutionError("assignment must be a native Worker assignment")
    if not isinstance(config, AdapterConfig):
        raise NativeExecutionError("config must be AdapterConfig")
    if not isinstance(provenance, Provenance):
        raise NativeExecutionError("provenance must be Provenance")
    if not isinstance(prompt, str) or not prompt or "\x00" in prompt or len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise NativeExecutionError("prompt is outside the approved size limit")
    route = config.route
    for name, reference in (
        ("endpoint", route.endpoint_ref),
        ("model", route.model_ref),
        ("credential", route.credential_ref),
    ):
        _validate_reference(reference, name, dsh_file=config.adapter_kind == "dsh")
    if config.adapter_kind == "dsh":
        if route.provider not in DSH_PROVIDER_PROFILES:
            raise NativeExecutionError("DSH provider profile is not allowlisted")
    elif route.provider != "codex-cc":
        raise NativeExecutionError("Codex execution requires the codex-cc profile")
    if config.adapter_kind == "codex-cli":
        for reference in build_codex_cli_launch().protected_environment:
            _validate_reference(reference, "codex_environment")


def _argv(config: AdapterConfig, prompt: str) -> list[str]:
    if config.adapter_kind == "dsh":
        return [str(PRODUCTION_DSH_EXECUTABLE), "--profile", "headless", "--patch", str(PRODUCTION_DSH_PATCH), "--", prompt]
    launch = build_codex_cli_launch()
    return [str(PRODUCTION_CODEX_EXECUTABLE), *launch.command[1:]]


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:  # pragma: no cover - Worker images are POSIX.
            process.terminate()
        process.wait(timeout=KILL_GRACE_SECONDS)
        return
    except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
        pass
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:  # pragma: no cover
            process.kill()
        process.wait(timeout=KILL_GRACE_SECONDS)
    except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
        pass


def _run(argv: list[str], payload: bytes, cwd: Path, env: dict[str, str], timeout: float, limit: int) -> dict[str, Any]:
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd),
            env=env,
            shell=False,
            start_new_session=True,
            close_fds=True,
        )
    except OSError as exc:
        raise NativeExecutionError("approved external executable could not be started") from exc
    assert process.stdin and process.stdout and process.stderr
    output = {"stdout": bytearray(), "stderr": bytearray()}
    counts = {"stdout": 0, "stderr": 0}
    stored = [0]
    limited = threading.Event()
    lock = threading.Lock()

    def drain(name: str, stream: Any) -> None:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                return
            counts[name] += len(chunk)
            with lock:
                remaining = max(0, limit - stored[0])
                if remaining:
                    output[name].extend(chunk[:remaining])
                    stored[0] += min(len(chunk), remaining)
                if counts["stdout"] + counts["stderr"] > limit:
                    limited.set()

    def feed() -> None:
        try:
            process.stdin.write(payload)
            process.stdin.close()
        except (BrokenPipeError, OSError):
            try:
                process.stdin.close()
            except OSError:
                pass

    threads = [
        threading.Thread(target=drain, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=drain, args=("stderr", process.stderr), daemon=True),
        threading.Thread(target=feed, daemon=True),
    ]
    for thread in threads:
        thread.start()
    timed_out = False
    deadline = started + timeout
    while process.poll() is None:
        if limited.is_set():
            _terminate(process)
            break
        if time.monotonic() >= deadline:
            timed_out = True
            _terminate(process)
            break
        time.sleep(0.01)
    if process.poll() is None:
        _terminate(process)
    try:
        process.wait(timeout=KILL_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        _terminate(process)
    for thread in threads:
        thread.join(timeout=KILL_GRACE_SECONDS)
    for stream in (process.stdin, process.stdout, process.stderr):
        stream.close()
    return {
        "stdout": bytes(output["stdout"]),
        "stderr": bytes(output["stderr"]),
        "stdout_bytes": counts["stdout"],
        "stderr_bytes": counts["stderr"],
        "exit_code": process.poll(),
        "latency_seconds": max(0.0, time.monotonic() - started),
        "timed_out": timed_out,
        "output_limit_exceeded": limited.is_set(),
    }


def _artifact(cwd: Path, content: bytes) -> tuple[str, EvidenceReference]:
    digest = hashlib.sha256(content).hexdigest()
    directory = cwd / ARTIFACT_DIRECTORY
    if directory.is_symlink():
        raise NativeExecutionError("result directory must not be a symlink")
    try:
        directory.mkdir(mode=0o700, exist_ok=True)
    except OSError as exc:
        raise NativeExecutionError("result directory could not be prepared") from exc
    if directory.stat().st_mode & 0o077:
        raise NativeExecutionError("result directory must be owner-only")
    target = directory / f"result-{digest}.txt"
    if target.is_symlink():
        raise NativeExecutionError("result artifact must not be a symlink")
    if target.exists():
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise NativeExecutionError("existing result artifact has a different hash")
    else:
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
        except FileExistsError:
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise NativeExecutionError("result artifact appeared with a different hash")
    ref = target.relative_to(cwd).as_posix()
    return ref, EvidenceReference(
        id=f"native-result-{digest[:16]}",
        kind="file",
        artifact_ref=ref,
        content_hash=f"sha256:{digest}",
    )


def _failure(cwd: Path, capture: Mapping[str, Any], reason: str, termination: str, secrets: Iterable[str]) -> dict[str, Any]:
    diagnostic = {
        "reason": reason,
        "exit_code": capture["exit_code"],
        "stdout": _redact(capture["stdout"].decode("utf-8", errors="replace"), secrets),
        "stderr": _redact(capture["stderr"].decode("utf-8", errors="replace"), secrets),
    }
    ref, evidence = _artifact(
        cwd,
        (json.dumps(diagnostic, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"),
    )
    return {
        "status": "TIMEOUT" if termination == "TIMEOUT" else "FAILED",
        "termination": termination,
        "result_ref": ref,
        "evidence_refs": [evidence.as_dict()],
        "usage": {},
    }


def _raw_result(config: AdapterConfig, cwd: Path, capture: Mapping[str, Any], secrets: Iterable[str]) -> dict[str, Any]:
    text = _redact(capture["stdout"].decode("utf-8", errors="replace"), secrets)
    if config.adapter_kind == "dsh" and not text.strip():
        raise ResultContractError("DSH returned empty output")
    if config.adapter_kind in {"codex-cli", "dsh"}:
        value: dict[str, Any] = {"status": "COMPLETED", "output": text, "usage": {}}
    else:
        try:
            value = json.loads(text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ResultContractError("DSH returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise ResultContractError("external result must be an object")
    allowed = {"status", "termination", "result_ref", "evidence_refs", "usage", "output", "elapsed_seconds"}
    if set(value) - allowed:
        raise ResultContractError("external result contains unsupported fields")
    value.setdefault("status", "COMPLETED")
    output = value.pop("output", None)
    if output is None and (not value.get("result_ref") or not value.get("evidence_refs")):
        output = text
    if output is not None:
        if not isinstance(output, str) or len(output.encode("utf-8")) > DEFAULT_MAX_OUTPUT_BYTES:
            raise ResultContractError("external output exceeds the approved size limit")
        ref, evidence = _artifact(cwd, output.encode("utf-8"))
        refs = value.get("evidence_refs", [])
        if not isinstance(refs, list):
            raise ResultContractError("external evidence_refs must be an array")
        value["evidence_refs"] = [*refs, evidence.as_dict()]
        value.setdefault("result_ref", ref)
    value.setdefault("usage", {})
    value["elapsed_seconds"] = capture["latency_seconds"]
    return value


def _metadata(argv: list[str], cwd: Path, capture: Mapping[str, Any]) -> dict[str, Any]:
    metadata = {
        "protocol": NATIVE_EXECUTION_PROTOCOL,
        "executable": argv[0],
        "argv": list(argv),
        "cwd": str(cwd),
        "exit_code": capture["exit_code"],
        "timed_out": capture["timed_out"],
        "output_limit_exceeded": capture["output_limit_exceeded"],
        "stdout_bytes": capture["stdout_bytes"],
        "stderr_bytes": capture["stderr_bytes"],
        "latency_seconds": capture["latency_seconds"],
        "external_process_started": True,
        "native_state_mutation": False,
        "native_result_submission": False,
    }
    if len(argv) >= 5 and argv[1:3] == ["--profile", "headless"]:
        prompt = argv[-1].encode("utf-8")
        metadata["argv"][-1] = "[PROMPT_REDACTED]"
        metadata["prompt_sha256"] = hashlib.sha256(prompt).hexdigest()
        metadata["prompt_bytes"] = len(prompt)
    return metadata


def execute_native_worker(assignment: NativeWorkerAssignment, config: AdapterConfig, provenance: Provenance, prompt: str) -> tuple[NormalizedResult, dict[str, Any]]:
    with bind_bailian_route(config, _WORKSPACE_ROOTS):
        return _execute_native_worker(assignment, config, provenance, prompt)


def _execute_native_worker(assignment: NativeWorkerAssignment, config: AdapterConfig, provenance: Provenance, prompt: str) -> tuple[NormalizedResult, dict[str, Any]]:
    """Run one fixed external process after a native assignment.

    The four arguments are the complete call surface.  Native IDs are passed
    to the child only as opaque references; this function has no task or room
    operation and never submits a native result.
    """

    _validate(assignment, config, provenance, prompt)
    cwd = _workspace()
    env, secrets = _environment(config)
    invocation = prepare_native_worker_invocation(
        assignment=assignment,
        config=config,
        provenance=provenance,
    )
    argv = _argv(config, prompt)
    executable = Path(argv[0])
    if executable.is_symlink() or not executable.is_file() or not os.access(executable, os.X_OK):
        raise NativeExecutionError("approved external executable is missing or not executable")
    payload = json.dumps(
        {
            "protocol": NATIVE_EXECUTION_PROTOCOL,
            "adapter_kind": config.adapter_kind,
            "route": config.route.as_dict(),
            "limits": config.limits.as_dict(),
            "native_assignment": assignment.as_dict(),
            "provenance": provenance.as_dict(),
            "prompt": prompt,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") if config.adapter_kind != "dsh" else b""
    capture = _run(
        argv,
        payload,
        cwd,
        env,
        config.limits.timeout_seconds,
        DEFAULT_MAX_OUTPUT_BYTES,
    )
    if capture["timed_out"]:
        raw = _failure(cwd, capture, "timeout", "TIMEOUT", secrets)
    elif capture["output_limit_exceeded"]:
        raw = _failure(cwd, capture, "output_limit", "PROTOCOL_ERROR", secrets)
    elif capture["exit_code"] not in (0, None):
        raw = _failure(cwd, capture, "external_exit", "PROVIDER_ERROR", secrets)
    else:
        try:
            raw = _raw_result(config, cwd, capture, secrets)
        except (ResultContractError, ValueError, TypeError) as exc:
            raw = _failure(cwd, capture, f"protocol_error:{exc}", "PROTOCOL_ERROR", secrets)
    try:
        result = invocation.normalize_result(raw, latency_seconds=capture["latency_seconds"])
    except (ResultContractError, ValueError) as exc:
        raise NativeExecutionError("external result could not be normalized") from exc
    metadata = _metadata(argv, cwd, capture)
    metadata.update({"result_status": result.status, "termination": result.termination})
    return result, metadata
