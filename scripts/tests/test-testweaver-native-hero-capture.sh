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
  while :; do sleep 1; done
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
  # The same actor can observe an event through overlapping room snapshots.
  # Keep the duplicate to prove event-index records are emitted once per
  # actor/event, while the two opaque IDs below prove path names cannot alias.
  printf '%s\n' '{"joined_rooms":["!hero:hs","!hero:hs"]}'
elif [[ "$all" == *'/messages?dir=b'* ]]; then
  printf '%s\n' '{"chunk":[{"event_id":"$human-event","sender":"@human:hs","origin_server_ts":9999999999999},{"event_id":"$task-root","sender":"@explore-leader:hs","origin_server_ts":9999999999000},{"event_id":"$skill-event","sender":"@explore-worker:hs","origin_server_ts":9999999999100},{"event_id":"$collision+one","sender":"@explore-worker:hs","origin_server_ts":9999999999200},{"event_id":"$collision/one","sender":"@explore-worker:hs","origin_server_ts":9999999999300}]}'
elif [[ "$all" == *'/event/'* ]]; then
  if [[ "$all" == *'%24collision%2Bone'* ]]; then
    printf '%s\n' '{"event_id":"$collision+one","room_id":"!hero:hs","sender":"@explore-worker:hs","origin_server_ts":9999999999200,"type":"m.room.message","content":{"msgtype":"m.text","body":"collision plus"}}'
  elif [[ "$all" == *'%24collision%2Fone'* ]]; then
    printf '%s\n' '{"event_id":"$collision/one","room_id":"!hero:hs","sender":"@explore-worker:hs","origin_server_ts":9999999999300,"type":"m.room.message","content":{"msgtype":"m.text","body":"collision slash"}}'
  elif [[ "$all" == *'%24task-root'* ]]; then
    printf '%s\n' '{"event_id":"$task-root","room_id":"!hero:hs","sender":"@explore-leader:hs","origin_server_ts":9999999999000,"type":"m.room.message","content":{"msgtype":"m.text","body":"@explore-worker:hs TASK_ASSIGNED task-1"}}'
  elif [[ "$all" == *'%24skill-event'* ]]; then
    printf '%s\n' '{"event_id":"$skill-event","room_id":"!hero:hs","sender":"@explore-worker:hs","origin_server_ts":9999999999100,"type":"m.room.message","content":{"msgtype":"m.text","body":"🔧 **read_file**\n```\n{\"file_path\":\"/root/agentteams-fs/agents/explore-worker/skills/evidence/SKILL.md\"}\n```","m.relates_to":{"event_id":"$task-root","rel_type":"m.thread","is_falling_back":false}}}'
  else
    printf '%s\n' '{"event_id":"$human-event","room_id":"!hero:hs","sender":"@human:hs","origin_server_ts":9999999999999,"type":"m.room.message","content":{"msgtype":"m.text","body":"approved"}}'
  fi
elif [[ "$all" == *'/profile/'* ]]; then
  printf '%s\n' '{"displayname":"External Human"}'
elif [[ "$all" == *'/api/agents/default/skills'* ]]; then
  # Current QwenPaw returns the inventory as a top-level array.
  printf '%s\n' '[{"name":"evidence","enabled":true}]'
elif [[ "$all" == *'find /root/agentteams-fs /root/manager-workspace'* ]]; then
  printf '%s  %s\n' "$(printf '%064d' 2)" '/root/agentteams-fs/agents/explore-worker/skills/evidence/SKILL.md'
elif [[ "$all" == *'find /root/manager-workspace'* ]]; then
  printf '%s\n' '/root/manager-workspace/.openclaw/agents/main/sessions/hero.jsonl'
elif [[ "$all" == *'find "/root/agentteams-fs/agents/$ACTOR_NAME"'* ]]; then
  if [[ "$container" == explore-worker-box ]]; then
    printf '%s\n' '/root/agentteams-fs/agents/explore-worker/sessions/agentteams_matrix/hero.jsonl'
  fi
elif [[ "$all" == *'find "$root/projects"'* ]]; then
  if [[ "$container" == explore-leader-box ]]; then
    printf '%s\n' "/root/agentteams-fs/teams/explore/shared/tasks/task-1/meta.json"
    printf '%s\n' "/root/agentteams-fs/teams/explore/shared/tasks/task-1/result.md"
  fi
