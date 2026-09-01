#!/usr/bin/env bash
set -euo pipefail

umask 077

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
evidence_dir="$script_dir"
state_dir="$evidence_dir/.state"
redactor="$evidence_dir/redact-docker-log.pl"
manager_container='agentteams-native-m0-20260901-manager'

human_event_path="$evidence_dir/human-event.json"
events_path="$evidence_dir/matrix-events.jsonl"
event_index_path="$evidence_dir/matrix-event-index.jsonl"
stage_path="$evidence_dir/matrix-stage-observations.jsonl"
status_path="$evidence_dir/matrix-collector-status.json"
seen_path="$state_dir/matrix-seen-event-ids"
rooms_path="$state_dir/rooms.tsv"
lock_path="$state_dir/matrix-collector.lock"

mkdir -p "$state_dir"
touch "$events_path" "$event_index_path" "$stage_path" "$seen_path" "$rooms_path"

for command_name in docker jq perl sha256sum date wc awk tr grep; do
    command -v "$command_name" >/dev/null 2>&1
done
test -r "$human_event_path"
test -r "$redactor"

run_id="$(basename "$evidence_dir")"
human_room_id="$(jq -r '.room_id // empty' "$human_event_path")"
human_event_id="$(jq -r '.event_id // empty' "$human_event_path")"
human_sender="$(jq -r '.sender // empty' "$human_event_path")"
human_origin_ts="$(jq -r '.origin_server_ts // empty' "$human_event_path")"
human_body_sha="$(jq -j '.content.body // empty' "$human_event_path" | sha256sum | awk '{print $1}')"

test -n "$human_room_id"
test -n "$human_event_id"
test -n "$human_sender"
case "$human_origin_ts" in
    ''|*[!0-9]*) exit 64 ;;
esac

human_event_file_sha="$(sha256sum "$human_event_path" | awk '{print $1}')"
jq -n \
    --arg run_id "$run_id" \
    --arg room_id "$human_room_id" \
    --arg event_id "$human_event_id" \
    --arg sender "$human_sender" \
    --arg origin_server_ts "$human_origin_ts" \
    --arg body_sha256 "$human_body_sha" \
    --arg event_file_sha256 "$human_event_file_sha" \
    --arg path "$human_event_path" \
    '{schema: "testweaver.m2d.human-event-hash/v1", run_id: $run_id, room_id: $room_id, event_id: $event_id, sender: $sender, origin_server_ts: ($origin_server_ts|tonumber), body_sha256: $body_sha256, event_file_sha256: $event_file_sha256, event_path: $path, values_redacted: true}' \
    > "$evidence_dir/human-event-hash.json"
chmod 600 "$evidence_dir/human-event-hash.json"

boundary_ms="$human_origin_ts"

actor_specs=(
    'manager|agentteams-native-m0-20260901-manager|AGENTTEAMS_MANAGER_MATRIX_TOKEN'
    'native-m0-clean-leader|agentteams-native-m0-20260901-worker-native-m0-clean-leader|AGENTTEAMS_WORKER_MATRIX_TOKEN'
    'native-m0-clean-worker|agentteams-native-m0-20260901-worker-native-m0-clean-worker|AGENTTEAMS_WORKER_MATRIX_TOKEN'
    'native-m1-verify-leader|agentteams-native-m0-20260901-worker-native-m1-verify-leader|AGENTTEAMS_WORKER_MATRIX_TOKEN'
    'native-m1-verify-worker|agentteams-native-m0-20260901-worker-native-m1-verify-worker|AGENTTEAMS_WORKER_MATRIX_TOKEN'
)

matrix_get_actor() {
    local container="$1"
    local token_var="$2"
    local request_path="$3"
    local output_path="$4"
    local temporary_path="${output_path}.tmp.$$"

    if docker exec "$container" sh -c '
        token_var="$1"
        request_path="$2"
        matrix_url="${AGENTTEAMS_MATRIX_URL%/}"
        case "$token_var" in
            AGENTTEAMS_MANAGER_MATRIX_TOKEN) token="${AGENTTEAMS_MANAGER_MATRIX_TOKEN:-}" ;;
            AGENTTEAMS_WORKER_MATRIX_TOKEN) token="${AGENTTEAMS_WORKER_MATRIX_TOKEN:-}" ;;
            *) exit 66 ;;
        esac
        [ -n "$matrix_url" ] || exit 64
        [ -n "$token" ] || exit 65
        curl -fsS --max-time 10 \
            -H "Authorization: Bearer ${token}" \
            "${matrix_url}${request_path}"
    ' _ "$token_var" "$request_path" 2>/dev/null | perl "$redactor" > "$temporary_path"; then
        mv -f "$temporary_path" "$output_path"
        chmod 600 "$output_path"
        return 0
    fi
    rm -f "$temporary_path"
    return 1
}

