# Offline Hero evidence bundle

`scripts/testweaver-hero-bundle.py` is a read-only post-run packager. It accepts
only a completed `testweaver-native-hero-capture.sh` evidence directory
(`STOPPED` + `FINAL`) and fixed, checksum-covered fact paths. It never starts a
Hero, creates AgentTeams work, sends Matrix events, calls a provider, or fills
in missing evidence.

Additional externally produced facts belong under the capture directory at:

```text
facts/hitl/
facts/recovery/
facts/oracles/outcome.json
facts/oracles/boundary.json
facts/otel/
facts/agentloop/
```

They must already be listed in the capture's final `SHA256SUMS`. Oracle JSON
uses the existing `OracleResult` shape. Missing facts remain `NOT_OBSERVED`;
invalid authority or independence bindings become `BLOCKED`; incomplete groups
become `PARTIAL`. The bundle classification is evidence completeness only and
is never `PASS` or `LIVE`.

Build, verify, and independently replay without external services:

```bash
python3 scripts/testweaver-hero-bundle.py build \
  /absolute/path/to/completed-hero-evidence hero-evidence.zip \
  --source-commit "$(git rev-parse HEAD)"
python3 scripts/testweaver-hero-bundle.py verify hero-evidence.zip
python3 scripts/testweaver-hero-bundle.py replay hero-evidence.zip
```

The archive contains a deterministic `manifest.json`, `SHA256SUMS`, the
allowlisted original evidence under `source/`, and a standard-library-only
`replay.py`. Copy the ZIP anywhere and run:

```bash
python3 replay.py hero-evidence.zip
```

`replay.py` verifies both archive receipts and every bundled byte; it does not
re-execute the original run.
