#!/usr/bin/env bash
# Names-only configuration preflight for REAL-AGENTLOOP-OTEL-010.
#
# Protected sources are inspected internally only to check names and probe
# already configured endpoints. Values are never printed, serialized, or
# logged. This script never starts a container, changes a service, calls a
# model, queries AgentLoop, or sends a trace.
set +x 2>/dev/null || true
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REFERENCE_FILE="${TESTWEAVER_REFERENCE_FILE:-${SCRIPT_DIR}/../testweaver/config/runtime.env}"
REQUIRED_NAMES_FILE="${TESTWEAVER_REQUIRED_NAMES_FILE:-${SCRIPT_DIR}/../testweaver/config/agentteams-required-vars.txt}"
MANAGER_CONTAINER=""
NACOS_SOURCE_CONTAINER=""
OTEL_CONTAINER=""
NETWORK_CHECK=1
BLOCKING_GAPS=0

usage() {
  printf '%s\n' \
    "Usage: $0 [--reference FILE] [--required-names FILE]" \
    "          [--manager-container NAME] [--nacos-source-container NAME]" \
    "          [--otel-container NAME] [--no-network]"
}

while (($#)); do
  case "$1" in
    --reference|--config|--required-names|--manager-container|--nacos-source-container|--otel-container)
      (($# >= 2)) || { usage >&2; exit 2; }
      case "$1" in
        --reference|--config) REFERENCE_FILE="$2" ;;
        --required-names) REQUIRED_NAMES_FILE="$2" ;;
        --manager-container) MANAGER_CONTAINER="$2" ;;
        --nacos-source-container) NACOS_SOURCE_CONTAINER="$2" ;;
        --otel-container) OTEL_CONTAINER="$2" ;;
      esac
      shift 2
      ;;
    --no-network) NETWORK_CHECK=0; shift ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
blocking_gap() { BLOCKING_GAPS=1; say "GAP $*"; }
deferred_gap() { say "DEFERRED $*"; }

ref_value() {
  local wanted="$1"
  awk -v wanted="$wanted" '
    /^[[:space:]]*(export[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*[[:space:]]*=/ {
      line=$0
      sub(/^[[:space:]]*/, "", line)
      sub(/^export[[:space:]]+/, "", line)
      key=line
      sub(/[[:space:]]*=.*/, "", key)
      gsub(/[[:space:]]/, "", key)
      if (key != wanted) next
      sub(/^[^=]*=[[:space:]]*/, "", line)
      sub(/[[:space:]]+#.*$/, "", line)
      sub(/[[:space:]]+$/, "", line)
      if (line ~ /^".*"$/) { sub(/^"/, "", line); sub(/"$/, "", line) }
      if (line ~ /^'"'"'.*'"'"'$/) { sub(/^'"'"'/, "", line); sub(/'"'"'$/, "", line) }
      print line
    }
  ' "$REFERENCE_FILE" 2>/dev/null | tail -n 1
}

file_keys() {
  awk '
    /^[[:space:]]*(export[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*[[:space:]]*=/ {
      line=$0
      sub(/^[[:space:]]*/, "", line)
      sub(/^export[[:space:]]+/, "", line)
      key=line
      sub(/[[:space:]]*=.*/, "", key)
      gsub(/[[:space:]]/, "", key)
      print key
    }
  ' "$1" 2>/dev/null | sort -u
}

container_keys() {
  command -v docker >/dev/null 2>&1 || return 0
  docker inspect --format '{{range .Config.Env}}{{println (index (split . "=") 0)}}{{end}}' "$1" 2>/dev/null | sort -u || true
}

has_name() { grep -Fqx -- "$1" <<<"$2"; }
is_running() { command -v docker >/dev/null 2>&1 && [[ "$(docker inspect --format '{{.State.Status}}' "$1" 2>/dev/null || true)" == running ]]; }

check_parent() {
  local path="$1" owner mode
  owner="$(stat -c '%U:%G' -- "$(dirname -- "$path")" 2>/dev/null || true)"
  mode="$(stat -c '%a' -- "$(dirname -- "$path")" 2>/dev/null || true)"
  [[ "$owner" == root:root && -n "$mode" ]] || return 1
  if (( 0$mode & 022 )); then return 1; fi
  return 0
}

check_file() {
  local label="$1" path="$2" required="$3"
  local owner mode type resolved
  if [[ -z "$path" || ! -f "$path" || -L "$path" ]]; then
    if ((required)); then blocking_gap "reference=$label reason=file-unavailable"; else deferred_gap "reference=$label reason=file-unavailable"; fi
    return 1
  fi
  resolved="$(realpath -e -- "$path" 2>/dev/null || true)"
  if [[ "$resolved" != "$path" ]]; then
    if ((required)); then blocking_gap "reference=$label reason=symlinked-path"; else deferred_gap "reference=$label reason=symlinked-path"; fi
    return 1
  fi
  owner="$(stat -c '%U:%G' -- "$path" 2>/dev/null || true)"
  mode="$(stat -c '%a' -- "$path" 2>/dev/null || true)"
  type="$(stat -c '%F' -- "$path" 2>/dev/null || true)"
  if [[ "$type" != "regular file" || "$owner" != root:root ]] || ! check_parent "$path"; then
    if ((required)); then blocking_gap "reference=$label reason=permission-check"; else deferred_gap "reference=$label reason=permission-check"; fi
    return 1
  fi
  if ((required)) && [[ "$mode" != 600 ]]; then
    blocking_gap "reference=$label reason=expected-root-0600"
    return 1
  fi
  say "REUSED path=$path owner=$owner mode=$mode"
}

probe_manager_endpoint() {
  local var_name="$1" label="$2" names="$3"
  if ! has_name "$var_name" "$names"; then
    blocking_gap "endpoint=$label reason=variable-name-missing variable=$var_name"
    return
  fi
  if ((NETWORK_CHECK == 0)); then
    deferred_gap "endpoint=$label reason=network-check-disabled variable=$var_name"
    return
  fi
  if ! is_running "$MANAGER_CONTAINER"; then
    blocking_gap "endpoint=$label reason=manager-container-not-running"
    return
  fi
  if docker exec "$MANAGER_CONTAINER" sh -c '
      case "$1" in
        AGENTTEAMS_MATRIX_URL) url="${AGENTTEAMS_MATRIX_URL:-}" ;;
        AGENTTEAMS_AI_GATEWAY_URL) url="${AGENTTEAMS_AI_GATEWAY_URL:-}" ;;
        AGENTTEAMS_CONTROLLER_URL) url="${AGENTTEAMS_CONTROLLER_URL:-}" ;;
        *) exit 10 ;;
      esac
      [ -n "$url" ] || exit 11
      command -v curl >/dev/null 2>&1 || exit 12
      code="$(curl --config /dev/null --silent --show-error --output /dev/null \
        --write-out "%{http_code}" --connect-timeout 3 --max-time 6 "$url" 2>/dev/null)" || exit 13
      case "$code" in [1-5][0-9][0-9]) exit 0 ;; *) exit 14 ;; esac
    ' sh "$var_name" >/dev/null 2>&1; then
    say "REUSED endpoint=$label status=reachable source=container:$MANAGER_CONTAINER"
  else
    blocking_gap "endpoint=$label reason=probe-failed source=container:$MANAGER_CONTAINER"
  fi
}

