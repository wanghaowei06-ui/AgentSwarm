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
    AgentLoopQueryVerification,
    AgentLoopReceipt,
    AgentLoopResponseSummary,
    AgentLoopScope,
)
from .heterogeneity import CandidateCapability, HeterogeneityPolicyFact
from .matrix_readback import MatrixDecisionExpectation, MatrixHumanReadbackVerifier
from .projector import NativeEventProjector, ProjectionError
from .tea_transport import (
    AlibabaCloudCredential,
    TeaAgentLoopTransport,
    load_protected_csv_credential,
)
from .xtrace_readback import (
    TeaXTraceTransport,
    XTraceCorrelation,
    XTraceHTTPResponse,
    XTraceReadbackClient,
    XTraceReadbackReceipt,
)

__all__ = [
    "AgentLoopCallResult",
    "AgentLoopClient",
    "AgentLoopCredentialLease",
    "AgentLoopEndpoint",
    "AgentLoopHTTPResponse",
    "AgentLoopQueryVerification",
    "AgentLoopReceipt",
    "AgentLoopResponseSummary",
    "AgentLoopScope",
    "AlibabaCloudCredential",
    "CandidateCapability",
    "HeterogeneityPolicyFact",
    "MatrixDecisionExpectation",
    "MatrixHumanReadbackVerifier",
    "NativeEventProjector",
    "ProjectionError",
    "TeaAgentLoopTransport",
    "TeaXTraceTransport",
    "XTraceCorrelation",
    "XTraceHTTPResponse",
    "XTraceReadbackClient",
    "XTraceReadbackReceipt",
    "load_protected_csv_credential",
]
