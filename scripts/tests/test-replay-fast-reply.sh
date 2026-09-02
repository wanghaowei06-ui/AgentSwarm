#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPLAY_SCRIPT="${ROOT_DIR}/scripts/replay-task.sh"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/agentteams-replay-fast-reply.XXXXXX")"
trap 'rm -rf "${TEST_ROOT}"' EXIT

FAKE_BIN="${TEST_ROOT}/bin"
FAKE_STATE="${TEST_ROOT}/manager-replied"
MESSAGES_CAPTURE="${TEST_ROOT}/messages-called"
SENT_URL_CAPTURE="${TEST_ROOT}/sent-url"
TEST_HOME="${TEST_ROOT}/home"
LOG_DIR="${TEST_ROOT}/logs"
mkdir -p "${FAKE_BIN}" "${TEST_HOME}" "${LOG_DIR}"

cat > "${FAKE_BIN}/docker" <<'EOF'
#!/usr/bin/env bash
set -e

if [ "${1:-}" = "exec" ] && [ "${3:-}" = "openclaw" ]; then
    printf '{"ok":true}\n'
    exit 0
fi

printf 'unexpected docker invocation: %s\n' "$*" >&2
exit 1
EOF

cat > "${FAKE_BIN}/curl" <<'EOF'
#!/usr/bin/env bash
set -e

