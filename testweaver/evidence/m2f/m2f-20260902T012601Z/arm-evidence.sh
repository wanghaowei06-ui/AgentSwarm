#!/usr/bin/env bash
set -euo pipefail

umask 077
script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
repo_root="$(cd -- "$script_dir/../../../.." && pwd)"
evidence_dir="$script_dir"
state_dir="$evidence_dir/.state"
logs_root="$evidence_dir/logs"
manifest_path="$evidence_dir/baseline-manifest.json"
redactor="$evidence_dir/redact-docker-log.pl"

mkdir -p "$state_dir" "$logs_root"
for command_name in docker jq perl curl sha256sum python3 git; do
    command -v "$command_name" >/dev/null 2>&1
done

run_id="$(basename "$evidence_dir")"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
head="$(git -C "$repo_root" rev-parse HEAD)"
human_input_hash="$(sha256sum "$evidence_dir/human-input.txt" | awk '{print $1}')"
controller_container='agentteams-native-m0-20260901-controller'

skills='approval-intent-boundary-check avoid-redundant-exploration diagnose-by-competing-hypotheses preserve-critical-constraints reconcile-before-retry'
expected_names_json='["approval-intent-boundary-check","avoid-redundant-exploration","diagnose-by-competing-hypotheses","preserve-critical-constraints","reconcile-before-retry"]'
log_specs='manager|agentteams-native-m0-20260901-manager controller|agentteams-native-m0-20260901-controller worker-native-m0-clean-leader|agentteams-native-m0-20260901-worker-native-m0-clean-leader worker-native-m0-clean-worker|agentteams-native-m0-20260901-worker-native-m0-clean-worker worker-native-m1-verify-leader|agentteams-native-m0-20260901-worker-native-m1-verify-leader worker-native-m1-verify-worker|agentteams-native-m0-20260901-worker-native-m1-verify-worker'
workers='native-m0-clean-leader native-m0-clean-worker native-m1-verify-leader native-m1-verify-worker'

for worker in $workers; do
    container="agentteams-native-m0-20260901-worker-$worker"
    port="$(docker port "$container" 8088/tcp 2>/dev/null | sed -n 's/.*:\([0-9][0-9]*\)$/\1/p' | head -1)"
    test -n "$port"
done
for skill in $skills; do
    test -r "$repo_root/testweaver/skills/native-agentspec-package/skills/$skill/SKILL.md"
done
test -r "$redactor"
test -r "$evidence_dir/human-input.txt"
test -r "$evidence_dir/human-event.json"

logs_dir="$logs_root/arm-$run_id"
mkdir -p "$logs_dir"
collectors_tsv="$state_dir/collectors.tsv"
: > "$collectors_tsv"

for spec in $log_specs; do
    IFS='|' read -r label container <<< "$spec"
    log_file="$logs_dir/$label.docker.log"
    nohup setsid sh -c 'docker logs --follow --timestamps --since "$1" "$2" 2>&1 | perl "$3" >> "$4"' _ "$started_at" "$container" "$redactor" "$log_file" >/dev/null 2>&1 &
    collector_pid=$!
    alive=false
    if kill -0 "$collector_pid" 2>/dev/null; then
        alive=true
    fi
    printf '%s\t%s\t%s\t%s\t%s\n' "$label" "$container" "$log_file" "$collector_pid" "$alive" >> "$collectors_tsv"
done

read_resource() {
    local kind="$1"
    local filter="$2"
    local out="$3"
    if docker exec "$controller_container" sh -c "agt get $kind -o json" 2>/dev/null | jq "$filter" > "$out"; then
        chmod 600 "$out"
    else
        printf '[]\n' > "$out"
        chmod 600 "$out"
    fi
}
read_resource managers '[.managers[]? | {name,phase,runtime,image,version,matrixUserID:(.matrixUserID // .matrix_user_id // null)}]' "$state_dir/managers.json"
read_resource teams '[.teams[]? | {name,teamName:(.teamName // .name),leader:(.leaderName // .leader // null),workerNames:(.workerNames // []),phase,leaderReady,readyWorkers,totalWorkers}]' "$state_dir/teams.json"
read_resource workers '[.workers[]? | {name,workerName,team:(.team // .teamName // null),role,runtime,image,phase,containerState}]' "$state_dir/workers.json"

for spec in $log_specs; do
    IFS='|' read -r label container <<< "$spec"
    if docker inspect "$container" 2>/dev/null | jq '.[0] | {container_name:(.Name|sub("^/";"")),container_id:.Id,image:.Config.Image,image_id:.Image,status:.State.Status,running:.State.Running,restart_count:.RestartCount,started_at:.State.StartedAt}' > "$state_dir/container-$label.json"; then
        chmod 600 "$state_dir/container-$label.json"
    else
        printf '{}\n' > "$state_dir/container-$label.json"
    fi
done

