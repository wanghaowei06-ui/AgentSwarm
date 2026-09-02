#!/usr/bin/env bash
set -euo pipefail

readonly TESTWEAVER_NODE_RUNTIME_VERSION="v22.23.1"
readonly TESTWEAVER_NODE_RUNTIME_SHA256="93956de2e59480474a7b46571da1651180b1a050cdf32641ebec4ce6e478e068"

preflight_node_runtime() {
  local executable="$1"
  local declared_sha256="$2"
  local actual_sha256
  local actual_version

  case "${executable}" in
    /*) ;;
    *)
      echo "TESTWEAVER_NODE_EXECUTABLE must be absolute" >&2
      return 2
      ;;
  esac
  if [ ! -f "${executable}" ] || [ -L "${executable}" ] || [ ! -x "${executable}" ]; then
    echo "TESTWEAVER_NODE_EXECUTABLE must be an executable regular non-symlink file" >&2
    return 2
  fi
  if [ "${declared_sha256}" != "${TESTWEAVER_NODE_RUNTIME_SHA256}" ]; then
    echo "TESTWEAVER_NODE_SHA256 does not match the locked runtime" >&2
    return 2
  fi
  actual_sha256="$(sha256sum -- "${executable}" | awk '{print $1}')"
  if [ "${actual_sha256}" != "${TESTWEAVER_NODE_RUNTIME_SHA256}" ]; then
    echo "Node runtime SHA256 does not match the locked runtime" >&2
    return 2
  fi
  actual_version="$("${executable}" --version)"
  if [ "${actual_version}" != "${TESTWEAVER_NODE_RUNTIME_VERSION}" ]; then
    echo "Node runtime version does not match ${TESTWEAVER_NODE_RUNTIME_VERSION}" >&2
    return 2
  fi
  if ! "${executable}" -e '
    const zlib = require("node:zlib");
    if (typeof Promise.withResolvers !== "function") process.exit(2);
    if (typeof zlib.createZstdDecompress !== "function") process.exit(2);
  '; then
    echo "Node runtime lacks required DSH headless capabilities" >&2
    return 2
  fi
}

main() {
  local adapter_root
  local base_id
  local build_context
  local dsh_stage
  local dsh_hash

  adapter_root="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
  : "${TESTWEAVER_QWENPAW_BASE_IMAGE:?set an immutable QwenPaw base image reference}"
  : "${TESTWEAVER_QWENPAW_BASE_IMAGE_ID:?set the expected immutable base image ID}"
  : "${TESTWEAVER_QWENPAW_IMAGE:?set an immutable output image tag}"
  : "${TESTWEAVER_DSH_SOURCE_DIR:?set the fixed materialized DSH package directory}"
  : "${TESTWEAVER_DSH_LOCKFILE:?set the fixed upstream pnpm lockfile}"
  : "${TESTWEAVER_DSH_PROVENANCE:?set the fixed upstream provenance receipt}"
  : "${TESTWEAVER_NODE_EXECUTABLE:?set the locked Node runtime executable path}"
  : "${TESTWEAVER_NODE_SHA256:?set the locked Node runtime SHA256}"

  preflight_node_runtime "${TESTWEAVER_NODE_EXECUTABLE}" "${TESTWEAVER_NODE_SHA256}"

  test -d "${TESTWEAVER_DSH_SOURCE_DIR}"
  test -f "${TESTWEAVER_DSH_LOCKFILE}"
  test -f "${TESTWEAVER_DSH_PROVENANCE}"
  if [ "${CODEX_CLI_SPEC:-@openai/codex@0.152.0}" != "@openai/codex@0.152.0" ]; then
    echo "CODEX_CLI_SPEC is fixed to @openai/codex@0.152.0" >&2
    exit 2
  fi

  base_id="$(docker image inspect "${TESTWEAVER_QWENPAW_BASE_IMAGE}" --format '{{.Id}}')"
  if [ "${base_id}" != "${TESTWEAVER_QWENPAW_BASE_IMAGE_ID}" ]; then
    echo "base image ID does not match the requested immutable input" >&2
    exit 2
  fi

  build_context="$(mktemp -d "${TMPDIR:-/tmp}/testweaver-qwenpaw-build.XXXXXX")"
  dsh_stage="$(mktemp -d "${TMPDIR:-/tmp}/testweaver-dsh-stage.XXXXXX")"
  python3 "${adapter_root}/scripts/package_dsh.py" \
    --source "${TESTWEAVER_DSH_SOURCE_DIR}" \
    --output "${dsh_stage}" \
    --canonical-lock "${TESTWEAVER_DSH_LOCKFILE}" \
    --provenance "${TESTWEAVER_DSH_PROVENANCE}"

  tar -C "${dsh_stage}" --sort=name --mtime='2026-01-01 00:00:00Z' \
    --owner=0 --group=0 --numeric-owner \
    --use-compress-program='gzip -n' -cf "${build_context}/dsh-runtime.tar.gz" .
  dsh_hash="$(sha256sum "${build_context}/dsh-runtime.tar.gz" | awk '{print $1}')"
  printf '%s  dsh-runtime.tar.gz\n' "${dsh_hash}" > "${build_context}/dsh-runtime.tar.gz.sha256"
  install -m 0755 -- "${TESTWEAVER_NODE_EXECUTABLE}" "${build_context}/node-runtime"
  test "$(sha256sum "${build_context}/node-runtime" | awk '{print $1}')" = "${TESTWEAVER_NODE_RUNTIME_SHA256}"

  for file in __init__.py codex_cli.py config.py native_worker.py result.py executor.py mcp_server.py; do
    cp "${adapter_root}/${file}" "${build_context}/${file}"
  done
  cp "${adapter_root}/Dockerfile.qwenpaw" "${build_context}/Dockerfile.qwenpaw"
  cp "${adapter_root}/dsh-launcher.mjs" "${build_context}/dsh-launcher.mjs"
  cp -a "${adapter_root}/qwenpaw-package" "${build_context}/qwenpaw-package"

  docker build --pull=false \
    --build-arg "QWENPAW_BASE_IMAGE=${TESTWEAVER_QWENPAW_BASE_IMAGE}" \
    --build-arg "TESTWEAVER_DSH_PACKAGE=dsh-runtime.tar.gz" \
    --build-arg "TESTWEAVER_DSH_PACKAGE_SHA256=dsh-runtime.tar.gz.sha256" \
    -f "${build_context}/Dockerfile.qwenpaw" \
    -t "${TESTWEAVER_QWENPAW_IMAGE}" \
    "${build_context}"

  echo "dsh_package_sha256=${dsh_hash}"
  echo "node_runtime_sha256=${TESTWEAVER_NODE_RUNTIME_SHA256}"
  echo "build_context=${build_context}"
  echo "base_image_id=${base_id}"
  docker image inspect "${TESTWEAVER_QWENPAW_IMAGE}" \
    --format 'image_id={{.Id}} created={{.Created}} size={{.Size}}'
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
