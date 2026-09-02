#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
package_root="${repo_root}/testweaver/skills/native-agentspec-package"
source_root="${repo_root}/testweaver/skills"

expected_names=(
  approval-intent-boundary-check
  avoid-redundant-exploration
  diagnose-by-competing-hypotheses
  preserve-critical-constraints
  reconcile-before-retry
)

command -v jq >/dev/null
test -f "${package_root}/manifest.json"
test -d "${package_root}/skills"
test ! -e "${package_root}/bundle-manifest.json"

jq -e 'type == "object" and .version == "1.0" and has("schema_version") | not' \
  "${package_root}/manifest.json" >/dev/null
jq -e '(.worker // {}) | has("suggested_name") | not' \
  "${package_root}/manifest.json" >/dev/null
package_version="$(jq -er '.version | strings | select(length > 0)' "${package_root}/manifest.json")"
package_source_commit="$(jq -er '.source.source_commit | strings | select(length > 0)' "${package_root}/manifest.json")"
manifest_sha256="$(sha256sum "${package_root}/manifest.json" | cut -d' ' -f1)"

mapfile -t actual_names < <(
  find "${package_root}/skills" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort
)
if [[ "${actual_names[*]}" != "${expected_names[*]}" ]]; then
  printf 'package skill directories mismatch\n' >&2
  exit 1
fi

for name in "${expected_names[@]}"; do
  source_file="${source_root}/${name}/SKILL.md"
  package_file="${package_root}/skills/${name}/SKILL.md"
  test -f "${source_file}"
  test -f "${package_file}"
  cmp -s "${source_file}" "${package_file}"
  test "$(sha256sum "${source_file}" | cut -d' ' -f1)" = \
    "$(sha256sum "${package_file}" | cut -d' ' -f1)"
  head -n 1 "${package_file}" | grep -qx -- '---'
  sed -n '2,5p' "${package_file}" | grep -q '^name: '
  sed -n '2,5p' "${package_file}" | grep -q '^description: '
  sed -n '2,5p' "${package_file}" | grep -q '^assign_when: '
done

printf 'PASS: native AgentSpec package layout version=%s source_commit=%s manifest_sha256=%s skill_count=%s\n' \
  "${package_version}" "${package_source_commit}" "${manifest_sha256}" "${#expected_names[@]}"
