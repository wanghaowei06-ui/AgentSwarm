#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
capture="$repo_root/scripts/testweaver-native-hero-capture.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"

cat >"$tmp/bin/docker" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
printf '%q ' "$@" >>"$FAKE_DOCKER_CALLS"
printf '\n' >>"$FAKE_DOCKER_CALLS"

if [[ "${1:-}" == ps ]]; then
  printf '%s\n' manager-box explore-leader-box explore-worker-box dsh-box boundary-box verify-leader-box verify-worker-box outcome-box
  exit 0
fi
if [[ "${1:-}" == logs ]]; then
  printf '2026-09-03T00:00:00Z actor ready token=%s\n' "$TOKEN_SENTINEL"
  exit 0
fi
if [[ "${1:-}" == inspect && "${2:-}" == --format ]]; then
  case "${4:-}" in
    manager-box) printf 'AGENTTEAMS_MANAGER_NAME=default\nAGENTTEAMS_MANAGER_MATRIX_TOKEN=%s\n' "$TOKEN_SENTINEL" ;;
    explore-leader-box) printf 'AGENTTEAMS_WORKER_NAME=explore-leader\n' ;;
    explore-worker-box) printf 'AGENTTEAMS_WORKER_NAME=explore-worker\n' ;;
    dsh-box) printf 'AGENTTEAMS_WORKER_NAME=dsh-worker\n' ;;
    boundary-box) printf 'AGENTTEAMS_WORKER_NAME=boundary-oracle\n' ;;
    verify-leader-box) printf 'AGENTTEAMS_WORKER_NAME=verify-leader\n' ;;
    verify-worker-box) printf 'AGENTTEAMS_WORKER_NAME=verify-worker\n' ;;
    outcome-box) printf 'AGENTTEAMS_WORKER_NAME=outcome-oracle\n' ;;
  esac
  exit 0
fi
if [[ "${1:-}" == inspect ]]; then
  name=${2:-unknown}
  printf '[{"Name":"/%s","Id":"id-%s","Image":"sha256:image","RestartCount":0,"Config":{"Image":"image:%s"},"State":{"Status":"running","StartedAt":"2026-09-03T00:00:00Z","Health":{"Status":"healthy"}}}]\n' "$name" "$name" "$name"
  exit 0
fi
if [[ "${1:-}" != exec ]]; then exit 1; fi
shift
while [[ "${1:-}" == -e ]]; do shift 2; done
container=$1; shift

if [[ "$container" == agt-box && "${1:-}" == agt && "${2:-}" == get ]]; then
  case "$3" in
    managers) printf '%s\n' '{"total":1,"managers":[{"name":"default","phase":"Running","runtime":"openclaw","model":"manager-model","matrixUserID":"@manager:hs"}]}' ;;
    teams) printf '%s\n' '{"total":2,"teams":[{"name":"explore","phase":"Active","leaderName":"explore-leader","workerNames":["explore-worker","dsh-worker","boundary-oracle"]},{"name":"verify","phase":"Active","leaderName":"verify-leader","workerNames":["verify-worker","outcome-oracle"]}]}' ;;
    workers) printf '%s\n' '{"total":7,"workers":[{"name":"explore-leader","runtime":"openclaw","matrixUserID":"@explore-leader:hs"},{"name":"explore-worker","runtime":"openclaw","matrixUserID":"@explore-worker:hs"},{"name":"dsh-worker","runtime":"qwenpaw","model":"deepseek","matrixUserID":"@dsh-worker:hs"},{"name":"boundary-oracle","runtime":"openclaw","matrixUserID":"@boundary-oracle:hs"},{"name":"verify-leader","runtime":"openclaw","matrixUserID":"@verify-leader:hs"},{"name":"verify-worker","runtime":"openclaw","matrixUserID":"@verify-worker:hs"},{"name":"outcome-oracle","runtime":"openclaw","matrixUserID":"@outcome-oracle:hs"}]}' ;;
    projects) printf '%s\n' '{"total":1,"projects":[{"id":"project-1","status":"running"}]}' ;;
    tasks) printf '%s\n' '{"total":1,"tasks":[{"id":"task-1","status":"running"}]}' ;;
  esac
  exit 0
fi

all="$*"
case "$container" in
  manager-box) matrix_user='@manager:hs' ;;
  explore-leader-box) matrix_user='@explore-leader:hs' ;;
  explore-worker-box) matrix_user='@explore-worker:hs' ;;
  dsh-box) matrix_user='@dsh-worker:hs' ;;
  boundary-box) matrix_user='@boundary-oracle:hs' ;;
  verify-leader-box) matrix_user='@verify-leader:hs' ;;
  verify-worker-box) matrix_user='@verify-worker:hs' ;;
  outcome-box) matrix_user='@outcome-oracle:hs' ;;
  *) matrix_user='@unknown:hs' ;;
esac
if [[ "$all" == *'account/whoami'* ]]; then
  printf '{"user_id":"%s"}\n' "$matrix_user"
elif [[ "$all" == *'joined_rooms'* ]]; then
  printf '%s\n' '{"joined_rooms":["!hero:hs"]}'
elif [[ "$all" == *'/messages?dir=b'* ]]; then
  printf '%s\n' '{"chunk":[{"event_id":"$human-event","sender":"@human:hs","origin_server_ts":9999999999999}]}'
elif [[ "$all" == *'/event/'* ]]; then
  printf '%s\n' '{"event_id":"$human-event","room_id":"!hero:hs","sender":"@human:hs","origin_server_ts":9999999999999,"type":"m.room.message","content":{"msgtype":"m.text","body":"approved"}}'
