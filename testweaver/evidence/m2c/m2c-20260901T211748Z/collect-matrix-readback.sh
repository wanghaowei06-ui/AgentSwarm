#!/usr/bin/env bash
set -euo pipefail

umask 077

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../../.." && pwd)"
evidence_dir="$script_dir"
state_dir="$evidence_dir/.state"
baseline_path="$evidence_dir/baseline-manifest.json"
redactor="$evidence_dir/redact-docker-log.pl"
manager_container='agentteams-native-m0-20260901-manager'

events_path="$evidence_dir/matrix-events.jsonl"
event_index_path="$evidence_dir/matrix-event-index.jsonl"
stage_path="$evidence_dir/matrix-stage-observations.jsonl"
status_path="$evidence_dir/matrix-collector-status.json"
seen_path="$state_dir/matrix-seen-event-ids"
cursor_path="$state_dir/matrix-cursor"
fixed_path="$state_dir/matrix-fixed-event.json"
context_path="$state_dir/matrix-context.json"
messages_path="$state_dir/matrix-messages.json"
lock_path="$state_dir/matrix-collector.lock"

mkdir -p "$state_dir"
touch "$events_path" "$event_index_path" "$stage_path" "$seen_path"

for command_name in docker jq perl sha256sum date wc; do
    command -v "$command_name" >/dev/null 2>&1
done
test -r "$baseline_path"
test -r "$redactor"

room_id="$(jq -r '.frozen_human_input.room_id' "$baseline_path")"
event_id="$(jq -r '.frozen_human_input.event_id' "$baseline_path")"
expected_sender="$(jq -r '.frozen_human_input.sender' "$baseline_path")"
expected_origin_ts="$(jq -r '.frozen_human_input.origin_server_ts' "$baseline_path")"
expected_body_sha="$(jq -r '.frozen_human_input.body_sha256' "$baseline_path")"
run_id="$(jq -r '.frozen_human_input.run_id' "$baseline_path")"
manager_sender="$(jq -r '.manager.resource.matrixUserID // empty' "$baseline_path")"

# These are only URL path encodings of the supplied public Matrix identifiers.
room_path="$(printf '%s' "$room_id" | jq -sRr @uri)"
event_path="$(printf '%s' "$event_id" | jq -sRr @uri)"
fixed_request="/_matrix/client/v3/rooms/$room_path/event/$event_path"
context_request="/_matrix/client/v3/rooms/$room_path/context/$event_path?limit=100"

matrix_get() {
    local request_path="$1"
    local output_path="$2"
    local temporary_path="${output_path}.tmp.$$"

    if docker exec "$manager_container" sh -c '
        matrix_url="${AGENTTEAMS_MATRIX_URL%/}"
        [ -n "$matrix_url" ] || exit 64
        [ -n "${AGENTTEAMS_MANAGER_MATRIX_TOKEN:-}" ] || exit 65
        curl -fsS --max-time 10 \
            -H "Authorization: Bearer ${AGENTTEAMS_MANAGER_MATRIX_TOKEN}" \
            "${matrix_url}${1}"
    ' _ "$request_path" 2>/dev/null | perl "$redactor" > "$temporary_path"; then
        mv -f "$temporary_path" "$output_path"
        chmod 600 "$output_path"
        return 0
    fi
    rm -f "$temporary_path"
    return 1
}

matrix_get_messages() {
    local cursor="$1"
    local output_path="$2"
    local temporary_path="${output_path}.tmp.$$"

    if docker exec "$manager_container" sh -c '
        matrix_url="${AGENTTEAMS_MATRIX_URL%/}"
        [ -n "$matrix_url" ] || exit 64
        [ -n "${AGENTTEAMS_MANAGER_MATRIX_TOKEN:-}" ] || exit 65
        curl -fsS --get --max-time 10 \
            -H "Authorization: Bearer ${AGENTTEAMS_MANAGER_MATRIX_TOKEN}" \
            "${matrix_url}/_matrix/client/v3/rooms/${1}/messages" \
            --data-urlencode "dir=f" \
            --data-urlencode "from=${2}" \
            --data-urlencode "limit=100"
    ' _ "$room_path" "$cursor" 2>/dev/null | perl "$redactor" > "$temporary_path"; then
        mv -f "$temporary_path" "$output_path"
        chmod 600 "$output_path"
        return 0
    fi
    rm -f "$temporary_path"
    return 1
}

