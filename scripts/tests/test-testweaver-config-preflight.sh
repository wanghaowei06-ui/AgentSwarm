#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PREFLIGHT="${ROOT_DIR}/scripts/testweaver-config-preflight.sh"
TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TEMP_DIR}"' EXIT

mkdir -p "${TEMP_DIR}/bin"
DOCKER_STUB="${TEMP_DIR}/bin/docker"
printf '%s\n' \
    '#!/usr/bin/env bash' \
    'set -euo pipefail' \
    'if [[ "${1:-}" == "ps" ]]; then' \
    '    printf "%s\\n" agentteams-native-manager' \
    '    exit 0' \
    'fi' \
    'if [[ "${1:-}" != "inspect" ]]; then exit 1; fi' \
    'name="${@: -1}"' \
    'if [[ "${name}" != "agentteams-native-manager" ]]; then exit 1; fi' \
    'format="${3:-}"' \
    'if [[ "${format}" == *State.Status* ]]; then' \
    '    printf "%s\\n" running' \
    'else' \
    '    printf "%s\\n" \' \
    '        AGENTTEAMS_RUNTIME AGENTTEAMS_MANAGER_RUNTIME AGENTTEAMS_MATRIX_URL \' \
    '        AGENTTEAMS_MATRIX_DOMAIN AGENTTEAMS_AI_GATEWAY_URL AGENTTEAMS_CONTROLLER_URL \' \
    '        AGENTTEAMS_LLM_PROVIDER \' \
    '        AGENTTEAMS_LLM_API_KEY AGENTTEAMS_DEFAULT_MODEL AGENTTEAMS_MANAGER_GATEWAY_KEY \' \
    '        AGENTTEAMS_MANAGER_PASSWORD AGENTTEAMS_REGISTRATION_TOKEN AGENTTEAMS_ADMIN_USER \' \
    '        AGENTTEAMS_ADMIN_PASSWORD AGENTTEAMS_MANAGER_NAME AGENTTEAMS_MANAGER_MATRIX_TOKEN' \
    'fi' \
    > "${DOCKER_STUB}"
chmod 0755 "${DOCKER_STUB}"

REFERENCE="${TEMP_DIR}/runtime.env"
printf '%s\n' \
    'TESTWEAVER_AGENTTEAMS_ENV_FILE=/etc/agentteams/agentteams.env' \
    'TESTWEAVER_AGENTTEAMS_PROVIDER_ENV_FILE=/etc/agentteams/providers.env' \
    'TESTWEAVER_AGENTTEAMS_MANAGER_CONTAINER=agentteams-manager' \
    'TESTWEAVER_NACOS_SOURCE_CONTAINER=agentteams-native-controller' \
    'TESTWEAVER_AGENTLOOP_CONFIG_FILE=/root/.loongsuite-pilot/config.json' \
    'TESTWEAVER_OTEL_CONFIG_FILE=/root/projects/muti-agent/deploy/otel/g9-collector.yaml' \
    'TESTWEAVER_OTEL_CONTAINER=tw-g9-otel-collector' \
    > "${REFERENCE}"

OUTPUT="$(
    PATH="${TEMP_DIR}/bin:${PATH}" \
    TESTWEAVER_REFERENCE_FILE="${REFERENCE}" \
    bash "${PREFLIGHT}" --no-network
)"

grep -Fq 'source=container:agentteams-native-manager' <<<"${OUTPUT}"
grep -Fq 'READY scope=m0-reference' <<<"${OUTPUT}"
! grep -Fq 'BLOCKED scope=m0-reference' <<<"${OUTPUT}"

printf '%s\n' 'PASS: AgentTeams preflight discovers the active native Manager container'
