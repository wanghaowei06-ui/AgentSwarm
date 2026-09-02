"""Thin, in-memory governance contracts for TestWeaver Skill versions.

AgentTeams remains the owner of Skill discovery, loading, invocation, and all
Agent/Task lifecycle state.  This package only validates externally supplied
references and advances an explicit Skill-evolution review record.
"""

from .state import (
    ArtifactRef,
    Attribution,
    Baseline,
    CanaryObservation,
    ExternalReadback,
    HumanDecision,
    HumanDecisionVerification,
    ReevaluationObservation,
    SkillEvolution,
    SkillOpsError,
    SkillOpsStateError,
    SkillOperationVerification,
    SkillProposal,
    SkillReceipt,
)
from .publish import (
    NativePackageError,
    NativePackageRef,
    build_native_publish_intent,
    verify_native_package_readback,
    verify_nacos_candidate_readback,
)
from .nacos import (
    NACOS_BASE_URL,
    NACOS_CONTAINER,
    NACOS_GROUP,
    NACOS_NAMESPACE,
    NacosClient,
    NacosCandidateReadback,
    NacosHttpResponse,
    NacosNotFound,
    NacosRegistry,
    NacosRegistryError,
    NacosV3Client,
)
from .provenance import (
    agentloop_readback_from_observability,
    matrix_readback_from_authority,
    verify_skill_operation_receipt,
)

__all__ = [
    "ArtifactRef",
    "Attribution",
    "Baseline",
    "CanaryObservation",
    "ExternalReadback",
    "HumanDecision",
    "HumanDecisionVerification",
    "ReevaluationObservation",
    "SkillEvolution",
    "SkillOpsError",
    "SkillOpsStateError",
    "SkillOperationVerification",
    "SkillProposal",
    "SkillReceipt",
    "NativePackageError",
    "NativePackageRef",
    "build_native_publish_intent",
    "verify_native_package_readback",
    "verify_nacos_candidate_readback",
    "NACOS_BASE_URL",
    "NACOS_CONTAINER",
    "NACOS_GROUP",
    "NACOS_NAMESPACE",
    "NacosClient",
    "NacosCandidateReadback",
    "NacosHttpResponse",
    "NacosNotFound",
    "NacosRegistry",
    "NacosRegistryError",
    "NacosV3Client",
    "agentloop_readback_from_observability",
    "matrix_readback_from_authority",
    "verify_skill_operation_receipt",
]
