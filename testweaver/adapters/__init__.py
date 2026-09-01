"""Thin TestWeaver adapters around AgentTeams-native worker boundaries.

The package contains data contracts only.  Native TeamHarness and the
upstream runtime own transport, delegation, process control, and credentials.
"""

from .codex_cli import (
    CODEX_EXECUTABLE,
    CODEX_REASONING_CONFIG,
    DEFAULT_MODEL,
    DEFAULT_REASONING,
    CodexCliLaunch,
    build_codex_cli_launch,
)
from .config import (
    AdapterConfig,
    AdapterConfigError,
    ExecutionLimits,
    ProtectedReference,
    ProviderRoute,
)
from .native_worker import (
    DSH_PROVIDER_PROFILES,
    DshProviderProfile,
    NativeWorkerAdapterError,
    NativeWorkerAssignment,
    NativeWorkerInvocation,
    prepare_native_worker_invocation,
)
from .result import (
    EvidenceReference,
    NativeReferences,
    NormalizedResult,
    Provenance,
    ResultContractError,
    Usage,
    WorkerResult,
    normalize_result,
)

__all__ = [
    "AdapterConfig",
    "AdapterConfigError",
    "CODEX_EXECUTABLE",
    "CODEX_REASONING_CONFIG",
    "CodexCliLaunch",
    "DEFAULT_MODEL",
    "DEFAULT_REASONING",
    "EvidenceReference",
    "ExecutionLimits",
    "DSH_PROVIDER_PROFILES",
    "DshProviderProfile",
    "NativeReferences",
    "NativeWorkerAdapterError",
    "NativeWorkerAssignment",
    "NativeWorkerInvocation",
    "NormalizedResult",
    "ProtectedReference",
    "Provenance",
    "ProviderRoute",
    "ResultContractError",
    "Usage",
    "WorkerResult",
    "build_codex_cli_launch",
    "normalize_result",
    "prepare_native_worker_invocation",
]