elif [[ "$all" == *'cat "$1"'* && "$all" == *'/hero.jsonl'* ]]; then
  if [[ "$container" == explore-worker-box ]]; then
    printf '%s\n' '{"id":"req","timestamp":9999999999050,"type":"message","message":{"role":"user","content":"$task-root task-1 campaign-1 run-1 0123456789abcdef0123456789abcdef"}}'
    printf '%s\n' '{"id":"res","timestamp":9999999999200,"durationMs":123,"type":"message","message":{"role":"assistant","provider":"gateway","model":"worker-model","content":"campaign-1 run-1 0123456789abcdef0123456789abcdef","usage":{"input":10,"output":5}}}'
  else
    printf '%s\n' '{"id":"req","timestamp":"2026-09-03T00:01:00Z","type":"message","message":{"role":"user","content":"campaign-1 run-1 0123456789abcdef0123456789abcdef"}}'
    printf '%s\n' '{"id":"res","timestamp":"2026-09-03T00:01:01Z","durationMs":123,"type":"message","message":{"role":"assistant","provider":"gateway","model":"manager-model","content":"campaign-1 run-1 0123456789abcdef0123456789abcdef","usage":{"input":10,"output":5}}}'
  fi
elif [[ "$all" == *'cat "$1"'* && "$all" == *'/meta.json'* ]]; then
  printf '%s\n' '{"task_id":"task-1","project_id":"project-1","status":"submitted","assigned_to":"@explore-worker:hs","result_status":"SUCCESS","eventId":"$task-event"}'
elif [[ "$container" == pg-box && "$all" == *'select tablename'* ]]; then
  if [[ "${PG_EMPTY_TABLES:-0}" != 1 ]]; then
    printf '%s\n' tw_authority
  fi
elif [[ "$container" == pg-box && "$all" == *'select column_name'* ]]; then
  printf '%s\n' agent_id campaign_id content_hash pg_revision provider_session_record_hash run_id task_id trace_id
elif [[ "$container" == pg-box && "$all" == *'row_to_json'* ]]; then
  printf '%s\n' "$PG_TUPLE_FIXTURE"
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
trace_id=0123456789abcdef0123456789abcdef
export PG_TUPLE_FIXTURE=$(jq -nc --arg trace_id "$trace_id" '{campaign_id:"campaign-1",run_id:"run-1",trace_id:$trace_id,pg_revision:9,content_hash:("sha256:"+("c"*64)),agent_id:"explore-worker",task_id:"task-1",provider_session_record_hash:("sha256:"+("a"*64))}')
allowlist="$tmp/humans.allow"
printf '%s\n' '@human:hs' >"$allowlist"
chmod 600 "$allowlist"
evidence="$tmp/evidence"

args=(--run-id run-1 --campaign-id campaign-1 --trace-id "$trace_id" --evidence-dir "$evidence" \
  --agt-container agt-box --team explore --team verify --human-allowlist "$allowlist" --pg-container pg-box)

bash "$capture" start "${args[@]}"
test -f "$evidence/manifest.json"
test -f "$evidence/SHA256SUMS"
jq -e '.status=="ACTIVE" and .classification=="NOT_ASSESSED" and .live_claimed==false' "$evidence/manifest.json" >/dev/null
jq -e '[.actors[].name] | index("dsh-worker") and index("boundary-oracle") and index("outcome-oracle")' "$evidence/latest/roster.json" >/dev/null
test "$(jq '.teams|length' "$evidence/latest/roster.json")" -eq 2
test -f "$evidence/latest/authority/managers.json.raw.sha256"
jq -e '.status=="OBSERVED_PROVIDER_TURN" and .provider_models[0].provider=="gateway" and .request_hash!="NOT_OBSERVED" and .response_hash!="NOT_OBSERVED"' "$evidence/latest/manager-choice-readback.json" >/dev/null
jq -e 'select(.task_id=="task-1" and .status=="submitted" and .raw_bytes_sha256)' "$evidence/latest/shared-fs/task-metadata.jsonl" >/dev/null
jq -e 'select(.schema_version=="testweaver.pg-exact-readback/v1" and .task_id=="task-1" and .source_hash)' "$evidence/latest/pg-exact-readback.jsonl" >/dev/null
pg_raw_ref=$(jq -r '.source_ref' "$evidence/latest/pg-exact-readback.jsonl")
test -f "$evidence/$pg_raw_ref"
jq -e 'select(.schema_version=="testweaver.skill-invocation-capture/v1" and .task_id=="task-1" and .source_kind=="runtime_matrix_skill_event" and .provider_session_record_hash)' "$evidence/latest/skill-invocations.jsonl" >/dev/null
skill_raw_ref=$(jq -r '.source_ref' "$evidence/latest/skill-invocations.jsonl" | head -1)
test -f "$evidence/$skill_raw_ref"

