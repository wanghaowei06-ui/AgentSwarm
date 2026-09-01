#!/usr/bin/env bash
set -euo pipefail

umask 077

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../../../../.." && pwd)"
evidence_dir="$script_dir"
state_dir="$evidence_dir/.state"
logs_root="$evidence_dir/logs"
manifest_path="$evidence_dir/baseline-manifest.json"
redactor="$script_dir/redact-docker-log.pl"

mkdir -p "$state_dir" "$logs_root"

for command_name in docker jq perl curl sha256sum python3 git; do
    command -v "$command_name" >/dev/null 2>&1
done

started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
head="$(git -C "$repo_root" rev-parse HEAD)"
human_input_hash="$(sha256sum "$evidence_dir/human-input.txt" | awk '{print $1}')"
controller_container='agentteams-native-m0-20260901-controller'
run_id="$(basename "$evidence_dir")"
logs_dir="$logs_root/arm-$run_id"
mkdir -p "$logs_dir"

skill_names=(
    approval-intent-boundary-check
    avoid-redundant-exploration
    diagnose-by-competing-hypotheses
    preserve-critical-constraints
    reconcile-before-retry
)

expected_names_json='["approval-intent-boundary-check","avoid-redundant-exploration","diagnose-by-competing-hypotheses","preserve-critical-constraints","reconcile-before-retry"]'

log_specs=(
    'manager|agentteams-native-m0-20260901-manager'
    'controller|agentteams-native-m0-20260901-controller'
    'worker-native-m0-clean-leader|agentteams-native-m0-20260901-worker-native-m0-clean-leader'
    'worker-native-m0-clean-worker|agentteams-native-m0-20260901-worker-native-m0-clean-worker'
    'worker-native-m1-verify-leader|agentteams-native-m0-20260901-worker-native-m1-verify-leader'
    'worker-native-m1-verify-worker|agentteams-native-m0-20260901-worker-native-m1-verify-worker'
)

worker_specs=()
for worker in native-m0-clean-leader native-m0-clean-worker native-m1-verify-leader native-m1-verify-worker; do
    container="agentteams-native-m0-20260901-worker-$worker"
    ports="$(docker ps --filter "name=$container" --format '{{.Ports}}')"
    port="$(printf '%s' "$ports" | sed -n 's/.*0.0.0.0:\([0-9][0-9]*\)->8088.*/\1/p' | head -1)"
    test -n "$port"
    worker_specs+=("$worker|$container|$port")
done

for skill in "${skill_names[@]}"; do
    test -r "$repo_root/testweaver/skills/native-agentspec-package/skills/$skill/SKILL.md"
done
test -r "$redactor"
test -r "$evidence_dir/human-input.txt"

collectors_tsv="$state_dir/collectors.tsv"
: > "$collectors_tsv"

# Start one append-only, timestamp-preserving stream per in-scope container.
# The pipeline performs redaction before the line reaches the evidence file.
for spec in "${log_specs[@]}"; do
    IFS='|' read -r label container <<< "$spec"
    log_file="$logs_dir/$label.docker.log"
    nohup setsid sh -c 'docker logs --follow --timestamps --since "$1" "$2" 2>&1 | perl "$3" >> "$4"' \
        _ "$started_at" "$container" "$redactor" "$log_file" \
        >/dev/null 2>&1 &
    collector_pid=$!
    collector_alive=false
    if kill -0 "$collector_pid" 2>/dev/null; then
        collector_alive=true
    fi
    printf '%s\t%s\t%s\t%s\t%s\n' \
        "$label" "$container" "$log_file" "$collector_pid" "$collector_alive" \
        >> "$collectors_tsv"
done

# Read only selected, non-secret fields from the official resource API.  The
# unfiltered responses never reach a terminal or an evidence file.
docker exec "$controller_container" sh -c 'agt get managers -o json' 2>/dev/null \
    | jq '[.managers[]? | {name, phase, runtime, image, version, matrixUserID: (.matrixUserID // .matrix_user_id // null)}]' \
    > "$state_dir/managers.json"

docker exec "$controller_container" sh -c 'agt get teams -o json' 2>/dev/null \
    | jq '[.teams[]? | select(.name == "native-m0-clean-team" or .name == "native-m1-verify-team") | {name, teamName: (.teamName // .name), leader: (.leaderName // .leader // null), workerNames: (.workerNames // []), workerMembers: (.workerMembers // []), phase, leaderReady, readyWorkers, totalWorkers}]' \
    > "$state_dir/teams.json"

docker exec "$controller_container" sh -c 'agt get workers -o json' 2>/dev/null \
    | jq '[.workers[]? | select(.name == "native-m0-clean-leader" or .name == "native-m0-clean-worker" or .name == "native-m1-verify-leader" or .name == "native-m1-verify-worker") | {name, workerName, team: (.team // .teamName // null), role, runtime, image, phase, containerState}]' \
    > "$state_dir/workers.json"

