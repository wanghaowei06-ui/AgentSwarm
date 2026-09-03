#!/usr/bin/env bash
set -euo pipefail

package_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
manifest="${package_root}/manifest.json"
instructions="${package_root}/config/AGENTS.md"
skills_root="${package_root}/skills"

if [[ ! -f "${instructions}" ]]; then
    echo "RED: native AgentSpec config/AGENTS.md is missing" >&2
    exit 1
fi

command -v jq >/dev/null
test -f "${manifest}"
version="$(jq -er '.version | strings | select(length > 0)' "${manifest}")"
source_commit="$(jq -er '.source.source_commit | strings | select(length > 0)' "${manifest}")"
content="$(<"${instructions}")"

required_fragments=(
    "assign_when"
    "native Skill inventory"
    "workspace/skills/<exact-skill-name>/SKILL.md"
    "skill_name:"
    "source_commit:"
    "version:"
    "evidence_ref:"
    "zero or more"
    "Do not require or load every Skill"
    "If no Skill applies"
    "normal AgentTeams task/handoff path"
    "Human, Manager, Leader, and Worker"
    "use Chinese by default"
    "protocol field names"
    "log keys"
    "evidence identifiers"
    "stable English"
)
for fragment in "${required_fragments[@]}"; do
    if ! grep -Fq -- "${fragment}" <<<"${content}"; then
        echo "RED: instruction contract missing: ${fragment}" >&2
        exit 1
    fi
done

grep -Fq -- "source_commit: ${source_commit}" "${instructions}"
grep -Fq -- "version: ${version}" "${instructions}"

if grep -Eiq -- '(must|required)[[:space:]].*all[[:space:]]+(available[[:space:]]+)?skills|load[[:space:]]+all[[:space:]]+(available[[:space:]]+)?skills' "${instructions}"; then
    echo "RED: instruction contract requires loading every Skill" >&2
    exit 1
fi
if grep -Eiq -- 'm1plus|native-m0|native-m1|task-[0-9]{6,}|room[_ -]?id' "${instructions}"; then
    echo "RED: instruction contract is tied to a concrete case" >&2
    exit 1
fi
if grep -Eiq -- '(^|[^[:alnum:]_])(runner|observer|dispatcher)([^[:alnum:]_]|$)' "${instructions}"; then
    echo "RED: instruction contract adds a second control layer" >&2
    exit 1
fi

expected_names=(
    approval-intent-boundary-check
    avoid-redundant-exploration
    diagnose-by-competing-hypotheses
    preserve-critical-constraints
    reconcile-before-retry
)
for name in "${expected_names[@]}"; do
    skill_file="${skills_root}/${name}/SKILL.md"
    test -f "${skill_file}"
    test "$(sed -n '1p' "${skill_file}")" = '---'
    grep -Eq "^name:[[:space:]]*${name}[[:space:]]*$" "${skill_file}"
    grep -Eq '^description:[[:space:]]*[^[:space:]].*$' "${skill_file}"
    grep -Eq '^assign_when:[[:space:]]*[^[:space:]].*$' "${skill_file}"
    if grep -Fq -- "${name}" "${instructions}"; then
        echo "RED: generic instructions name a concrete Skill" >&2
        exit 1
    fi
done

test ! -e "${package_root}/bundle-manifest.json"
echo "GREEN: native Skill selection/provenance instruction contract"
