# Skill evolution state contract

This is the thin governance boundary for the five declarative TestWeaver
Skills. The state contract stores references, hashes, and review state in
memory; it does not load or edit `SKILL.md`, discover packages, or create/route
AgentTeams work. AgentTeams remains authoritative for Skill discovery,
loading, invocation, and Agent/Project/Task state.

## Closed flow

An external collector/evaluator supplies the following immutable sequence:

```text
real baseline dataset/evaluation + same-run trace/evidence refs
  -> attribution
  -> proposal(base_version, candidate_version, content_hash, rollback_ref)
  -> external HumanDecision
  -> canary
  -> same dataset/evaluation reevaluation
  -> explicit PROMOTE or ROLLBACK receipt
```

`ArtifactRef` carries only a reference, `sha256:` hash, source kind, explicit
`provenance`, and explicit `classification`. Observation refs require a run ID,
`provenance=LIVE`, and `classification=LIVE_ATTESTED`; constructing one also
requires the opaque `ExternalReadback` token produced after an external
collector has read and hashed the raw source. `attested=True`, a renamed
fixture, or a caller-supplied mapping is never sufficient. `FIXTURE`,
`SYNTHETIC`, and `REPLAY` remain non-LIVE by explicit classification;
reference names are never inspected for those meanings.

`HumanDecision` is immutable and sealed by `record_hash`. It carries a positive
`decision_revision` plus opaque `actor_ref`, `identity_ref`, and
`attestation_ref` values. These fields are not authority. Advancing the
lifecycle requires the caller to supply an external readback verifier; the
verifier must return a sealed `HumanDecisionVerification` whose source is
`matrix-live-readback` and whose event, sender, proposal, revision, baseline,
and run fields match the lifecycle, and the verification must carry a raw
event readback token. A missing, false, exceptional, malformed, or mismatched
verifier result is rejected. `Attribution` stores
`baseline_run_id` and requires every trace/evidence reference to use that exact
run.

This module does not send or read Matrix events. The Hero integration layer
must obtain the authoritative raw homeserver event and provide the verifier
result plus its readback token. Unit-test fakes exercise only this fail-closed
contract; they are not LIVE evidence.

`publish.py` is only a reference seam for the existing AgentTeams
`nacos://` AgentSpec/package path. It validates a proposal's immutable package
URI, version, content hash, and rollback reference, then verifies selected
names-only fields returned by the official native publish/readback path.
`nacos.py` contains only the old source's Nacos v3 upload/submit/publish,
download, config publish, and exact readback calls. It reuses the existing
`tw-g8-nacos` endpoint name but never starts or inspects a server. The existing
`SkillEvolution` object remains responsible for external Human approval,
canary, reevaluation, promotion, and rollback records; no second runtime is
implemented.

The state object has no method that signs a decision, changes a Skill, or
performs a promotion/rollback; `close()` only records an already-created
receipt. Promotion is blocked unless both external canary and reevaluation
records say `PASS`, and those observations must point to different result
references and different result hashes even when they use the identical frozen
dataset and evaluation. A `FAIL` canary must be closed with the existing
explicit `ROLLBACK` receipt action (P1 operational requirement); no new
lifecycle state or scheduler is introduced.

`schema.json` is the strict interchange schema (`additionalProperties: false`)
for each record. `Proposal.content_hash` is the candidate package/content hash;
`record_hash` seals the proposal metadata. No candidate body, Golden content,
credential, prompt, or runtime output is accepted by this boundary.

## Reuse boundary

The current `testweaver/skills/bundle-manifest.json`, native AgentSpec package,
and the existing OpenWorker public-input/evaluation contracts remain the
package and evaluation sources. The old `packages/skillops` schemas supplied
field-shape guidance only. Its runner, replay, graph/scheduler, runtime,
AgentLoop release, Nacos mutation, and receipt artifacts are deliberately not
migrated.

The focused tests use bounded contract values only. They are not LIVE runs and
do not read the Golden boundary file or start an AgentTeams component.