for spec in "${log_specs[@]}"; do
    IFS='|' read -r label container <<< "$spec"
    docker inspect "$container" 2>/dev/null \
        | jq '.[0] | {container_name: (.Name | sub("^/"; "")), container_id: .Id, image: .Config.Image, image_id: .Image, status: .State.Status, running: .State.Running, restart_count: .RestartCount, started_at: .State.StartedAt}' \
        > "$state_dir/container-$label.json"
done

skills_tsv="$state_dir/skills.tsv"
api_states_tsv="$state_dir/api-states.tsv"
: > "$skills_tsv"
: > "$api_states_tsv"

for spec in "${worker_specs[@]}"; do
    IFS='|' read -r worker container port <<< "$spec"
    api_file="$state_dir/api-$worker.json"
    if curl -fsS --max-time 5 "http://127.0.0.1:$port/api/agents/default/skills" 2>/dev/null \
        | jq --argjson wanted "$expected_names_json" '
            (if type == "array" then . else (.skills // []) end)
            | map(select((.name // "") as $n | ($wanted | index($n)) != null)
                  | {name: .name, enabled: (.enabled // null)})
            | sort_by(.name)
        ' > "$api_file"; then
        api_state='reachable'
    else
        printf '[]\n' > "$api_file"
        api_state='unavailable'
    fi
    printf '%s\t%s\t%s\n' "$worker" "$port" "$api_state" >> "$api_states_tsv"

    for skill in "${skill_names[@]}"; do
        source_path="$repo_root/testweaver/skills/native-agentspec-package/skills/$skill/SKILL.md"
        source_sha="$(sha256sum "$source_path" | awk '{print $1}')"
        source_commit="$(git -C "$repo_root" log -1 --format=%H -- "testweaver/skills/native-agentspec-package/skills/$skill/SKILL.md")"
        runtime_path="/root/agentteams-fs/agents/$worker/.qwenpaw/workspaces/default/skills/$skill/SKILL.md"
        runtime_sha="$(docker exec "$container" sh -c "sha256sum '$runtime_path' 2>/dev/null | cut -d' ' -f1" 2>/dev/null || true)"
        enabled="$(jq -r --arg skill "$skill" '(map(select(.name == $skill)) | .[0].enabled) // null' "$api_file" 2>/dev/null || true)"
        [ -n "$enabled" ] || enabled='null'
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
            "$worker" "$skill" "$port" "$source_commit" "$source_sha" "${runtime_sha:-}" "$enabled" \
            >> "$skills_tsv"
    done
done

python3 - "$manifest_path" "$repo_root" "$started_at" "$head" "$human_input_hash" "$state_dir" <<'PY'
import json
import os
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
repo_root = Path(sys.argv[2])
started_at = sys.argv[3]
head = sys.argv[4]
human_input_hash = sys.argv[5]
state_dir = Path(sys.argv[6])

def load_json(name, default):
    path = state_dir / name
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default

def evidence_path(path_text):
    resolved = Path(path_text).resolve()
    run_root = manifest_path.parent.resolve()
    try:
        resolved.relative_to(run_root)
    except ValueError:
        return "[OUT_OF_SCOPE]"
    return str(resolved)

container_labels = [
    "manager",
    "controller",
    "worker-native-m0-clean-leader",
    "worker-native-m0-clean-worker",
    "worker-native-m1-verify-leader",
    "worker-native-m1-verify-worker",
]
containers = {
    label: load_json(f"container-{label}.json", {})
    for label in container_labels
}

manager_resources = load_json("managers.json", [])
team_resources = load_json("teams.json", [])
worker_resources = load_json("workers.json", [])
manager_resource = next((item for item in manager_resources if item.get("name") == "default"), None)
worker_by_name = {item.get("name"): item for item in worker_resources if item.get("name")}

worker_labels = {
    "native-m0-clean-leader": "worker-native-m0-clean-leader",
    "native-m0-clean-worker": "worker-native-m0-clean-worker",
    "native-m1-verify-leader": "worker-native-m1-verify-leader",
    "native-m1-verify-worker": "worker-native-m1-verify-worker",
}

worker_records = []
for name, label in worker_labels.items():
    resource = worker_by_name.get(name)
    container = containers[label]
    worker_records.append({
        "identity": {
            "resource_name": name,
            "container_name": container.get("container_name"),
            "role": resource.get("role") if resource else None,
            "team": resource.get("team") if resource else None,
        },
        "runtime": resource.get("runtime") if resource else None,
        "image": {
            "resource": resource.get("image") if resource else None,
            "container": container.get("image"),
            "image_id": container.get("image_id"),
        },
        "resource": resource,
        "container": container,
    })

team_by_name = {item.get("name"): item for item in team_resources if item.get("name")}
team_records = []
for name in ["native-m0-clean-team", "native-m1-verify-team"]:
    resource = team_by_name.get(name)
    leader = resource.get("leader") if resource else None
    member_names = list(resource.get("workerNames") or []) if resource else []
    if leader and leader not in member_names:
        member_names.insert(0, leader)
    member_images = {}
    for member in member_names:
        member_record = next((item for item in worker_records if item["identity"]["resource_name"] == member), None)
        if member_record:
            member_images[member] = member_record["image"]
    team_records.append({
        "identity": {"resource_name": name},
        "image": None,
        "image_note": "Team resource has no image field; member image references are recorded below.",
        "member_images": member_images,
        "resource": resource,
    })

skills = []
with (state_dir / "skills.tsv").open(encoding="utf-8") as handle:
    for line in handle:
        fields = line.rstrip("\n").split("\t")
        if len(fields) != 7:
            continue
        worker, skill, port, source_commit, source_sha, runtime_sha, enabled = fields
        if enabled == "null":
            enabled_value = None
        else:
            enabled_value = enabled.lower() == "true"
        skills.append({
            "worker": worker,
            "skill": skill,
            "api_port": int(port),
            "source_commit": source_commit,
            "source_sha256": source_sha,
            "runtime_sha256": runtime_sha or None,
            "enabled": enabled_value,
        })

api_states = []
with (state_dir / "api-states.tsv").open(encoding="utf-8") as handle:
    for line in handle:
        worker, port, state = line.rstrip("\n").split("\t")
        api_states.append({"worker": worker, "api_port": int(port), "state": state})

log_sources = []
with (state_dir / "collectors.tsv").open(encoding="utf-8") as handle:
    for line in handle:
        label, container, log_path, pid, alive = line.rstrip("\n").split("\t")
        log_sources.append({
            "label": label,
            "container": container,
            "log": evidence_path(log_path),
            "pid": int(pid),
            "alive_at_manifest": alive == "true",
        })

manager_container = containers["manager"]
controller_container = containers["controller"]
try:
    with manifest_path.open(encoding="utf-8") as handle:
        existing_manifest = json.load(handle)
except (OSError, ValueError):
    existing_manifest = {}
existing_human_input = existing_manifest.get("frozen_human_input")
if not isinstance(existing_human_input, dict) or not existing_human_input.get("room_id") or not existing_human_input.get("event_id"):
    existing_human_input = {
        "hash": human_input_hash,
        "room_id": None,
        "event_id": None,
        "policy": "Room and event identifiers were not supplied; no Human query was performed. Later use is filter/readback only.",
    }
manifest = {
    "schema": "testweaver.m2d.evidence-boundary/v1",
    "status": "EVIDENCE_ARMED",
    "started_at": started_at,
    "head": head,
    "frozen_human_input": existing_human_input,
    "scope": {
        "containers": container_labels,
        "manager": "default",
        "teams": ["native-m0-clean-team", "native-m1-verify-team"],
        "workers": list(worker_labels),
        "skills": [
            "approval-intent-boundary-check",
            "avoid-redundant-exploration",
            "diagnose-by-competing-hypotheses",
            "preserve-critical-constraints",
            "reconcile-before-retry",
        ],
        "exclude_other_containers": True,
    },
    "manager": {
        "identity": {"resource_name": "default", "container_name": manager_container.get("container_name")},
        "image": {
            "resource": manager_resource.get("image") if manager_resource else None,
            "container": manager_container.get("image"),
            "image_id": manager_container.get("image_id"),
        },
        "resource": manager_resource,
        "container": manager_container,
    },
    "controller": {
        "identity": {"container_name": controller_container.get("container_name")},
        "image": {"container": controller_container.get("image"), "image_id": controller_container.get("image_id")},
        "container": controller_container,
    },
    "teams": team_records,
    "workers": worker_records,
    "skills": skills,
    "skill_api_observation": api_states,
    "docker_log_collection": {
        "mode": "incremental_from_boundary",
        "since": started_at,
        "timestamps": True,
        "stdout_stderr_combined": True,
        "sources": log_sources,
        "redaction": {
            "values": "credential-like values are replaced with [REDACTED] before persistence",
            "variable_names": "retained where present",
            "input_lines": "streamed line-by-line; no event parsing or rewriting",
        },
        "raw_event_parsing": False,
        "event_injection": False,
    },
    "forbidden_actions_for_this_boundary": [
        "send Matrix messages",
        "create Project or Task",
        "invoke a model",
        "restart, replace, or modify runtime resources",
        "parse logs and inject derived events",
    ],
    "notes": [
        "This is a baseline collection boundary only; no run outcome is recorded.",
        "Evidence files remain uncommitted until the Run is frozen.",
    ],
}

if isinstance(existing_manifest.get("matrix_readback"), dict):
    manifest["matrix_readback"] = existing_manifest["matrix_readback"]

manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.chmod(manifest_path, 0o600)
PY

printf 'EVIDENCE_ARMED\n'
printf 'manifest=%s\n' "$manifest_path"
printf 'collector_count=%s\n' "${#log_specs[@]}"
