# TestWeaver authority projections

This package stores sealed, metadata-only authority records. AgentTeams remains
the owner of rooms, tasks, agents, providers, and scheduling; this package does
not send Matrix events, invoke a provider, create a task, or run an observer.

## External human decisions

`APPROVE`, `DENY`, and `RESUME` require a caller-supplied
`HumanReadbackVerifier`. The verifier is an integration seam: it must read the
authoritative homeserver event outside this package and return a sealed
`HumanReadbackAttestation` from that readback. The attestation binds the event
reference and hash, sender and identity reference, approval/run/campaign/trace
lineage, revision, decision, verification time, and its own record hash.
`HITLAuthority` compares every bound field and persists only the attestation
reference and sealed hash. A missing, failing, unsealed, or mismatched verifier
result is rejected. The unit-test verifier is a contract fake, not LIVE
evidence; production integration must supply the raw Matrix readback.

## Atomic Oracle pair persistence

`OracleAuthority.persist_pair` validates both results and appends both rows via
one database transaction. A failure on the second insert rolls the first back.
Identical sealed hashes replay idempotently; a different hash raises
`AuthorityConflict`. `AuthorityStore` accepts an existing DB-API connection;
SQLite tests cover the local contract and PostgreSQL 16 verification is required
for deployment.