elif [[ "$all" == *'/profile/'* ]]; then
  printf '%s\n' '{"displayname":"External Human"}'
elif [[ "$all" == *'/api/agents/default/skills'* ]]; then
  printf '%s\n' '{"skills":[{"name":"evidence","enabled":true}]}'
elif [[ "$all" == *'find /root/manager-workspace'* ]]; then
  printf '%s\n' '/root/manager-workspace/.openclaw/agents/main/sessions/hero.jsonl'
elif [[ "$all" == *'find /root/agentteams-fs/agents'* ]]; then
  :
elif [[ "$all" == *'find "$root/projects"'* ]]; then
  printf '%s\n' "/root/agentteams-fs/teams/explore/shared/tasks/task-1/meta.json"
  printf '%s\n' "/root/agentteams-fs/teams/explore/shared/tasks/task-1/result.md"
elif [[ "$all" == *'cat "$1"'* && "$all" == *'/sessions/hero.jsonl'* ]]; then
  printf '%s\n' '{"id":"req","timestamp":"2026-09-03T00:01:00Z","type":"message","message":{"role":"user","content":"campaign-1 run-1 trace-1"}}'
  printf '%s\n' '{"id":"res","timestamp":"2026-09-03T00:01:01Z","durationMs":123,"type":"message","message":{"role":"assistant","provider":"gateway","model":"manager-model","usage":{"input":10,"output":5}}}'
elif [[ "$all" == *'cat "$1"'* && "$all" == *'/meta.json'* ]]; then
  printf '%s\n' '{"task_id":"task-1","project_id":"project-1","status":"submitted","assigned_to":"@explore-worker:hs","result_status":"SUCCESS","eventId":"$task-event"}'
elif [[ "${1:-}" == sha256sum ]]; then
  printf '%064d  %s\n' 1 "${2:-file}"
else
  exit 1
fi
FAKE
chmod +x "$tmp/bin/docker"

export PATH="$tmp/bin:$PATH"
export FAKE_DOCKER_CALLS="$tmp/docker.calls"
export TOKEN_SENTINEL='super-secret-token-value'
allowlist="$tmp/humans.allow"
printf '%s\n' '@human:hs' >"$allowlist"
chmod 600 "$allowlist"
evidence="$tmp/evidence"

args=(--run-id run-1 --campaign-id campaign-1 --trace-id trace-1 --evidence-dir "$evidence" \
  --agt-container agt-box --team explore --team verify --human-allowlist "$allowlist" --pg-container NONE)

bash "$capture" start "${args[@]}"
test -f "$evidence/manifest.json"
test -f "$evidence/SHA256SUMS"
jq -e '.status=="ACTIVE" and .classification=="NOT_ASSESSED" and .live_claimed==false' "$evidence/manifest.json" >/dev/null
jq -e '[.actors[].name] | index("dsh-worker") and index("boundary-oracle") and index("outcome-oracle")' "$evidence/latest/roster.json" >/dev/null
test "$(jq '.teams|length' "$evidence/latest/roster.json")" -eq 2
test -f "$evidence/latest/authority/managers.json.raw.sha256"
jq -e '.status=="OBSERVED_PROVIDER_TURN" and .provider_models[0].provider=="gateway" and .request_hash!="NOT_OBSERVED" and .response_hash!="NOT_OBSERVED"' "$evidence/latest/manager-choice-readback.json" >/dev/null
jq -e 'select(.task_id=="task-1" and .status=="submitted" and .raw_bytes_sha256)' "$evidence/latest/shared-fs/task-metadata.jsonl" >/dev/null

index=$(find "$evidence/latest/matrix" -name event-index.jsonl -print -quit)
test -n "$index"
jq -e 'select(.identity_binding=="HUMAN_ALLOWLIST_EXACT" and .immutable_source.raw_bytes_sha256)' "$index" >/dev/null
exact_ref=$(jq -r '.immutable_source.ref' "$index" | head -1)
test -f "$evidence/$exact_ref"
test -f "${evidence}/${exact_ref%.json}.raw.sha256"
whoami=$(find "$evidence/latest/matrix" -name whoami.json -print -quit)
test -n "$whoami"
test -f "${whoami%.json}.raw.sha256"

sleep 1
bash "$capture" snapshot "${args[@]}"
sleep 1
bash "$capture" stop "${args[@]}"
jq -e '.status=="STOPPED" and .checksum_state=="FINAL"' "$evidence/manifest.json" >/dev/null
(cd "$evidence" && sha256sum -c SHA256SUMS >/dev/null)

if rg -F "$TOKEN_SENTINEL" "$evidence" --glob '!*.sha256' --glob '!SHA256SUMS' >/dev/null; then
  printf 'secret sentinel leaked into evidence\n' >&2
  exit 1
fi
if rg -i '(/send/|createRoom|agt (create|delete|update)|provider.*curl)' "$FAKE_DOCKER_CALLS" >/dev/null; then
  printf 'a prohibited mutating command was observed\n' >&2
  exit 1
fi

if bash "$capture" start --run-id bad --campaign-id bad --trace-id bad --evidence-dir "$tmp/bad" \
  --agt-container agt-box --team explore --human-allowlist "$allowlist" --pg-container NONE >/dev/null 2>&1; then
  printf 'one-Team invocation unexpectedly succeeded\n' >&2
  exit 1
fi

printf 'native hero capture tests: PASS\n'
