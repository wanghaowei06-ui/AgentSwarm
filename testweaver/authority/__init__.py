"""Thin TestWeaver authority projections; native AgentTeams remains in charge."""

from .capsule import CapsuleAuthority, CapsuleHit, CapsuleRecord, FailureCapsule, ProcessCapsule
from .hitl import HITLAuthority, HITLRecord, HumanReadbackAttestation, HumanReadbackVerifier
from .ledger import SideEffectEntry, SideEffectLedger
from .oracle import OracleAuthority, OracleResult, validate_oracle_pair
from .store import (
    AuthorityConflict,
    AuthorityError,
    AuthorityEvent,
    AuthorityStore,
    PostgresAuthorityStore,
    RecordInsert,
    canonical_json,
    digest_bytes,
    safe_metadata,
    seal,
    validate_hash,
    validate_ref,
)

__all__ = [
    "AuthorityConflict",
    "AuthorityError",
    "AuthorityEvent",
    "AuthorityStore",
    "CapsuleAuthority",
    "CapsuleHit",
    "CapsuleRecord",
    "FailureCapsule",
    "HITLAuthority",
    "HITLRecord",
    "HumanReadbackAttestation",
    "HumanReadbackVerifier",
    "OracleAuthority",
    "OracleResult",
    "PostgresAuthorityStore",
    "ProcessCapsule",
    "RecordInsert",
    "SideEffectEntry",
    "SideEffectLedger",
    "canonical_json",
    "digest_bytes",
    "safe_metadata",
    "seal",
    "validate_hash",
    "validate_oracle_pair",
    "validate_ref",
]