probe_nacos() {
  local names="$1" has_uri=0 has_host_port=0
  has_name AGENTTEAMS_NACOS_REGISTRY_URI "$names" && has_uri=1
  if has_name AGENTTEAMS_NACOS_HOST "$names" && has_name AGENTTEAMS_NACOS_PORT "$names"; then has_host_port=1; fi
  if ((has_uri == 0 && has_host_port == 0)); then deferred_gap "endpoint=nacos reason=required-variable-names-missing"; return; fi
  if ((NETWORK_CHECK == 0)); then deferred_gap "endpoint=nacos reason=network-check-disabled"; return; fi
  if ! is_running "$NACOS_SOURCE_CONTAINER"; then deferred_gap "endpoint=nacos reason=source-container-not-running"; return; fi
  if docker exec "$NACOS_SOURCE_CONTAINER" sh -c '
      url="${AGENTTEAMS_NACOS_REGISTRY_URI:-}"
      if [ -z "$url" ] && [ -n "${AGENTTEAMS_NACOS_HOST:-}" ] && [ -n "${AGENTTEAMS_NACOS_PORT:-}" ]; then
        url="http://${AGENTTEAMS_NACOS_HOST}:${AGENTTEAMS_NACOS_PORT}/nacos/v1/console/health/readiness"
      fi
      [ -n "$url" ] || exit 10
      command -v curl >/dev/null 2>&1 || exit 11
      code="$(curl --config /dev/null --silent --show-error --output /dev/null \
        --write-out "%{http_code}" --connect-timeout 3 --max-time 6 "$url" 2>/dev/null)" || exit 12
      case "$code" in [1-5][0-9][0-9]) exit 0 ;; *) exit 13 ;; esac
    ' >/dev/null 2>&1; then
    say "REUSED endpoint=nacos status=reachable source=container:$NACOS_SOURCE_CONTAINER"
  else
    deferred_gap "endpoint=nacos reason=probe-failed source=container:$NACOS_SOURCE_CONTAINER"
  fi
}

if [[ ! -f "$REFERENCE_FILE" || -L "$REFERENCE_FILE" ]]; then blocking_gap "reference-file reason=unavailable"; exit 2; fi
if [[ ! -f "$REQUIRED_NAMES_FILE" || -L "$REQUIRED_NAMES_FILE" ]]; then blocking_gap "required-names-file reason=unavailable"; exit 2; fi

