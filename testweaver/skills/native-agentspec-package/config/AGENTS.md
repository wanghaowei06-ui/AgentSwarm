# Native Skill selection and evidence discipline

Use this instruction for every task you handle.

1. Start with the runtime's native Skill inventory. For each candidate, evaluate
   the `assign_when` frontmatter and choose zero or more Skills that apply to
   the current task. Do not require or load every Skill by default.
2. For each selected Skill, use the runtime's native Skill loading path to read
   the exact `workspace/skills/<exact-skill-name>/SKILL.md` resolved by that
   inventory. Do not read a package staging directory or create an alternate
   Skill registry.
3. Follow the selected Skill through the normal AgentTeams task/handoff path.
   Return its native result without adding another model, wrapper, or dispatch
   layer. If no Skill applies, do not fabricate a Skill invocation record.
4. For every selected Skill, include a compact provenance record in the normal
   result or handoff. Use these exact fields and preserve the exact Skill name:

   skill_name: <exact Skill name from native inventory/frontmatter>
   source_commit: 19a929ea084c32e0e551881ec709b1d9b1792512
   version: 1.0
   evidence_ref: <stable native task, room, or result reference>

   Use an existing native evidence reference; never expose credentials, hidden
   context, or replace a native event with a receipt or synthetic record.

Package provenance for this instruction set is declared in `manifest.json`:
`source_commit` is `19a929ea084c32e0e551881ec709b1d9b1792512` and `version` is
`1.0`.

## Language boundary

For task bodies and requester-facing reports addressed to or produced for
Human, Manager, Leader, and Worker, use Chinese by default. Keep protocol field names,
code, log keys, evidence identifiers, and resource/Matrix/Task IDs in stable English;
do not translate or alter these identifiers.
