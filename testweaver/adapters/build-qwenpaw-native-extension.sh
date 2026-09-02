#!/usr/bin/env bash
set -euo pipefail

adapter_root="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
: "${TESTWEAVER_QWENPAW_BASE_IMAGE:?set an immutable QwenPaw base image reference}"
: "${TESTWEAVER_QWENPAW_IMAGE:?set an immutable output image tag}"
: "${TESTWEAVER_DSH_BINARY:?set a DSH executable path relative to testweaver/adapters}"

case "${TESTWEAVER_DSH_BINARY}" in
  /*|../*|*/../*|*" "*)
    echo "TESTWEAVER_DSH_BINARY must be a safe relative path" >&2
    exit 2
    ;;
esac
test -f "${adapter_root}/${TESTWEAVER_DSH_BINARY}"
test ! -L "${adapter_root}/${TESTWEAVER_DSH_BINARY}"
test -x "${adapter_root}/${TESTWEAVER_DSH_BINARY}"

exec docker build --pull=false \
  --build-arg "QWENPAW_BASE_IMAGE=${TESTWEAVER_QWENPAW_BASE_IMAGE}" \
  --build-arg "TESTWEAVER_DSH_BINARY=${TESTWEAVER_DSH_BINARY}" \
  --build-arg "CODEX_CLI_SPEC=${CODEX_CLI_SPEC:-@openai/codex@0.152.0}" \
  -f "${adapter_root}/Dockerfile.qwenpaw" \
  -t "${TESTWEAVER_QWENPAW_IMAGE}" \
  "${adapter_root}"