record_event_lines() {
    local payload_path="$1"
    local jq_filter="$2"
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
            --arg source "$source" \
            --arg event_id "$observed_event_id" \
            --arg room_id "$observed_room_id" \
            --arg sender "$observed_sender" \
            --arg origin_server_ts "$observed_origin_ts" \
            --arg type "$observed_type" \
            --arg event_sha256 "$event_sha" \
            '{collected_at: $collected_at, source: $source, raw_event_path: "testweaver/evidence/m2c/m2c-20260901T211748Z/matrix-events.jsonl", event_id: $event_id, room_id: $room_id, sender: $sender, origin_server_ts: $origin_server_ts, type: $type, captured_event_sha256: $event_sha256}' \
            >> "$event_index_path"
    done < <(jq -c "$jq_filter" "$payload_path" 2>/dev/null || true)
}

write_stage_observation() {
    local collected_at="$1"
    local fixed_observed_json="$2"
    local fixed_body_hash_match="$3"
    local fixed_metadata_match="$4"
    local manager_post_pattern='(^|:)manager:'

    jq -c -s \
        --arg collected_at "$collected_at" \
        --arg fixed_id "$event_id" \
        --arg manager_sender "$manager_sender" \
        --arg manager_pattern "$manager_post_pattern" \
        --argjson fixed_observed "$fixed_observed_json" \
        --arg fixed_body_hash_match "$fixed_body_hash_match" \
        --arg fixed_metadata_match "$fixed_metadata_match" '
        def post: map(select(.event_id != $fixed_id));
        def body: (.content.body // "") | tostring;
        (post) as $post
        | ([$post[] | select(((.sender // "") == $manager_sender) or ((.sender // "") | test($manager_pattern)))] ) as $manager_events
        | ([$post[] | select(((.sender // "") | test("native-m[01]-[^:]*-leader|team[-_ ]leader"; "i")))] ) as $leader_events
        | ([$post[] | select(((.sender // "") | test("native-m[01]-[^:]*-worker|team[-_ ]worker"; "i")))] ) as $worker_events
        | ([$post[] | select(
              ((.sender // "") | test("native-m[01]-[^:]*-leader|team[-_ ]leader"; "i"))
              and (body | test("project"; "i"))
              and (body | test("task"; "i"))
          )]) as $delegation_events
        | ([$post[] | select(
              (((.sender // "") == $manager_sender) or ((.sender // "") | test($manager_pattern)) or ((.sender // "") | test("native-m[01]-[^:]*-leader|team[-_ ]leader"; "i")))
              and (body | test("accepted"; "i"))
              and (body | test("report"; "i"))
          )]) as $accepted_events
        | ([$post[] | select(
              (body | test("pause_project|project[^\\n]*(paused|pause)|PAUSE"; "i"))
              and (body | test("approval|approve|批准|审批"; "i"))
              and (body | test("project[ _-]*id|task[ _-]*id|项目[^\\n]*(ID|id)|任务[^\\n]*(ID|id)"; "i"))
              and (body | test("worker|容器"; "i"))
              and (body | test("rollback|revert|recover|回滚|恢复"; "i"))
          )]) as $pause_events
        | {
            collected_at: $collected_at,
            basis: "read-only Matrix event stream; no inference from receipts or runtime control",
            stages: [
              {stage: "human_freeze_event", state: (if $fixed_observed then "observed" else "not_observed" end), evidence_event_ids: (if $fixed_observed then [$fixed_id] else [] end), criteria: "exact supplied event id, room, sender, origin_server_ts, and body hash"},
              {stage: "subsequent_matrix_event", state: (if ($post | length) > 0 then "observed" else "not_observed" end), evidence_event_ids: ($post | map(.event_id))},
              {stage: "manager_activity_after_freeze", state: (if ($manager_events | length) > 0 then "observed" else "not_observed" end), evidence_event_ids: ($manager_events | map(.event_id))},
              {stage: "leader_project_task_delegation", state: (if ($delegation_events | length) > 0 then "observed" else "not_observed" end), evidence_event_ids: ($delegation_events | map(.event_id)), criteria: "post-freeze leader event body explicitly contains project and task"},
              {stage: "worker_activity_or_return", state: (if ($worker_events | length) > 0 then "observed" else "not_observed" end), evidence_event_ids: ($worker_events | map(.event_id))},
              {stage: "accepted_report", state: (if ($accepted_events | length) > 0 then "observed" else "not_observed" end), evidence_event_ids: ($accepted_events | map(.event_id)), criteria: "post-freeze leader/manager event body contains accepted and report"},
              {stage: "pause_or_approval_request", state: (if ($pause_events | length) > 0 then "observed" else "not_observed" end), evidence_event_ids: ($pause_events | map(.event_id)), criteria: "raw Matrix body contains a native pause/approval marker"},
              {stage: "manager_followup_decision_activity", state: (if ($manager_events | length) >= 2 then "observed" else "not_observed" end), evidence_event_ids: ($manager_events | map(.event_id)), criteria: "at least two post-freeze Manager-sender events; no semantic inference"}
            ],
            fixed_event_checks: {body_hash: $fixed_body_hash_match, metadata: $fixed_metadata_match}
          }
    ' "$events_path" >> "$stage_path"
}

collect_once() {
    local collected_at
    local fixed_state='not_observed'
    local body_hash_match='not_checked'
    local metadata_match='not_checked'
    local context_state='not_observed'
    local messages_state='not_observed'
    local fixed_observed_json=false
    local fixed_event_id
    local observed_body_sha
    local cursor=''
    local next_cursor=''
    local event_count
    local temporary_status

    collected_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    if [ ! -s "$fixed_path" ] || ! jq -e --arg event_id "$event_id" '.event_id == $event_id' "$fixed_path" >/dev/null 2>&1; then
        matrix_get "$fixed_request" "$fixed_path" || true
    fi

    if [ -s "$fixed_path" ] && jq -e --arg event_id "$event_id" --arg room_id "$room_id" --arg sender "$expected_sender" --argjson origin_ts "$expected_origin_ts" '
        .event_id == $event_id and .room_id == $room_id and .sender == $sender and .origin_server_ts == $origin_ts
    ' "$fixed_path" >/dev/null 2>&1; then
        metadata_match='matched'
        observed_body_sha="$(jq -j '.content.body // empty' "$fixed_path" | sha256sum | awk '{print $1}')"
        if [ "$observed_body_sha" = "$expected_body_sha" ]; then
            body_hash_match='matched'
            fixed_state='observed'
            fixed_observed_json=true
        else
            body_hash_match='mismatch'
            fixed_state='not_observed'
        fi
        fixed_event_id="$(jq -r '.event_id' "$fixed_path")"
        if [ "$fixed_event_id" = "$event_id" ]; then
            record_event_lines "$fixed_path" '.' 'fixed_event_endpoint' "$collected_at"
        fi
    elif [ -s "$fixed_path" ]; then
        metadata_match='mismatch'
        fixed_event_id="$(jq -r '.event_id // empty' "$fixed_path" 2>/dev/null || true)"
        if [ "$fixed_event_id" = "$event_id" ]; then
            record_event_lines "$fixed_path" '.' 'fixed_event_endpoint' "$collected_at"
        fi
    fi

    if [ ! -s "$cursor_path" ]; then
        if matrix_get "$context_request" "$context_path"; then
            context_state='observed'
            record_event_lines "$context_path" '.events_after[]?' 'room_context.events_after' "$collected_at"
            cursor="$(jq -r '.end // empty' "$context_path" 2>/dev/null || true)"
            if [ -n "$cursor" ]; then
                printf '%s\n' "$cursor" > "$cursor_path"
                chmod 600 "$cursor_path"
            fi
        fi
    else
        cursor="$(sed -n '1p' "$cursor_path")"
        if [ -n "$cursor" ] && matrix_get_messages "$cursor" "$messages_path"; then
            messages_state='observed'
            record_event_lines "$messages_path" '.chunk[]?' 'room_messages.chunk' "$collected_at"
            next_cursor="$(jq -r '.end // empty' "$messages_path" 2>/dev/null || true)"
            if [ -n "$next_cursor" ] && [ "$next_cursor" != "$cursor" ]; then
                printf '%s\n' "$next_cursor" > "$cursor_path"
                chmod 600 "$cursor_path"
            fi
        fi
    fi

    write_stage_observation "$collected_at" "$fixed_observed_json" "$body_hash_match" "$metadata_match"
    event_count="$(wc -l < "$events_path" | tr -d ' ')"
    temporary_status="${status_path}.tmp.$$"
    jq -n \
        --arg schema 'testweaver.m1plus.matrix-readback/v1' \
        --arg run_id "$run_id" \
        --arg checked_at "$collected_at" \
        --arg fixed_state "$fixed_state" \
        --arg body_hash_match "$body_hash_match" \
        --arg metadata_match "$metadata_match" \
        --arg context_state "$context_state" \
        --arg messages_state "$messages_state" \
        --argjson event_count "$event_count" \
        '{schema: $schema, run_id: $run_id, checked_at: $checked_at, fixed_event: {state: $fixed_state, body_hash: $body_hash_match, metadata: $metadata_match}, subsequent_readback: {context: $context_state, messages: $messages_state}, events_recorded: $event_count, credentials: {base_url_variable: "AGENTTEAMS_MATRIX_URL", access_token_variable: "AGENTTEAMS_MANAGER_MATRIX_TOKEN", values_persisted: false}, writes: false}' \
        > "$temporary_status"
    mv -f "$temporary_status" "$status_path"
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
