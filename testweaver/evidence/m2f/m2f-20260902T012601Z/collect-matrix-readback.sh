#!/usr/bin/env bash
set -euo pipefail

umask 077
script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
evidence_dir="$script_dir"
state_dir="$evidence_dir/.state"
redactor="$evidence_dir/redact-docker-log.pl"
human_event_path="$evidence_dir/human-event.json"
events_path="$evidence_dir/matrix-events.jsonl"
index_path="$evidence_dir/matrix-event-index.jsonl"
status_path="$evidence_dir/matrix-collector-status.json"
seen_path="$state_dir/matrix-seen-event-ids"
rooms_path="$state_dir/matrix-rooms.tsv"

mkdir -p "$state_dir"
touch "$events_path" "$index_path" "$seen_path" "$rooms_path"
for command_name in docker jq perl sha256sum date; do
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
case "$human_origin_ts" in
    ''|*[!0-9]*) exit 64 ;;
esac
jq -n --arg run_id "$run_id" --arg room_id "$human_room_id" --arg event_id "$human_event_id" \
    --arg sender "$human_sender" --arg ts "$human_origin_ts" --arg body_sha "$human_body_sha" \
    '{schema:"testweaver.m2f.human-event-hash/v1",run_id:$run_id,room_id:$room_id,event_id:$event_id,sender:$sender,origin_server_ts:($ts|tonumber),body_sha256:$body_sha,values_redacted:true}' \
    > "$evidence_dir/human-event-hash.json"
chmod 600 "$evidence_dir/human-event-hash.json"

actor_specs='manager|agentteams-native-m0-20260901-manager|AGENTTEAMS_MANAGER_MATRIX_TOKEN native-m0-clean-leader|agentteams-native-m0-20260901-worker-native-m0-clean-leader|AGENTTEAMS_WORKER_MATRIX_TOKEN native-m0-clean-worker|agentteams-native-m0-20260901-worker-native-m0-clean-worker|AGENTTEAMS_WORKER_MATRIX_TOKEN native-m1-verify-leader|agentteams-native-m0-20260901-worker-native-m1-verify-leader|AGENTTEAMS_WORKER_MATRIX_TOKEN native-m1-verify-worker|agentteams-native-m0-20260901-worker-native-m1-verify-worker|AGENTTEAMS_WORKER_MATRIX_TOKEN'

matrix_get_actor() {
    local container="$1"
    local token_var="$2"
    local request_path="$3"
    local output_path="$4"
    local temporary_path="$output_path.tmp.$$"
    if docker exec "$container" sh -c '
        token_var="$1"
        request_path="$2"
        matrix_url="$AGENTTEAMS_MATRIX_URL"
        matrix_url=$(printf "%s" "$matrix_url" | sed "s:/*$::")
        case "$token_var" in
            AGENTTEAMS_MANAGER_MATRIX_TOKEN) token="$AGENTTEAMS_MANAGER_MATRIX_TOKEN" ;;
            AGENTTEAMS_WORKER_MATRIX_TOKEN) token="$AGENTTEAMS_WORKER_MATRIX_TOKEN" ;;
            *) exit 66 ;;
        esac
        test -n "$matrix_url"
        test -n "$token"
        curl -fsS --max-time 10 -H "Authorization: Bearer $token" "$matrix_url$request_path"
    ' _ "$token_var" "$request_path" 2>/dev/null | perl "$redactor" > "$temporary_path"; then
        mv "$temporary_path" "$output_path"
        chmod 600 "$output_path"
        return 0
    fi
    return 1
}