index=$(find "$evidence/latest/matrix" -name event-index.jsonl -print -quit)
test -n "$index"
jq -e 'select(.identity_binding=="HUMAN_ALLOWLIST_EXACT" and .immutable_source.raw_bytes_sha256)' "$index" >/dev/null
exact_ref=$(jq -r '.immutable_source.ref' "$index" | head -1)
test -f "$evidence/$exact_ref"
test -f "${evidence}/${exact_ref%.json}.raw.sha256"
collision_index="$evidence/latest/matrix/explore-worker/event-index.jsonl"
collision_count=$(jq -s --arg first '$collision+one' --arg second '$collision/one' \
  '[.[] | select(.event_id==$first or .event_id==$second)] | length' "$collision_index")
test "$collision_count" -eq 2
collision_ref_count=$(jq -s --arg first '$collision+one' --arg second '$collision/one' \
  '[.[] | select(.event_id==$first or .event_id==$second) | .immutable_source.ref] | unique | length' "$collision_index")
test "$collision_ref_count" -eq 2
while IFS= read -r collision_ref; do
  test -f "$evidence/$collision_ref"
  collision_sidecar="${collision_ref%.json}.raw.sha256"
  test -f "$evidence/$collision_sidecar"
  test "$(cat "$evidence/$collision_sidecar")" = "$(sha256sum "$evidence/$collision_ref" | awk '{print $1}')"
done < <(jq -r --arg first '$collision+one' --arg second '$collision/one' \
  'select(.event_id==$first or .event_id==$second) | .immutable_source.ref' "$collision_index" | sort -u)
human_event_count=$(jq -s --arg event '$human-event' '[.[] | select(.event_id==$event)] | length' "$collision_index")
test "$human_event_count" -eq 1
whoami=$(find "$evidence/latest/matrix" -name whoami.json -print -quit)
test -n "$whoami"
test -f "${whoami%.json}.raw.sha256"

chmod 644 "$evidence/.state/config"
if bash "$capture" snapshot "${args[@]}" >/dev/null 2>&1; then
  printf 'unsafe capture config mode unexpectedly succeeded\n' >&2
  exit 1
fi
chmod 600 "$evidence/.state/config"
bash "$capture" snapshot "${args[@]}"
test "$(find "$evidence/snapshots" -mindepth 1 -maxdepth 1 -type d | wc -l)" -ge 2
sleep 1
bash "$capture" stop "${args[@]}"
jq -e '.status=="STOPPED" and .checksum_state=="FINAL"' "$evidence/manifest.json" >/dev/null
(cd "$evidence" && sha256sum -c SHA256SUMS >/dev/null)
while IFS=$'\t' read -r pid _; do
  if kill -0 "$pid" 2>/dev/null; then
    printf 'owned log follower %s survived stop\n' "$pid" >&2
    exit 1
  fi
done <"$evidence/.state/collectors.tsv"

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

empty_evidence="$tmp/empty-pg-evidence"
empty_args=(--run-id run-empty --campaign-id campaign-empty --trace-id "$trace_id" \
  --evidence-dir "$empty_evidence" --agt-container agt-box --team explore --team verify \
  --human-allowlist "$allowlist" --pg-container pg-box)
PG_EMPTY_TABLES=1 bash "$capture" start "${empty_args[@]}"
jq -e '.status=="NOT_OBSERVED"' "$empty_evidence/latest/pg-tw-row-hashes.jsonl" >/dev/null
test ! -s "$empty_evidence/latest/pg-exact-readback.jsonl"
rg -q $'^pg.tw_rows\tNOT_OBSERVED$' "$empty_evidence/latest/not-observed.tsv"
rg -q $'^pg.exact_tuple\tNOT_OBSERVED$' "$empty_evidence/latest/not-observed.tsv"
PG_EMPTY_TABLES=1 bash "$capture" stop "${empty_args[@]}"

printf 'native hero capture tests: PASS\n'
