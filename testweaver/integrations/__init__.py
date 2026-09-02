"""Thin post-run integrations around AgentTeams-native execution.

Nothing in this package creates or updates an AgentTeams Project, Task, Room,
Team, or Worker.  AgentTeams remains the execution control plane.
"""

from .agentloop_client import (
    AgentLoopCallResult,
    AgentLoopClient,
    AgentLoopCredentialLease,
    AgentLoopEndpoint,
    AgentLoopHTTPResponse,
    AgentLoopReceipt,
    AgentLoopScope,
)
from .heterogeneity import CandidateCapability, HeterogeneityPolicyFact
from .matrix_readback import MatrixDecisionExpectation, MatrixHumanReadbackVerifier
from .projector import NativeEventProjector, ProjectionError

__all__ = [
    "AgentLoopCallResult",
    "AgentLoopClient",
    "AgentLoopCredentialLease",
    "AgentLoopEndpoint",
    "AgentLoopHTTPResponse",
    "AgentLoopReceipt",
    "AgentLoopScope",
    "CandidateCapability",
    "HeterogeneityPolicyFact",
    "MatrixDecisionExpectation",
    "MatrixHumanReadbackVerifier",
    "NativeEventProjector",
    "ProjectionError",
]
