"""Thin launch contract for the committed AgentTeams Codex remote member."""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import ProtectedReference


CODEX_EXECUTABLE = "codex-cc"
DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_REASONING = "max"
CODEX_REASONING_CONFIG = "model_reasoning_effort=max"
_APP_SERVER_COMMAND = (
    CODEX_EXECUTABLE,
    "-m",
    DEFAULT_MODEL,
    "-c",
    CODEX_REASONING_CONFIG,
    "app-server",
    "--listen",
    "stdio://",
)


@dataclass(frozen=True)
class CodexCliLaunch:
    """Non-executing launch metadata consumed by the upstream bridge."""

    model: str = DEFAULT_MODEL
    reasoning: str = DEFAULT_REASONING
    command: tuple[str, ...] = field(default=_APP_SERVER_COMMAND, init=False)
    protected_environment: tuple[ProtectedReference, ...] = field(
        default_factory=lambda: (
            ProtectedReference.env("HOME"),
            ProtectedReference.env("CODEX_HOME"),
        ),
        init=False,
    )

    def __post_init__(self) -> None:
        if self.model != DEFAULT_MODEL:
            raise ValueError("the external worker model is fixed to the approved default")
        if self.reasoning != DEFAULT_REASONING:
            raise ValueError("the external worker reasoning level is fixed to the approved default")
        if self.command != _APP_SERVER_COMMAND:
            raise ValueError("the external worker command is fixed to the app-server entrypoint")
        if tuple(ref.location for ref in self.protected_environment) != ("HOME", "CODEX_HOME"):
            raise ValueError("the external worker may reuse only HOME and CODEX_HOME references")

    def as_dict(self) -> dict[str, object]:
        return {
            "command": list(self.command),
            "model": self.model,
            "reasoning": self.reasoning,
            "config_overrides": [CODEX_REASONING_CONFIG],
            "protected_environment": [ref.as_dict() for ref in self.protected_environment],
        }


def build_codex_cli_launch() -> CodexCliLaunch:
    """Return fixed launch metadata without resolving or starting the executable."""

    return CodexCliLaunch()
