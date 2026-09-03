# TestWeaver native artifact contracts

This directory contains the smallest TestWeaver data contract for sharing a
claim and its supporting material across AgentTeams-native work. The native
project, task, and room identifiers in `native_refs` are references only. The
`read_only` marker is required, and no native room or task state is reproduced
here.

Each artifact is carried by the native TeamHarness artifact path. Its
`artifact.channel` is either `filesync` or `message`; this package does not
implement transport or execution behavior. The artifact reference is only a
provenance pointer.

`content_hash` is the SHA-256 of the canonical JSON object after removing the
top-level `content_hash` field. Canonical JSON uses UTF-8, sorted object keys,
and compact separators, matching the thin hashing behavior of the source
implementation.

The examples in `tests/` are synthetic validation fixtures. They are marked
`TEST_FIXTURE_ONLY_NOT_LIVE` and are not LIVE evidence.

The JSON files are the interchange contract. `validator.py` is a dependency-
free focused validator for strict local checks; it has no authority to create,
route, or mutate native work.