record_event_lines() {
    local payload_path="$1"
    local actor="$2"
    local source="$3"
    local collected_at="$4"
    local event
    local observed_event_id
    local observed_room_id
    local observed_sender
    local observed_origin_ts
    local observed_type
    local event_sha

    [ -s "$payload_path" ] || return 0
    while IFS= read -r event; do
        [ -n "$event" ] || continue
        observed_event_id="$(printf '%s' "$event" | jq -r '.event_id // empty' 2>/dev/null || true)"
        [ -n "$observed_event_id" ] || continue
        if grep -Fqx -- "$observed_event_id" "$seen_path" 2>/dev/null; then
            continue
        fi
        observed_room_id="$(printf '%s' "$event" | jq -r '.room_id // empty' 2>/dev/null || true)"
        observed_sender="$(printf '%s' "$event" | jq -r '.sender // empty' 2>/dev/null || true)"
        observed_origin_ts="$(printf '%s' "$event" | jq -r '.origin_server_ts // empty' 2>/dev/null || true)"
        observed_type="$(printf '%s' "$event" | jq -r '.type // empty' 2>/dev/null || true)"
        event_sha="$(printf '%s' "$event" | sha256sum | awk '{print $1}')"

        printf '%s\n' "$event" | perl "$redactor" >> "$events_path"
        printf '%s\n' "$observed_event_id" >> "$seen_path"
        jq -cn \
            --arg collected_at "$collected_at" \
            --arg actor "$actor" \
            --arg source "$source" \
            --arg raw_event_path "$events_path" \
            --arg event_id "$observed_event_id" \
            --arg room_id "$observed_room_id" \
            --arg sender "$observed_sender" \
            --arg origin_server_ts "$observed_origin_ts" \
            --arg type "$observed_type" \
            --arg event_sha256 "$event_sha" \
            '{collected_at: $collected_at, actor: $actor, source: $source, raw_event_path: $raw_event_path, event_id: $event_id, room_id: $room_id, sender: $sender, origin_server_ts: ($origin_server_ts|tonumber), type: $type, captured_event_sha256: $event_sha256}' \
            >> "$event_index_path"
    done < <(jq -c --argjson boundary "$boundary_ms" '.chunk[]? | select((.origin_server_ts // 0) >= $boundary)' "$payload_path" 2>/dev/null || true)
}

collect_actor() {
    local actor="$1"
    local container="$2"
    local token_var="$3"
    local actor_key
    local joined_path
    local room_id
    local room_path
    local message_path
    local room_number=0
    local collected_at

    actor_key="$(printf '%s' "$actor" | tr -c 'A-Za-z0-9._-' '_')"
    joined_path="$state_dir/joined-$actor_key.json"
    collected_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    if ! matrix_get_actor "$container" "$token_var" '/_matrix/client/v3/joined_rooms' "$joined_path"; then
        printf '%s\t%s\t%s\tunavailable\n' "$actor" "$container" "$collected_at" >> "$rooms_path"
        return 0
    fi

    while IFS= read -r room_id; do
        [ -n "$room_id" ] || continue
        room_number=$((room_number + 1))
        room_path="$(printf '%s' "$room_id" | jq -sRr @uri)"
        message_path="$state_dir/messages-$actor_key-$room_number.json"
        if matrix_get_actor "$container" "$token_var" "/_matrix/client/v3/rooms/${room_path}/messages?dir=b&limit=100" "$message_path"; then
            printf '%s\t%s\t%s\t%s\n' "$actor" "$container" "$room_id" "$message_path" >> "$rooms_path"
            record_event_lines "$message_path" "$actor" "${actor}.room_messages" "$collected_at"
        else
            printf '%s\t%s\t%s\tread_failed\n' "$actor" "$container" "$room_id" >> "$rooms_path"
        fi
    done < <(jq -r '.joined_rooms[]?' "$joined_path" 2>/dev/null || true)
}

