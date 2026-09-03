# AgentSwarm

[English](./README.en.md) | [中文](./README.md)

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](./LICENSE)
[![Competition snapshot](https://img.shields.io/badge/competition-v1.2-6f42c1.svg)](./docs/competition-reproduction.md)

> AgentSwarm is the public competition distribution based on the upstream open-source [AgentTeams](https://github.com/agentscope-ai/AgentTeams) project. It keeps AgentTeams' real runtime source, image names, environment variables, APIs, and installation contracts, while adding a competition reproduction entry point, public-boundary documentation, test/trace specifications, and repository governance.

This repository does not re-claim upstream code as independent AgentSwarm work. The `AgentTeams` names in source files are runtime interfaces; AgentSwarm names this competition distribution and its curated public deliverables.

## Start here

- [Competition reproduction guide](./docs/competition-reproduction.md)
- [Open-source boundary and provenance](./docs/open-source-boundary.md)
- [Third-party dependency inventory](./docs/dependencies.md)
- [Contributing guide](./CONTRIBUTING.md)
- [Security response](./SECURITY.md)
- [Release history](./CHANGELOG.md)
- [Runnable example](./examples/README.md)

## AgentSwarm and AgentTeams

| Area | Scope |
| --- | --- |
| AgentTeams Controller, Manager, Workers, Matrix, Helm, and installer contracts | Real open-source system content from upstream AgentTeams; source paths and interfaces remain unchanged |
| AgentSwarm competition entry point | This repository's bilingual README, fixed-tag reproduction guide, dependency and public-boundary documents |
| Dashboard and public TestWeaver material | Runnable source, interface/trace specifications, and repeatable test helpers included in this snapshot |
| Local evidence, logs, secrets, and personal environment material | Explicitly excluded; never presented as source capability or evaluation proof |
| Upstream contribution, adoption, and co-maintenance | Claimed only when backed by a public URL; this release makes no unverified claim |

For upstream history and community activity, visit the [AgentTeams upstream repository](https://github.com/agentscope-ai/AgentTeams). For this competition submission, use a fixed tag and the [competition reproduction guide](./docs/competition-reproduction.md).

## Open source surface

The public tree contains the parts that can be rebuilt and checked from a clean checkout:

| Path | Contents |
| --- | --- |
| `agentteams-controller/` | Go Controller, CRDs, REST API, `agt` CLI, and controller tests |
| `manager/` | Manager image, startup scripts, templates, prompts, and Manager Skills |
| `worker/`, `qwenpaw/`, `copaw/`, `hermes/`, `openhuman/` | Worker runtimes and image entrypoints |
| `openclaw-base/` | OpenClaw Manager/Worker base image |
| `plugins/` | TeamHarness, WorkerFlow, and runtime extensions |
| `helm/`, `install/`, `shared/` | Kubernetes chart, embedded installer, and shared scripts |
| `dashboard/` | Optional interface over real Matrix/Controller data |
| `tests/`, `testweaver/` | Integration tests, adapters, evaluation/trace contracts, and reproduction helpers |
| `docs/`, `design/` | Architecture, deployment, interface, runtime, and competition documentation |

## Competition reproduction

The current public distribution is `competition-v1.2`. The earlier `competition-v1.1` remains an immutable historical snapshot; evaluators should use a fixed tag rather than the moving `main` branch.

The following path builds real images from this repository and installs the embedded system. It does not use mocks, offline replay, or pre-recorded evidence:

~~~bash
git clone https://github.com/wanghaowei06-ui/AgentSwarm.git
cd AgentSwarm
git checkout competition-v1.2

export VERSION=competition-v1.2
export OPENCLAW_BASE_IMAGE=agentteams/openclaw-base
export OPENCLAW_BASE_VERSION=competition-v1.2
export AGENTTEAMS_DASHBOARD=0

make build-openclaw-base
make install-embedded
make wait-ready-embedded
make verify
~~~

See the [competition reproduction guide](./docs/competition-reproduction.md) for model API setup, credentials, ports, resource requirements, live task execution, and output retention. Pass API keys through environment variables only.

## Installation and deployment

The repository provides two real installation deliverables:

- **Docker embedded** for evaluators and local use, using the root `Makefile`, `install/`, and embedded image.
- **Kubernetes Helm** for team or production-style deployments, using `helm/agentteams/` for the Controller, gateway, Matrix, storage, and Manager configuration.

See the [Chinese quickstart](./docs/zh-cn/quickstart.md), [architecture](./docs/zh-cn/architecture.md), [Windows deployment](./docs/zh-cn/windows-deploy.md), [development guide](./docs/zh-cn/development.md), [Helm chart](./helm/agentteams/), and [installer documentation](./install/README.md).

The public repository provides source installation and deployment files. It does not claim to be a separately published PyPI/npm package, and external registries, model providers, and SaaS services remain external dependencies.

## Architecture

AgentTeams coordinates Manager, Workers, and humans in Matrix rooms:

~~~text
Human
  │ Element Web / Matrix Client
  ▼
Matrix Homeserver (Tuwunel) ─── shared files (MinIO / OSS)
  │
  ▼
Manager Agent ─── AI Gateway (Higress) ─── online LLM provider
  │
  ├── OpenClaw Worker
  ├── QwenPaw / CoPaw Worker
  ├── Hermes Worker
  └── OpenHuman Worker
~~~

The Manager decomposes and coordinates work; Workers execute it; the Matrix room keeps the collaboration context visible so a human can observe and intervene. See the [architecture documentation](./docs/zh-cn/architecture.md) for runtime boundaries.

## Dashboard, tests, and trace

The Dashboard is an optional real-data interface. It does not generate demo projects, seed data, or fabricated messages; it reads data returned by the Controller and Matrix. See [Dashboard README](./dashboard/README.md) for local build, configuration, and checks.

Repeatable checks include:

~~~bash
make verify
make test-installed TEST_FILTER="01"
python3 -m unittest discover -s testweaver/adapters/tests -p 'test_*.py'
~~~

The public TestWeaver tree contains adapters, contracts, Skill/Schema material, and trace specifications. Historical evidence directories, container logs, and local run state are not public deliverables.

## Version and maintenance

- `competition-v1.2` is the current public distribution; `competition-v1.1` is the previously published immutable competition snapshot.
- Future public changes are verified on `main` before a new immutable tag is created.
- See [CHANGELOG.md](./CHANGELOG.md), [NOTICE](./NOTICE), and the [open-source boundary](./docs/open-source-boundary.md).
- See [MAINTAINERS.md](./MAINTAINERS.md) for the current maintainer and support scope.
- Use [GitHub Issues](https://github.com/wanghaowei06-ui/AgentSwarm/issues) and the [contributing guide](./CONTRIBUTING.md) for bugs, feature requests, and pull requests.

## Upstream contribution and adoption statement

This repository does not present its own commit history, competition evaluation logs, or static screenshots as upstream AgentTeams contributions, third-party adoption, or co-maintenance evidence. If a merged upstream PR, public issue, external deployment report, or co-maintainer record becomes available, it will be linked directly in the release notes.

## License

This repository follows Apache License 2.0; see [LICENSE](./LICENSE) and [NOTICE](./NOTICE). Files with their own source or license notice take precedence, and third-party dependencies remain under their respective licenses.
