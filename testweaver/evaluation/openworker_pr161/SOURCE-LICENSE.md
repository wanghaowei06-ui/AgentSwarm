# OpenWorker PR #161 evaluation provenance

This directory contains a behavioral evaluation contract only. No OpenWorker source code is copied.

## Pinned upstream source

- Repository: <https://github.com/andrewyng/openworker>
- Pull request: `#161`, merged as `38e1f030219c75e7423a9a9813253d8178915db7`
- Vulnerable comparison: parent-side historical commit
  `98445fee112eec07423da5eeef2a3ebba54f6acd`
- Source path: `coworker/inbox_routing.py`
- Vulnerable SHA-256:
  `9170af275ab252b338651dd1dc5d357ad1f3a54525ad94f86942f16f8005e519`
- Fixed SHA-256:
  `1a75dad625fdb6c9257b3d9225175042579c6a8712d40532aed7e37f3431c98e`
- Upstream license: MIT License, as recorded by the upstream `LICENSE` at the fixed
  commit. The upstream copyright notice is retained here for attribution:
  `Copyright (c) 2024 Andrew Ng`.

The pinned source is used only as an immutable target reference. The public
inputs are a small re-expression of the upstream regression behavior; the
expected boundary is stored separately and is not part of public target input.

## TestWeaver asset provenance

- Register: `27157efd241ed1028f20074530315b88c6f5491a`
- Register location in the supplying repository:
  `docs/business/native-asset-inheritance-register.md`
- Machine register in that commit:
  `artifacts/verification/semifinal/native-asset-inheritance-register.json`
- Relevant classifications: `GOLD-EVALUATION-BASELINE-007` is historical
  scoped/reusable; `HERO-GOLDEN-PUBLIC-HOLDOUT-008` is archive-only pending a
  real native trigger.
- Supplying TestWeaver repository license: Apache License 2.0.

Only the public case inputs, separated expected boundary, provenance metadata,
and an offline verifier contract are carried forward. The old target runner,
TaskRun/Scheduler/Manager/Observer control code, and old receipt/evidence files
are explicitly excluded.

## AgentTeams domain-asset gap audit

The pinned AgentTeams baseline
`2ea027403398dfa06f3fc86445042d59f4684d71` has zero paths matching
`evaluation`, `gold`, `dataset`, `benchmark`, `runner`, `verifier`, or `metric`.
The observed official `main` commit
`223ddc2b8073e4c8b93bcbb15e1d717f196c04d9` likewise exposes runtime, tests,
and generic AgentLoop integration, but no OpenWorker PR #161 domain suite.
Therefore this small evaluation asset remains in TestWeaver's evaluation
boundary; it does not duplicate an AgentTeams-owned dataset.
