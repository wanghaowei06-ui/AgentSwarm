"""Thin TestWeaver adapters around AgentTeams-native worker boundaries.

The package contains data contracts only.  Native TeamHarness and the
upstream runtime own transport, delegation, process control, and credentials.
"""

from .codex_cli import (
    CODEX_EXECUTABLE,
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
from .result import (
    EvidenceReference,
    NativeReferences,
    NormalizedResult,
    Provenance,
    ResultContractError,
    Usage,
    normalize_result,
)

__all__ = [
    "AdapterConfig",
    "AdapterConfigError",
    "CODEX_EXECUTABLE",
    "CodexCliLaunch",
    "DEFAULT_MODEL",
    "DEFAULT_REASONING",
    "EvidenceReference",
    "ExecutionLimits",
    "NativeReferences",
    "NormalizedResult",
    "ProtectedReference",
    "Provenance",
    "ProviderRoute",
    "ResultContractError",
    "Usage",
    "build_codex_cli_launch",
    "normalize_result",
]