record_events() {
    local payload_path="$1"
    local actor="$2"
    local source="$3"
    local collected_at="$4"
    while IFS= read -r event; do
        [ -n "$event" ] || continue
        event_id="$(printf "%s" "$event" | jq -r '.event_id // empty' 2>/dev/null || true)"
        [ -n "$event_id" ] || continue
        if grep -Fqx -- "$event_id" "$seen_path" 2>/dev/null; then
            continue
        fi
        room_id="$(printf "%s" "$event" | jq -r '.room_id // empty' 2>/dev/null || true)"
        sender="$(printf "%s" "$event" | jq -r '.sender // empty' 2>/dev/null || true)"
        origin_ts="$(printf "%s" "$event" | jq -r '.origin_server_ts // empty' 2>/dev/null || true)"
        event_type="$(printf "%s" "$event" | jq -r '.type // empty' 2>/dev/null || true)"
        event_sha="$(printf "%s" "$event" | sha256sum | awk '{print $1}')"
        printf "%s\n" "$event" >> "$events_path"
        printf "%s\n" "$event_id" >> "$seen_path"
        jq -cn --arg collected_at "$collected_at" --arg actor "$actor" --arg source "$source" \
            --arg raw_path "$events_path" --arg event_id "$event_id" --arg room_id "$room_id" \
            --arg sender "$sender" --arg ts "$origin_ts" --arg event_type "$event_type" \
            --arg event_sha "$event_sha" \
            '{collected_at:$collected_at,actor:$actor,source:$source,raw_event_path:$raw_path,event_id:$event_id,room_id:$room_id,sender:$sender,origin_server_ts:($ts|tonumber),type:$event_type,captured_event_sha256:$event_sha}' \
            >> "$index_path"
    done < <(jq -c --argjson boundary "$human_origin_ts" '.chunk[]? | select((.origin_server_ts // 0) >= $boundary)' "$payload_path" 2>/dev/null || true)
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
    actor_key="$(printf "%s" "$actor" | tr -c 'A-Za-z0-9._-' '_')"
    joined_path="$state_dir/joined-$actor_key.json"
    collected_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    if ! matrix_get_actor "$container" "$token_var" "/_matrix/client/v3/joined_rooms" "$joined_path"; then
        printf "%s\t%s\t%s\tunavailable\n" "$actor" "$container" "$collected_at" >> "$rooms_path"
        return 0
    fi
    while IFS= read -r room_id; do
        [ -n "$room_id" ] || continue
        room_number=$((room_number + 1))
        room_path="$(printf "%s" "$room_id" | jq -sRr @uri)"
        message_path="$state_dir/messages-$actor_key-$room_number.json"
        if matrix_get_actor "$container" "$token_var" "/_matrix/client/v3/rooms/$room_path/messages?dir=b&limit=100" "$message_path"; then
            printf "%s\t%s\t%s\t%s\n" "$actor" "$container" "$room_id" "$message_path" >> "$rooms_path"
            record_events "$message_path" "$actor" "$actor.room_messages" "$collected_at"
        else
            printf "%s\t%s\t%s\tread_failed\n" "$actor" "$container" "$room_id" >> "$rooms_path"
        fi
    done < <(jq -r '.joined_rooms[]?' "$joined_path" 2>/dev/null || true)
}

: > "$rooms_path"
for spec in $actor_specs; do
    IFS='|' read -r actor container token_var <<< "$spec"
    collect_actor "$actor" "$container" "$token_var"
done

checked_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
event_count="$(wc -l < "$events_path" | tr -d ' ')"
room_count="$(awk -F '\t' 'NF >= 3 {key=$1 FS $3; if (!(key in seen)) {seen[key]=1; count++}} END {print count+0}' "$rooms_path")"
jq -n --arg schema "testweaver.m2f.matrix-readback/v1" --arg run_id "$run_id" \
    --arg checked_at "$checked_at" --arg room_id "$human_room_id" --arg event_id "$human_event_id" \
    --arg events_path "$events_path" --arg index_path "$index_path" --arg rooms_path "$rooms_path" \
    --argjson event_count "$event_count" --argjson room_count "$room_count" \
    '{schema:$schema,run_id:$run_id,checked_at:$checked_at,human_boundary:{room_id:$room_id,event_id:$event_id},rooms_observed:$room_count,events_recorded:$event_count,paths:{events:$events_path,index:$index_path,rooms_state:$rooms_path},credentials:{base_url_variable:"AGENTTEAMS_MATRIX_URL",manager_access_token_variable:"AGENTTEAMS_MANAGER_MATRIX_TOKEN",worker_access_token_variable:"AGENTTEAMS_WORKER_MATRIX_TOKEN",values_persisted:false},writes:{matrix:false,evidence:true}}' \
    > "$status_path"
chmod 600 "$status_path"
printf "matrix_readback=%s\n" "$status_path"
printf "rooms_observed=%s events_recorded=%s\n" "$room_count" "$event_count"
