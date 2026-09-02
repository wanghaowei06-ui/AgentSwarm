#!/usr/bin/env bash
set -euo pipefail

adapter_root="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
: "${TESTWEAVER_QWENPAW_BASE_IMAGE:?set an immutable QwenPaw base image reference}"
: "${TESTWEAVER_QWENPAW_BASE_IMAGE_ID:?set the expected immutable base image ID}"
: "${TESTWEAVER_QWENPAW_IMAGE:?set an immutable output image tag}"
: "${TESTWEAVER_DSH_SOURCE_DIR:?set the fixed materialized DSH package directory}"
: "${TESTWEAVER_DSH_LOCKFILE:?set the fixed upstream pnpm lockfile}"
: "${TESTWEAVER_DSH_PROVENANCE:?set the fixed upstream provenance receipt}"

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

for file in __init__.py codex_cli.py config.py native_worker.py result.py executor.py mcp_server.py mcp_client.py; do
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
echo "build_context=${build_context}"
echo "base_image_id=${base_id}"
docker image inspect "${TESTWEAVER_QWENPAW_IMAGE}" \
  --format 'image_id={{.Id}} created={{.Created}} size={{.Size}}'
