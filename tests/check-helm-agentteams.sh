#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHART="${ROOT_DIR}/helm/agentteams"
COMMON_ARGS=(
    --set credentials.registrationToken=test
    --set credentials.adminPassword=test
    --set credentials.llmApiKey=test
    --set gateway.publicURL=http://localhost:18080
    --set worker.defaultImage.qwenpaw.repository=example/agentteams-qwenpaw-worker
    --set worker.defaultImage.qwenpaw.tag=test
)

render="$(mktemp)"
trap 'rm -f "${render}"' EXIT

grep -Fq 'qwenpaw:' "${CHART}/values.yaml"
grep -Fq 'define "agentteams.worker.qwenpawImage"' "${CHART}/templates/_helpers.tpl"
grep -Fq 'AGENTTEAMS_QWENPAW_WORKER_IMAGE' "${CHART}/templates/controller/deployment.yaml"
grep -Fq 'QWENPAW_WORKER_IMAGE="agentteams/qwenpaw-worker:local"' "${ROOT_DIR}/hack/local-k8s-up.sh"
grep -Fq 'docker build -t "$QWENPAW_WORKER_IMAGE"' "${ROOT_DIR}/hack/local-k8s-up.sh"
grep -Fq 'kind load docker-image "$QWENPAW_WORKER_IMAGE"' "${ROOT_DIR}/hack/local-k8s-up.sh"
grep -Fq 'worker.defaultImage.qwenpaw.repository=agentteams/qwenpaw-worker' "${ROOT_DIR}/hack/local-k8s-up.sh"

helm template agentteams "${CHART}" "${COMMON_ARGS[@]}" > "${render}"

grep -q 'name: agentteams-controller' "${render}"
grep -q 'app.kubernetes.io/name: agentteams' "${render}"
grep -Fq 'value: "example/agentteams-qwenpaw-worker:test"' "${render}"

echo "PASS: AgentTeams Helm release renders canonical resource names"