url="${!#}"
case "${url}" in
    */_matrix/client/v3/login)
        printf '{"access_token":"test-token"}\n'
        ;;
    */_matrix/client/v3/joined_rooms)
        printf 'unexpected room discovery\n' >&2
        exit 1
        ;;
    */_matrix/client/v3/rooms/*/members)
        printf '{"chunk":[{"state_key":"@admin:matrix.test"},{"state_key":"@manager:matrix.test"}]}\n'
        ;;
    */_matrix/client/v3/rooms/*/messages*)
        printf 'called\n' >> "${REPLAY_MESSAGES_CAPTURE}"
        if [ -f "${REPLAY_FAKE_STATE}" ]; then
            printf '%s\n' '{"chunk":[{"sender":"@manager:matrix.test","event_id":"$new","origin_server_ts":2,"content":{"body":"fast reply"}},{"sender":"@manager:matrix.test","event_id":"$old","origin_server_ts":1,"content":{"body":"old reply"}}]}'
        else
            printf '%s\n' '{"chunk":[{"sender":"@manager:matrix.test","event_id":"$old","origin_server_ts":1,"content":{"body":"old reply"}}]}'
        fi
        ;;
    */_matrix/client/v3/createRoom)
        printf 'unexpected room creation\n' >&2
        exit 1
        ;;
    */send/m.room.message/*)
        : > "${REPLAY_FAKE_STATE}"
        printf '%s\n' "${url}" > "${REPLAY_SENT_URL_CAPTURE}"
        printf '{"event_id":"$sent"}\n'
        ;;
    *)
        printf 'unexpected curl URL: %s\n' "${url}" >&2
        exit 1
        ;;
esac
EOF

cat > "${FAKE_BIN}/sleep" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF

chmod +x "${FAKE_BIN}/docker" "${FAKE_BIN}/curl" "${FAKE_BIN}/sleep"

set +e
OUTPUT="$({
    env \
        HOME="${TEST_HOME}" \
        PATH="${FAKE_BIN}:${PATH}" \
        REPLAY_FAKE_STATE="${FAKE_STATE}" \
        REPLAY_MESSAGES_CAPTURE="${MESSAGES_CAPTURE}" \
        REPLAY_SENT_URL_CAPTURE="${SENT_URL_CAPTURE}" \
        REPLAY_LOG_DIR="${LOG_DIR}" \
        REPLAY_TIMEOUT=1 \
        REPLAY_READY_TIMEOUT=1 \
        REPLAY_ROOM_ID='!explicit:matrix.test' \
        AGENTTEAMS_ADMIN_PASSWORD=test-password \
        AGENTTEAMS_MATRIX_DOMAIN=matrix.test \
        TEST_REGISTRATION_TOKEN=test-token \
        bash "${REPLAY_SCRIPT}" "fast task"
} 2>&1)"
RC=$?
set -e

if [ "${RC}" -ne 0 ]; then
    printf 'FAIL: replay command exited %d\n%s\n' "${RC}" "${OUTPUT}" >&2
    exit 1
fi

if [[ "${OUTPUT}" != *"fast reply"* ]]; then
    printf 'FAIL: replay command did not capture the immediate reply\n%s\n' "${OUTPUT}" >&2
    exit 1
fi

if ! grep -q '%21explicit%3Amatrix.test' "${SENT_URL_CAPTURE}"; then
    printf 'FAIL: replay command did not send to the explicit room\n%s\n' "${OUTPUT}" >&2
    exit 1
fi

printf 'PASS: replay command captures a reply that arrives immediately after send\n'

rm -f "${FAKE_STATE}" "${MESSAGES_CAPTURE}"
set +e
OUTPUT="$({
    env \
        HOME="${TEST_HOME}" \
        PATH="${FAKE_BIN}:${PATH}" \
        REPLAY_FAKE_STATE="${FAKE_STATE}" \
        REPLAY_MESSAGES_CAPTURE="${MESSAGES_CAPTURE}" \
        REPLAY_SENT_URL_CAPTURE="${SENT_URL_CAPTURE}" \
        REPLAY_LOG_DIR="${LOG_DIR}" \
        REPLAY_WAIT=0 \
        REPLAY_READY_TIMEOUT=1 \
        REPLAY_ROOM_ID='!explicit:matrix.test' \
        AGENTTEAMS_ADMIN_PASSWORD=test-password \
        AGENTTEAMS_MATRIX_DOMAIN=matrix.test \
        TEST_REGISTRATION_TOKEN=test-token \
        bash "${REPLAY_SCRIPT}" "fire and forget"
} 2>&1)"
RC=$?
set -e

if [ "${RC}" -ne 0 ]; then
    printf 'FAIL: no-wait replay command exited %d\n%s\n' "${RC}" "${OUTPUT}" >&2
    exit 1
fi

if [ -e "${MESSAGES_CAPTURE}" ]; then
    printf 'FAIL: no-wait replay command fetched message history\n%s\n' "${OUTPUT}" >&2
    exit 1
fi

printf 'PASS: no-wait replay command does not fetch message history\n'

rm -f "${FAKE_STATE}" "${MESSAGES_CAPTURE}" "${SENT_URL_CAPTURE}"
set +e
OUTPUT="$({
    env \
        HOME="${TEST_HOME}" \
        PATH="${FAKE_BIN}:${PATH}" \
        REPLAY_FAKE_STATE="${FAKE_STATE}" \
        REPLAY_MESSAGES_CAPTURE="${MESSAGES_CAPTURE}" \
        REPLAY_SENT_URL_CAPTURE="${SENT_URL_CAPTURE}" \
        REPLAY_LOG_DIR="${LOG_DIR}" \
        REPLAY_WAIT=0 \
        REPLAY_READY_TIMEOUT=1 \
        AGENTTEAMS_ADMIN_PASSWORD=test-password \
        AGENTTEAMS_MATRIX_DOMAIN=matrix.test \
        bash "${REPLAY_SCRIPT}" "missing room"
} 2>&1)"
RC=$?
set -e

if [ "${RC}" -eq 0 ] || [[ "${OUTPUT}" != *"REPLAY_ROOM_ID"* ]]; then
    printf 'FAIL: missing REPLAY_ROOM_ID did not fail closed\n%s\n' "${OUTPUT}" >&2
    exit 1
fi

if [ -e "${SENT_URL_CAPTURE}" ]; then
    printf 'FAIL: missing REPLAY_ROOM_ID attempted a send\n%s\n' "${OUTPUT}" >&2
    exit 1
fi

printf 'PASS: missing explicit room fails closed without discovery or send\n'

rm -f "${FAKE_STATE}" "${MESSAGES_CAPTURE}" "${SENT_URL_CAPTURE}"
set +e
OUTPUT="$({
    env \
        HOME="${TEST_HOME}" \
        PATH="${FAKE_BIN}:${PATH}" \
        REPLAY_FAKE_STATE="${FAKE_STATE}" \
        REPLAY_MESSAGES_CAPTURE="${MESSAGES_CAPTURE}" \
        REPLAY_SENT_URL_CAPTURE="${SENT_URL_CAPTURE}" \
        REPLAY_LOG_DIR="${LOG_DIR}" \
        REPLAY_WAIT=0 \
        REPLAY_READY_TIMEOUT=1 \
        REPLAY_ROOM_ID=invalid-room \
        AGENTTEAMS_ADMIN_PASSWORD=test-password \
        AGENTTEAMS_MATRIX_DOMAIN=matrix.test \
        bash "${REPLAY_SCRIPT}" "invalid room"
} 2>&1)"
RC=$?
set -e

if [ "${RC}" -eq 0 ] || [[ "${OUTPUT}" != *"invalid"* ]]; then
    printf 'FAIL: invalid REPLAY_ROOM_ID did not fail closed\n%s\n' "${OUTPUT}" >&2
    exit 1
fi

if [ -e "${SENT_URL_CAPTURE}" ]; then
    printf 'FAIL: invalid REPLAY_ROOM_ID attempted a send\n%s\n' "${OUTPUT}" >&2
    exit 1
fi

printf 'PASS: invalid explicit room fails closed without discovery or send\n'