skills_tsv="$state_dir/skills.tsv"
api_states_tsv="$state_dir/api-states.tsv"
: > "$skills_tsv"
: > "$api_states_tsv"
for worker in $workers; do
    container="agentteams-native-m0-20260901-worker-$worker"
    port="$(docker port "$container" 8088/tcp 2>/dev/null | sed -n 's/.*:\([0-9][0-9]*\)$/\1/p' | head -1)"
    api_file="$state_dir/api-$worker.json"
    if curl -fsS --max-time 5 "http://127.0.0.1:$port/api/agents/default/skills" 2>/dev/null | jq --argjson wanted "$expected_names_json" '
        (if type == "array" then . else (.skills // []) end)
        | map(select((.name // "") as $n | ($wanted | index($n)) != null) | {name:.name,enabled:(.enabled // null)})
        | sort_by(.name)
    ' > "$api_file"; then
        api_state='reachable'
    else
        printf '[]\n' > "$api_file"
        api_state='unavailable'
    fi
    chmod 600 "$api_file"
    printf '%s\t%s\t%s\n' "$worker" "$port" "$api_state" >> "$api_states_tsv"
    for skill in $skills; do
        source_path="$repo_root/testweaver/skills/native-agentspec-package/skills/$skill/SKILL.md"
        source_sha="$(sha256sum "$source_path" | awk '{print $1}')"
        source_commit="$(git -C "$repo_root" log -1 --format=%H -- "testweaver/skills/native-agentspec-package/skills/$skill/SKILL.md")"
        runtime_path="/root/agentteams-fs/agents/$worker/.qwenpaw/workspaces/default/skills/$skill/SKILL.md"
        runtime_sha="$(docker exec "$container" sh -c "sha256sum '$runtime_path' 2>/dev/null | cut -d' ' -f1" 2>/dev/null || true)"
        enabled="$(jq -r --arg skill "$skill" '(map(select(.name == $skill)) | .[0].enabled) // null' "$api_file" 2>/dev/null || true)"
        test -n "$enabled" || enabled='null'
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$worker" "$skill" "$port" "$source_commit" "$source_sha" "$runtime_sha" "$enabled" >> "$skills_tsv"
    done
done

python3 - "$manifest_path" "$state_dir" "$evidence_dir" "$started_at" "$head" "$human_input_hash" <<'PY'
import json
import os
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
state_dir = Path(sys.argv[2])
evidence_dir = Path(sys.argv[3])
started_at = sys.argv[4]
head = sys.argv[5]
human_input_hash = sys.argv[6]

def read_json(name, default):
    try:
        return json.loads((state_dir / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default

def scoped(path):
    try:
        return str(path.resolve().relative_to(evidence_dir.resolve()))
    except ValueError:
        return "[OUT_OF_SCOPE]"

containers = {}
for label in ("manager", "controller", "worker-native-m0-clean-leader",
              "worker-native-m0-clean-worker", "worker-native-m1-verify-leader",
              "worker-native-m1-verify-worker"):
    containers[label] = read_json(f"container-{label}.json", {})

skills = []
try:
    lines = (state_dir / "skills.tsv").read_text(encoding="utf-8").splitlines()
except OSError:
    lines = []
for line in lines:
    fields = line.split("\t")
    if len(fields) != 7:
        continue
    worker, skill, port, source_commit, source_sha, runtime_sha, enabled = fields
    skills.append({
        "worker": worker,
        "skill": skill,
        "api_port": int(port),
        "source_commit": source_commit,
        "source_sha256": source_sha,
        "runtime_sha256": runtime_sha or None,
        "enabled": None if enabled == "null" else enabled == "true",
    })

api_states = []
try:
    api_lines = (state_dir / "api-states.tsv").read_text(encoding="utf-8").splitlines()
except OSError:
    api_lines = []
for line in api_lines:
    worker, port, state = line.split("\t")
    api_states.append({"worker": worker, "api_port": int(port), "state": state})

human = read_json("../human-event.json", {})
logs_dir = evidence_dir / "logs" / f"arm-{evidence_dir.name}"
manifest = {
    "schema": "testweaver.m2f.evidence-boundary/v1",
    "status": "EVIDENCE_ARMED",
    "run_id": evidence_dir.name,
    "started_at": started_at,
    "capture_started_after_human_event": True,
    "head": head,
    "frozen_human_input": {
        "sha256": human_input_hash,
        "room_id": human.get("room_id"),
        "event_id": human.get("event_id"),
        "sender": human.get("sender"),
        "origin_server_ts": human.get("origin_server_ts"),
    },
    "scope": {
        "manager_container": "agentteams-native-m0-20260901-manager",
        "controller_container": "agentteams-native-m0-20260901-controller",
        "candidate_team_workers": [
            "native-m0-clean-leader",
            "native-m0-clean-worker",
            "native-m1-verify-leader",
            "native-m1-verify-worker",
        ],
        "skills": [
            "approval-intent-boundary-check",
            "avoid-redundant-exploration",
            "diagnose-by-competing-hypotheses",
            "preserve-critical-constraints",
            "reconcile-before-retry",
        ],
        "exclude_other_containers": True,
    },
    "containers": containers,
    "resources": {
        "manager": read_json("managers.json", []),
        "teams": read_json("teams.json", []),
        "workers": read_json("workers.json", []),
    },
    "skills": skills,
    "skill_api_observation": api_states,
    "evidence": {
        "docker_log_boundary": scoped(logs_dir),
        "collectors": scoped(state_dir / "collectors.tsv"),
        "human_input": scoped(evidence_dir / "human-input.txt"),
        "human_event": scoped(evidence_dir / "human-event.json"),
    },
    "secrets": {
        "values_read_or_persisted": False,
        "protected_configuration": "only variable names and file references may be recorded",
    },
    "forbidden_actions": [
        "model invocation",
        "Matrix send after this initial event",
        "script-created Project or Task",
        "runtime restart/replace/modify",
        "derived-event injection",
        "synthetic or fixture substitution",
    ],
    "notes": [
        "This is an armed boundary, not an outcome.",
        "The initial Human event was captured separately before Docker log streaming began.",
        "Matrix readback is read-only and must remain the source for the pre-capture initial event.",
    ],
}
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.chmod(manifest_path, 0o600)
PY

printf 'EVIDENCE_ARMED\n'
printf 'run_id=%s\n' "$run_id"
printf 'started_at=%s\n' "$started_at"
printf 'manifest=%s\n' "$manifest_path"
printf 'collector_count=6\n'