AGENTTEAMS_ENV_FILE="$(ref_value TESTWEAVER_AGENTTEAMS_ENV_FILE)"
PROVIDER_ENV_FILE="$(ref_value TESTWEAVER_AGENTTEAMS_PROVIDER_ENV_FILE)"
MANAGER_CONTAINER="${MANAGER_CONTAINER:-$(ref_value TESTWEAVER_AGENTTEAMS_MANAGER_CONTAINER)}"
NACOS_SOURCE_CONTAINER="${NACOS_SOURCE_CONTAINER:-$(ref_value TESTWEAVER_NACOS_SOURCE_CONTAINER)}"
AGENTLOOP_CONFIG_FILE="$(ref_value TESTWEAVER_AGENTLOOP_CONFIG_FILE)"
OTEL_CONFIG_FILE="$(ref_value TESTWEAVER_OTEL_CONFIG_FILE)"
OTEL_CONTAINER="${OTEL_CONTAINER:-$(ref_value TESTWEAVER_OTEL_CONTAINER)}"

check_file agentteams-env "$AGENTTEAMS_ENV_FILE" 1 || true
check_file provider-env "$PROVIDER_ENV_FILE" 1 || true
check_file agentloop-loongsuite-config "$AGENTLOOP_CONFIG_FILE" 0 || true
check_file otel-config "$OTEL_CONFIG_FILE" 0 || true

AGENTTEAMS_KEYS=""
PROVIDER_KEYS=""
[[ -f "$AGENTTEAMS_ENV_FILE" && ! -L "$AGENTTEAMS_ENV_FILE" ]] && AGENTTEAMS_KEYS="$(file_keys "$AGENTTEAMS_ENV_FILE")"
[[ -f "$PROVIDER_ENV_FILE" && ! -L "$PROVIDER_ENV_FILE" ]] && PROVIDER_KEYS="$(file_keys "$PROVIDER_ENV_FILE")"

provider_names="$(printf '%s\n' "$PROVIDER_KEYS" | awk '/^AGENTTEAMS_[A-Z0-9_]+_(API_KEY|BASE_URL|MODEL)$/')"
if [[ -n "$provider_names" ]]; then
  say "REUSED provider-variable-names=$(tr '\n' ',' <<<"$provider_names" | sed 's/,$//') source=$PROVIDER_ENV_FILE"
else
  deferred_gap "provider-variable-names reason=complete-name-set-not-found"
fi

MANAGER_KEYS=""
[[ -n "$MANAGER_CONTAINER" ]] && MANAGER_KEYS="$(container_keys "$MANAGER_CONTAINER")"
while IFS= read -r required_name; do
  [[ -z "$required_name" || "$required_name" == \#* ]] && continue
  source_names=""
  if has_name "$required_name" "$AGENTTEAMS_KEYS" || has_name "$required_name" "$PROVIDER_KEYS"; then source_names="etc"; fi
  if has_name "$required_name" "$MANAGER_KEYS"; then
    [[ -n "$source_names" ]] && source_names+="+"
    source_names+="container:$MANAGER_CONTAINER"
  fi
  if [[ -n "$source_names" ]]; then say "REUSED variable=$required_name source=$source_names"; else blocking_gap "variable=$required_name reason=required-name-not-found"; fi
done < "$REQUIRED_NAMES_FILE"

if [[ -z "$MANAGER_CONTAINER" ]]; then blocking_gap "manager-container reason=reference-missing"; elif ! command -v docker >/dev/null 2>&1; then blocking_gap "manager-container reason=docker-unavailable"; elif ! is_running "$MANAGER_CONTAINER"; then blocking_gap "manager-container reason=not-running"; fi
probe_manager_endpoint AGENTTEAMS_MATRIX_URL agentteams.matrix "$MANAGER_KEYS"
probe_manager_endpoint AGENTTEAMS_AI_GATEWAY_URL agentteams.gateway "$MANAGER_KEYS"
probe_manager_endpoint AGENTTEAMS_CONTROLLER_URL agentteams.controller "$MANAGER_KEYS"

NACOS_KEYS="$(container_keys "$NACOS_SOURCE_CONTAINER")"
for nacos_name in AGENTTEAMS_NACOS_REGISTRY_URI AGENTTEAMS_NACOS_HOST AGENTTEAMS_NACOS_PORT AGENTTEAMS_NACOS_USERNAME AGENTTEAMS_NACOS_PASSWORD AGENTTEAMS_NACOS_TOKEN; do
  if has_name "$nacos_name" "$NACOS_KEYS"; then say "REUSED variable=$nacos_name source=container:$NACOS_SOURCE_CONTAINER"; fi
done
probe_nacos "$NACOS_KEYS"

if [[ -n "$OTEL_CONTAINER" ]] && is_running "$OTEL_CONTAINER"; then say "REUSED endpoint=otel status=collector-container-running source=container:$OTEL_CONTAINER"; else deferred_gap "endpoint=otel reason=collector-container-not-running"; fi
if systemctl is-active --quiet loongsuite-pilot-root.service 2>/dev/null; then say "REUSED runtime=loongsuite-pilot-root status=active"; else deferred_gap "agentloop-query reason=loongsuite-pilot-root-not-active"; fi
deferred_gap "agentloop-trace reason=same-real-hero-required"
deferred_gap "agentloop-trace reason=synthetic-and-unbound-live-trace-forbidden"

if ((BLOCKING_GAPS)); then say "BLOCKED scope=m0-reference"; exit 2; fi
say "READY scope=m0-reference trace=deferred-until-same-real-hero"
exit 0