write_stage_observation() {
    local collected_at="$1"
    jq -s -c \
        --arg collected_at "$collected_at" \
        --arg run_id "$run_id" \
        --arg human_event_id "$human_event_id" \
        --arg human_room_id "$human_room_id" \
        --arg human_sender "$human_sender" \
        --argjson human_origin_ts "$human_origin_ts" \
        --argjson boundary "$boundary_ms" '
        def body: (.content.body // "") | tostring;
        def post: map(select((.event_id != $human_event_id) and ((.origin_server_ts // 0) >= $boundary)));
        (post) as $post
        | ([$post[] | select(.type == "m.room.message" and ((.sender // "") | test("manager"; "i")))] ) as $manager_events
        | ([$post[] | select(.type == "m.room.message" and ((.sender // "") | test("leader"; "i")))] ) as $leader_events
        | ([$post[] | select(.type == "m.room.message" and ((.sender // "") | test("worker"; "i")))] ) as $worker_events
        | ([$post[] | select((body | test("pause_project"; "i")) and (body | test("approval|approve|批准|审批"; "i")))]) as $pause_candidates
        | ([$post[] | select((body | test("notificationNeeded|targetRoom|assignment"; "i")))]) as $assignment_candidates
        | {
            schema: "testweaver.m2d.matrix-stage-observation/v1",
            run_id: $run_id,
            collected_at: $collected_at,
            basis: "raw Matrix events collected read-only from Manager and Worker tokens; candidates are diagnostic and not proof",
            human_boundary: {room_id: $human_room_id, event_id: $human_event_id, sender: $human_sender, origin_server_ts: $human_origin_ts},
            post_boundary_event_count: ($post | length),
            actors: {manager_message_event_ids: ($manager_events | map(.event_id)), leader_message_event_ids: ($leader_events | map(.event_id)), worker_message_event_ids: ($worker_events | map(.event_id))},
            diagnostic_candidates: {assignment_event_ids: ($assignment_candidates | map(.event_id)), pause_approval_event_ids: ($pause_candidates | map(.event_id))},
            interpretation: "Do not treat candidate lists as native action or approval proof; verify exact raw event and TeamHarness tool result before stopping."
          }
    ' "$events_path" >> "$stage_path"
}

collect_once() {
    local collected_at
    local event_count
    local room_count
    : > "$rooms_path"
    for spec in "${actor_specs[@]}"; do
        IFS='|' read -r actor container token_var <<< "$spec"
        collect_actor "$actor" "$container" "$token_var"
    done
    collected_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    write_stage_observation "$collected_at"
    event_count="$(wc -l < "$events_path" | tr -d ' ')"
    room_count="$(awk -F '\t' 'NF >= 3 {key=$1 FS $3; if (!(key in seen)) {seen[key]=1; count++}} END {print count+0}' "$rooms_path")"
    jq -n \
        --arg schema 'testweaver.m2d.matrix-readback/v1' \
        --arg run_id "$run_id" \
        --arg checked_at "$collected_at" \
        --arg human_room_id "$human_room_id" \
        --arg human_event_id "$human_event_id" \
        --argjson event_count "$event_count" \
        --argjson room_count "$room_count" \
        --arg events_path "$events_path" \
        --arg index_path "$event_index_path" \
        --arg stage_path "$stage_path" \
        --arg rooms_path "$rooms_path" \
        '{schema: $schema, run_id: $run_id, checked_at: $checked_at, human_boundary: {room_id: $human_room_id, event_id: $human_event_id}, rooms_observed: $room_count, events_recorded: $event_count, paths: {events: $events_path, index: $index_path, stages: $stage_path, rooms_state: $rooms_path}, credentials: {base_url_variable: "AGENTTEAMS_MATRIX_URL", manager_access_token_variable: "AGENTTEAMS_MANAGER_MATRIX_TOKEN", worker_access_token_variable: "AGENTTEAMS_WORKER_MATRIX_TOKEN", values_persisted: false}, writes: false}' \
        > "$status_path"
    chmod 600 "$status_path"
}

mode="${1:---once}"
if ! mkdir "$lock_path" 2>/dev/null; then
    exit 0
fi
trap 'rmdir "$lock_path" 2>/dev/null || true' EXIT

case "$mode" in
    --once)
        collect_once
        ;;
    --follow)
        while :; do
            collect_once || true
            sleep 10
        done
        ;;
    *)
        exit 2
        ;;
esac
